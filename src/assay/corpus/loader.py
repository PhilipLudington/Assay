"""Loading a fixture from disk, and refusing the ones that would lie.

`load_manifest` proves the answer key is *well-formed*. That is not the same as
proving it is *true of this tree*, and the gap between the two is where a
corpus rots: a manifest can name a line range in a file that no longer exists,
or a diff can drift from the repo it claims to describe, and every downstream
number still computes. The Phase 0 pilot caught two patches that had silently
drifted from their trees — while the author was actively watching for it.

So the loader checks the manifest against the tree, and every check fails
loudly:

- **The diff reverses against `repo/`.** `repo/` holds the post-change state,
  so `git apply --reverse --check` succeeding is the proof that `change.patch`
  is the change that produced this tree. A drifted patch means the reviewer is
  asked to review one change while being scored against another.
- **Ground truth is anchored.** Every defect and distractor location names a
  file that exists and a line range inside it. An unanchored location cannot be
  matched against, so recall on it would be permanently zero for reasons that
  have nothing to do with the reviewer.
- **The claimed locality tier is structurally possible.** Locality is settled by
  measurement, not by this module (see the `structural_locality` docstring for
  where the line falls), but the diff's shape rules some claims out outright.
- **The answer key is not inside `repo/`.** Plus the two precondition checks
  `assay.executor` owns — surviving VCS history and symlinks.

Isolation is imported from `assay.executor` rather than reimplemented. The
boundary is a property of execution, and one definition of it is the only way
the isolation test can be evidence about what a run actually does. Loading is
the earliest moment the problem is visible, which is why the check runs here
too: a fixture that can leak should fail while it is being authored, not after
tokens have been spent on it.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from assay.corpus.manifest import (
    Defect,
    Distractor,
    FixtureManifest,
    Location,
    load_manifest,
)
from assay.corpus.taxonomy import Locality
from assay.executor.confinement import assert_isolated

#: The fixture layout from DESIGN. `repo/` is the reviewer's cwd and the hard
#: boundary; everything beside it is answer key or author-facing provenance.
MANIFEST_NAME = "fixture.yaml"
NOTES_NAME = "NOTES.md"
REPO_DIR = "repo"

#: Files that must never appear inside `repo/`, under any name-mangling. A copy
#: of the answer key inside the boundary defeats the boundary without ever
#: tripping it — the reviewer stays in `repo/` the whole time.
FORBIDDEN_INSIDE_REPO = (MANIFEST_NAME, NOTES_NAME)

#: Ordered near-to-far. `structural_locality` returns the closest tier the diff
#: permits, and a manifest may claim that tier or any further one.
LOCALITY_ORDER: tuple[Locality, ...] = (
    Locality.LOCAL,
    Locality.TOUCHED_FILE,
    Locality.CROSS_FILE,
)

_POST_IMAGE_FILE = re.compile(r"^\+\+\+ (.+)$")
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class FixtureError(RuntimeError):
    """A fixture on disk contradicts its manifest. Never downgraded to a warning."""


@dataclass(frozen=True)
class Hunk:
    """One post-image line range from the diff, in `repo/` coordinates.

    Post-image rather than pre-image because every other line number in the
    system — manifest locations, reviewer findings — refers to the state the
    reviewer is looking at.
    """

    file: str
    start: int
    end: int

    @property
    def is_empty(self) -> bool:
        """True for a pure-deletion hunk, which adds no post-image lines.

        Only reachable from a zero-context diff: with git's default three lines
        of context, a deletion still carries surrounding post-image lines.
        """
        return self.end < self.start

    def contains(self, line: int) -> bool:
        return not self.is_empty and self.start <= line <= self.end

    def overlaps(self, start: int, end: int) -> bool:
        """An empty hunk overlaps nothing — it occupies no post-image lines,
        so no manifest location can be inside it."""
        if self.is_empty:
            return False
        return not (self.end < start or end < self.start)


def parse_diff(diff: str) -> tuple[tuple[str, ...], tuple[Hunk, ...]]:
    """Returns the files the diff touches and their post-image hunk ranges.

    Deliberately a parser for the git-format unified diffs the corpus ships,
    not a general one: an unrecognised diff yields no hunks, and the callers
    that matter treat "no touched files" as a fixture error rather than as an
    empty result.
    """
    touched: list[str] = []
    hunks: list[Hunk] = []
    current: str | None = None

    for line in diff.splitlines():
        header = _POST_IMAGE_FILE.match(line)
        if header:
            # Strip the trailing timestamp some diff producers append.
            raw = header.group(1).split("\t")[0].strip()
            if raw == "/dev/null":
                # A deleted file has no post-image, so nothing can be located
                # in it and no reviewer can read it.
                current = None
                continue
            path = raw[2:] if raw.startswith(("a/", "b/")) else raw
            current = path
            if path not in touched:
                touched.append(path)
            continue

        if current is None:
            continue
        hunk = _HUNK_HEADER.match(line)
        if hunk:
            start = int(hunk.group(1))
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            hunks.append(Hunk(file=current, start=start, end=start + count - 1))

    return tuple(touched), tuple(hunks)


@dataclass(frozen=True)
class Fixture:
    """A validated fixture: manifest, tree, and the diff that connects them.

    Constructed only through `load_fixture`. A `Fixture` in hand means every
    check in this module passed, so nothing downstream re-derives them.
    """

    root: Path
    manifest: FixtureManifest
    diff: str

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def repo(self) -> Path:
        return self.root / REPO_DIR

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def notes_path(self) -> Path:
        return self.root / NOTES_NAME

    @property
    def patch_path(self) -> Path:
        return self.root / self.manifest.diff

    @property
    def defects(self) -> list[Defect]:
        return list(self.manifest.defects)

    @property
    def distractors(self) -> list[Distractor]:
        return list(self.manifest.distractors)

    @cached_property
    def _parsed(self) -> tuple[tuple[str, ...], tuple[Hunk, ...]]:
        return parse_diff(self.diff)

    @property
    def touched_files(self) -> tuple[str, ...]:
        """Repo-relative paths the diff modifies, in diff order.

        The review-context floor is built from these (DESIGN: the diff plus the
        full contents of every file it touches). Phase 2 assembles the floor
        itself; the loader only has to agree with it about which files those are.
        """
        return self._parsed[0]

    @property
    def hunks(self) -> tuple[Hunk, ...]:
        return self._parsed[1]

    def structural_locality(self, location: Location) -> Locality:
        """The closest locality tier the diff's shape permits for `location`.

        This is a *bound*, not a measurement, and the distinction is the whole
        point. Whether a defect is genuinely `cross_file` depends on what a
        reviewer can infer, which only a run can answer — the pilot mis-tagged
        two of three defects precisely because the author reasoned about it
        instead of measuring it. What the diff does settle is the other
        direction: a defect whose own lines are not in the diff cannot be
        `local`, however obvious it looks to its author.

        So the manifest may claim this tier or any tier further out, and the
        measured verification step may push it further out still. It may never
        pull it closer.
        """
        if location.file not in self.touched_files:
            return Locality.CROSS_FILE
        start, end = location.lines
        if any(h.file == location.file and h.overlaps(start, end) for h in self.hunks):
            return Locality.LOCAL
        return Locality.TOUCHED_FILE

    @property
    def unverified_localities(self) -> list[str]:
        """Defect ids whose locality tag has not been established by measurement."""
        return self.manifest.unverified_localities


def load_fixture(root: Path) -> Fixture:
    """Loads and fully validates the fixture rooted at `root`.

    Raises `ManifestError` if the manifest is malformed, `FixtureError` if the
    manifest and the tree disagree, and `FixtureNotIsolated` if the fixture
    could leak its own answer. Three types because the three are different
    problems with different fixes, and collapsing them would make the message
    the only thing carrying that information.
    """
    if not root.is_dir():
        raise FixtureError(f"no fixture directory at {root}")

    manifest = load_manifest(root / MANIFEST_NAME)

    repo = root / REPO_DIR
    if not repo.is_dir():
        raise FixtureError(f"{manifest.id}: no {REPO_DIR}/ directory in {root}")
    if not (root / NOTES_NAME).is_file():
        raise FixtureError(
            f"{manifest.id}: no {NOTES_NAME} — a fixture without recorded provenance "
            "cannot be defended as realistic, and realism is the corpus's only claim"
        )

    patch_path = root / manifest.diff
    if not patch_path.is_file():
        raise FixtureError(f"{manifest.id}: manifest names {manifest.diff}, which is missing")
    diff = patch_path.read_text(encoding="utf-8")

    fixture = Fixture(root=root, manifest=manifest, diff=diff)

    _assert_answer_key_outside_repo(fixture)
    assert_isolated(repo)
    _assert_diff_is_usable(fixture)
    _assert_patch_reverses(fixture, patch_path)
    _assert_ground_truth_is_anchored(fixture)
    _assert_localities_are_possible(fixture)

    return fixture


def load_corpus(root: Path) -> list[Fixture]:
    """Loads every fixture directly under `root`, sorted by id.

    One malformed fixture fails the whole load. Skipping it would silently
    shrink the corpus, and a corpus that quietly measures 14 fixtures while the
    README says 15 is exactly the kind of error this project exists to catch.
    """
    if not root.is_dir():
        raise FixtureError(f"no corpus directory at {root}")

    fixtures = [
        load_fixture(child)
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / MANIFEST_NAME).is_file()
    ]

    by_id: dict[str, Path] = {}
    for fixture in fixtures:
        if fixture.id in by_id:
            raise FixtureError(
                f"duplicate fixture id {fixture.id!r} in {by_id[fixture.id]} and "
                f"{fixture.root} — ids key every score, so a collision merges two "
                "fixtures' results without saying so"
            )
        by_id[fixture.id] = fixture.root

    return sorted(fixtures, key=lambda f: f.id)


def _assert_answer_key_outside_repo(fixture: Fixture) -> None:
    """The boundary is only a boundary if the answer is not on both sides of it."""
    repo = fixture.repo.resolve()
    for path in (fixture.manifest_path, fixture.notes_path, fixture.patch_path):
        resolved = path.resolve()
        if resolved == repo or resolved.is_relative_to(repo):
            raise FixtureError(
                f"{fixture.id}: {path.name} resolves inside {REPO_DIR}/ — a reviewer "
                "reaches the answer key without ever crossing the path boundary"
            )

    strays = sorted(
        p for p in fixture.repo.rglob("*") if p.is_file() and p.name in FORBIDDEN_INSIDE_REPO
    )
    if strays:
        listed = ", ".join(str(p.relative_to(fixture.repo)) for p in strays)
        raise FixtureError(f"{fixture.id}: answer-key copies inside {REPO_DIR}/: {listed}")


def _assert_diff_is_usable(fixture: Fixture) -> None:
    if not fixture.diff.strip():
        raise FixtureError(f"{fixture.id}: {fixture.manifest.diff} is empty")
    if not fixture.touched_files:
        raise FixtureError(
            f"{fixture.id}: {fixture.manifest.diff} names no post-image files — "
            "expected a git-format unified diff with `+++ b/<path>` headers"
        )
    missing = [name for name in fixture.touched_files if not (fixture.repo / name).is_file()]
    if missing:
        raise FixtureError(
            f"{fixture.id}: diff touches files absent from {REPO_DIR}/: {', '.join(missing)}"
        )


def _assert_patch_reverses(fixture: Fixture, patch_path: Path) -> None:
    """`repo/` holds the post-change state, so the diff must undo it exactly.

    `--check` performs no write, so this runs against `repo/` in place rather
    than a copy. Read-only is asserted by the flag, not assumed: `git apply`
    without `--check` is the writing form and is never invoked here.
    """
    try:
        result = subprocess.run(
            ["git", "apply", "--reverse", "--check", str(patch_path.resolve())],
            cwd=fixture.repo,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise FixtureError(
            f"{fixture.id}: git is required to validate {fixture.manifest.diff} against "
            f"{REPO_DIR}/, and is not on PATH"
        ) from error

    if result.returncode != 0:
        raise FixtureError(
            f"{fixture.id}: {fixture.manifest.diff} does not reverse against {REPO_DIR}/ — "
            "the tree and the diff have drifted apart, so the reviewer would be scored "
            f"against a change it was not shown ({result.stderr.strip()})"
        )


def _assert_ground_truth_is_anchored(fixture: Fixture) -> None:
    """Every location must name a real file and a line range inside it."""
    for defect in fixture.defects:
        _assert_location_exists(fixture, defect.location, f"defect {defect.id}")
    for index, distractor in enumerate(fixture.distractors, start=1):
        _assert_location_exists(fixture, distractor.location, f"distractor {index}")


def _assert_location_exists(fixture: Fixture, location: Location, label: str) -> None:
    path = fixture.repo / location.file
    if not path.is_file():
        raise FixtureError(
            f"{fixture.id}: {label} points at {location.file}, which does not exist "
            f"in {REPO_DIR}/"
        )
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    start, end = location.lines
    if end > line_count:
        raise FixtureError(
            f"{fixture.id}: {label} cites lines {start}–{end} of {location.file}, which "
            f"has {line_count} — an unanchored location can never be matched, so its "
            "recall is zero for reasons unrelated to the reviewer"
        )


def _assert_localities_are_possible(fixture: Fixture) -> None:
    for defect in fixture.defects:
        claimed = defect.locality.tier
        possible = fixture.structural_locality(defect.location)
        if LOCALITY_ORDER.index(claimed) < LOCALITY_ORDER.index(possible):
            raise FixtureError(
                f"{fixture.id}: defect {defect.id} claims locality {claimed.value!r}, but "
                f"the diff's shape allows no closer than {possible.value!r} "
                f"({location_reason(possible, defect.location.file)}). A tag may be "
                "further out than the structure requires, never closer"
            )


def location_reason(possible: Locality, file: str) -> str:
    if possible is Locality.CROSS_FILE:
        return f"{file} is not touched by the diff"
    return f"the cited lines of {file} fall outside every diff hunk"
