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

    id: str
    defect_class: Annotated[DefectClass, Field(alias="class")]
    severity: Severity
    locality: LocalityTag
    location: Location
    description: str = Field(min_length=20)


class Distractor(BaseModel):
    """Something a reviewer can plausibly but wrongly flag.

    Load-bearing, not decoration. With nothing plausible to flag wrongly,
    precision approaches 1.0 for any reviewer and the metric conveys nothing —
    which is also why every fixture is required to carry at least one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    location: Location
    note: str = Field(min_length=10, description="Why this is bait and why it is not a defect")


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
        seen: set[str] = set()
        for defect in self.defects:
            if not defect.id.startswith(f"{self.id}-"):
                raise ValueError(
                    f"defect id {defect.id!r} must be prefixed with the fixture id "
                    f"{self.id!r}, so a finding can be traced to its fixture"
                )
            if defect.id in seen:
                raise ValueError(f"duplicate defect id {defect.id!r}")
            seen.add(defect.id)
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
