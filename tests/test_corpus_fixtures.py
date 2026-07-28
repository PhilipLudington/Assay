"""The shipped corpus, checked against the standard it claims to meet.

`test_loader.py` proves the loader rejects a bad fixture; this proves the
fixtures we actually publish are not bad ones. It is a regression test in the
literal sense: a fixture is edited once and then read by every sweep for the
rest of the project's life, so the thing most likely to break it is a later
change to some *other* fixture, or to the loader, with nobody looking here.

Everything `load_fixture` already asserts — patch reversal, anchored ground
truth, structurally possible locality, no answer key inside `repo/`, no VCS
history, no symlinks — is inherited by loading. What this file adds is the
handful of standards that live in the plan rather than in the loader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assay.corpus import Fixture, load_corpus, load_fixture

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "corpus" / "ts"

#: Phase 0 measured how much of a repo an agentic reviewer actually reads: 79%
#: of an 8-file repo, 32% at 25 files, 23% at 50. Below the floor, tool use
#: degenerates into reading the whole tree and the agentic ceiling stops
#: measuring navigation; above the ceiling, nothing is known and cost was only
#: ever measured to 50.
MIN_SOURCE_FILES = 25
MAX_SOURCE_FILES = 50

VCS_DIRECTORY_NAMES = frozenset({".git", ".hg", ".svn"})


def fixture_roots() -> list[Path]:
    return sorted(
        child for child in CORPUS_ROOT.iterdir() if (child / "fixture.yaml").is_file()
    )


def fixture_ids() -> list[str]:
    return [root.name for root in fixture_roots()]


@pytest.fixture(scope="module")
def corpus() -> list[Fixture]:
    return load_corpus(CORPUS_ROOT)


def test_the_corpus_is_not_empty(corpus: list[Fixture]) -> None:
    assert corpus, f"no fixtures under {CORPUS_ROOT}"


@pytest.mark.parametrize("root", fixture_roots(), ids=fixture_ids())
def test_every_shipped_fixture_loads(root: Path) -> None:
    """Loading is the whole validation suite. Fixture by fixture, so a failure
    names the one that broke rather than the corpus."""
    load_fixture(root)


@pytest.mark.parametrize("root", fixture_roots(), ids=fixture_ids())
def test_repo_size_is_inside_the_measured_range(root: Path) -> None:
    sources = list((root / "repo").rglob("*.ts"))
    assert MIN_SOURCE_FILES <= len(sources) <= MAX_SOURCE_FILES, (
        f"{root.name} has {len(sources)} source files; Phase 0 measured navigation "
        f"behaviour only over {MIN_SOURCE_FILES}–{MAX_SOURCE_FILES}, and a repo below "
        "the floor is read whole rather than navigated"
    )


@pytest.mark.parametrize("root", fixture_roots(), ids=fixture_ids())
def test_no_version_control_history_anywhere_under_the_fixture(root: Path) -> None:
    """`assert_isolated` guards `repo/`; this guards the answer key beside it.

    History at the fixture root would carry the defect's commit message — and
    often the fix itself — into whatever is published alongside the corpus.
    """
    found = [
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_dir() and path.name in VCS_DIRECTORY_NAMES
    ]
    assert not found, f"{root.name} ships version-control history: {found}"


def test_every_fixture_carries_a_distractor(corpus: list[Fixture]) -> None:
    """DESIGN's rule, restated where a schema change cannot quietly drop it.

    With nothing plausible to flag wrongly, precision is near 1.0 for any
    reviewer and the metric conveys nothing.
    """
    for fixture in corpus:
        assert fixture.distractors, f"{fixture.id} carries no distractor"


def test_fixture_ids_match_their_directory(corpus: list[Fixture]) -> None:
    for fixture in corpus:
        assert fixture.root.name.startswith(f"{fixture.id}-"), (
            f"{fixture.root.name} declares id {fixture.id}; a directory that disagrees "
            "with its manifest makes a run id impossible to trace back by hand"
        )
