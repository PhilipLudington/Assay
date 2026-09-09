"""The `fixture.yaml` schema.

This file is the answer key. It lives outside `repo/` and must stay
unreachable from it — see `assay.executor` for the enforcement and the
isolation test for the proof.

Everything here fails loudly. A manifest that is malformed, incomplete, or
merely *plausible* is worse than a missing one: the run still produces
numbers, and nothing about the output looks wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from assay.corpus.taxonomy import DefectClass, Locality, Severity


class ManifestError(ValueError):
    """Raised when a manifest is unusable. Never downgraded to a warning."""


def _bare_token(value: str, what: str) -> str:
    """Rejects a name that is empty or carries whitespace anywhere.

    Both of the manifest's identity fields — `Defect.id` and `Distractor.kind` —
    are spelled by hand into a label file (`defect:<id>`, `distractor:<kind>`)
    and compared as raw strings by the uniqueness validators below. That makes
    the same two failures apply to both: `""` names something with no name, and
    `"x "` versus `"x"` are two identities that read as one, so a keystroke
    nobody can see buys a duplicate past a uniqueness check and forces a label
    file to carry the same invisible padding to score at all.

    The test is `str.isspace()` rather than `" " in value` or a `\\S` pattern,
    because a tab, a non-breaking space, and the trailing newline YAML hands
    back from a `|` block scalar are all padding an author reaches without
    typing a space. It is a rejection rather than a strip: stripping would
    accept the padded manifest and then disagree with its own text, which is
    what a hand-written label file is written against.
    """
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"{what} must be a non-empty token with no whitespace, got {value!r}")
    return value


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str = Field(description="Path relative to repo/, e.g. src/worker/pool.ts")
    lines: tuple[int, int] = Field(description="Inclusive [start, end] line range")

    @field_validator("file")
    @classmethod
    def _repo_relative(cls, value: str) -> str:
        if value.startswith("/") or ".." in Path(value).parts:
            raise ValueError(f"must be a repo-relative path without traversal: {value!r}")
        return value

    @field_validator("lines")
    @classmethod
    def _ordered(cls, value: tuple[int, int]) -> tuple[int, int]:
        start, end = value
        if start < 1:
            raise ValueError(f"line numbers are 1-based: {value!r}")
        if end < start:
            raise ValueError(f"line range runs backwards: {value!r}")
        return value


class LocalityTag(BaseModel):
    """A locality claim, plus the evidence for it.

    DESIGN makes locality a measurement rather than an author's assertion: run
    the single-shot reviewer with no tools, and a defect it finds is not
    `cross_file` whatever the author intended. The Phase 0 pilot produced two
    wrong tags out of three while the author was actively trying to avoid
    exactly that, so `verified` defaults to False and scoring treats an
    unverified `cross_file` claim as untrustworthy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: Locality
    verified: bool = False
    evidence: str | None = Field(
        default=None,
        description=(
            "How the tier was established — e.g. '0/10 single-shot runs found it "
            "(2026-07-26, claude-opus-5)'. Required once verified is True."
        ),
    )

    @model_validator(mode="after")
    def _evidence_present_when_verified(self) -> LocalityTag:
        if self.verified and not self.evidence:
            raise ValueError("verified locality must carry its evidence")
        return self


class Defect(BaseModel):
    # populate_by_name so `class:` in YAML maps onto `defect_class` in Python.
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(description="Fixture id, a hyphen, and a suffix, e.g. TS-0001-d1")
    defect_class: Annotated[DefectClass, Field(alias="class")]
    severity: Severity
    locality: LocalityTag
    location: Location
    description: str = Field(min_length=20)

    @field_validator("id")
    @classmethod
    def _id_is_a_bare_token(cls, value: str) -> str:
        """A defect id is the corpus's *primary* label, so it is held to the token rule.

        `assay.eval.precision` spells it `defect:<id>` and validates a label file
        against these exact strings, so a padded id is only scorable by a label
        file padded to match. Whether the suffix after the fixture prefix is
        present at all is checked in `_ids_are_consistent_and_unique`, which is
        the only place that knows the fixture's own id.
        """
        return _bare_token(value, "defect id")


class Distractor(BaseModel):
    """Something a reviewer can plausibly but wrongly flag.

    Load-bearing, not decoration. With nothing plausible to flag wrongly,
    precision approaches 1.0 for any reviewer and the metric conveys nothing —
    which is also why every fixture is required to carry at least one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(description="Bare token naming this bait, e.g. stale-batch-timestamp")
    location: Location
    note: str = Field(min_length=10, description="Why this is bait and why it is not a defect")

    @field_validator("kind")
    @classmethod
    def _kind_is_a_bare_token(cls, value: str) -> str:
        """A kind is the distractor's only name, so it is held to the token rule."""
        return _bare_token(value, "distractor kind")


class FixtureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^TS-\d{4}$")
    title: str = Field(min_length=10)
    language: str = Field(default="typescript")
    diff: str = Field(default="change.patch")
    defects: list[Defect] = Field(min_length=1)
    distractors: list[Distractor] = Field(min_length=1)

    @field_validator("diff")
    @classmethod
    def _diff_is_a_sibling_file(cls, value: str) -> str:
        """The patch lives beside `repo/`, not above the fixture root.

        Unvalidated, `diff: ../../secrets` would have the loader read an
        arbitrary file and hand it to a reviewer as the change under review.
        """
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError(
                f"must name a file inside the fixture directory, got {value!r}"
            )
        return value

    @field_validator("language")
    @classmethod
    def _typescript_only(cls, value: str) -> str:
        if value != "typescript":
            raise ValueError(
                f"v1 ships exactly one language; got {value!r}. Bug taxonomies are "
                "not portable, so adding a language means adding a taxonomy."
            )
        return value

    @model_validator(mode="after")
    def _ids_are_consistent_and_unique(self) -> FixtureManifest:
        prefix = f"{self.id}-"
        seen: set[str] = set()
        for defect in self.defects:
            if not defect.id.startswith(prefix):
                raise ValueError(
                    f"defect id {defect.id!r} must be prefixed with the fixture id "
                    f"{self.id!r}, so a finding can be traced to its fixture"
                )
            if defect.id == prefix:
                # The prefix alone names the fixture, not a defect in it. A
                # one-defect fixture makes that look harmless; the moment a
                # second defect is added there is nothing left to tell them
                # apart, and `defect:TS-0001-` is a label that reads as a typo.
                raise ValueError(
                    f"defect id {defect.id!r} is the fixture prefix with no suffix; "
                    f"it must name a specific defect, e.g. {prefix}d1"
                )
            if defect.id in seen:
                raise ValueError(f"duplicate defect id {defect.id!r}")
            seen.add(defect.id)
        return self

    @model_validator(mode="after")
    def _distractor_kinds_are_unique(self) -> FixtureManifest:
        """`kind` is a distractor's identity, and the two scorers disagree about it.

        `assay.eval.precision` keys bites on `distractor:<kind>` alone, so two
        distractors sharing a kind merge into one counter and a label file cannot
        say which was bitten. `assay.corpus.locality` keys on
        `distractor-<i>:<kind>`, which stays distinct. Both reports would be
        internally consistent and disagree with each other about how many
        distractors this fixture has — the shape of error the manifest exists to
        make impossible.
        """
        seen: set[str] = set()
        for distractor in self.distractors:
            if distractor.kind in seen:
                raise ValueError(f"duplicate distractor kind {distractor.kind!r}")
            seen.add(distractor.kind)
        return self

    @property
    def unverified_localities(self) -> list[str]:
        return [d.id for d in self.defects if not d.locality.verified]


def load_manifest(path: Path) -> FixtureManifest:
    """Parses and validates a fixture.yaml. Raises ManifestError on anything wrong."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ManifestError(f"no manifest at {path}") from error
    except yaml.YAMLError as error:
        raise ManifestError(f"{path} is not valid YAML: {error}") from error

    if not isinstance(raw, dict):
        raise ManifestError(f"{path} must contain a mapping, got {type(raw).__name__}")

    try:
        return FixtureManifest.model_validate(raw)
    except ValueError as error:
        raise ManifestError(f"{path} is not a valid fixture manifest:\n{error}") from error
