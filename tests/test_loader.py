"""Loading a fixture, and refusing one that contradicts itself.

The acceptance case is one test. The rest are rejections, because a fixture
that loads while being subtly wrong still produces numbers and nothing about
the output looks wrong — the same reason the manifest tests are shaped this way.

Two of these carry more weight than the others. The patch-reversal rejection is
a Phase 1 gate condition: the pilot shipped two patches that had silently
drifted from their trees. The answer-key-inside-`repo/` rejection closes the
one leak the executor's path boundary cannot see, since a reviewer that reads a
copy of the answer key inside `repo/` never crosses the boundary at all.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from assay.corpus import (
    FixtureError,
    Hunk,
    Locality,
    ManifestError,
    load_corpus,
    load_fixture,
    parse_diff,
)
from assay.executor import FixtureNotIsolated

# The post-change state: `total` is summed with a `<=` bound it should not have.
SHIPMENTS_TS = """\
export interface Shipment {
  id: string;
  weightKg: number;
}

export function totalWeight(shipments: Shipment[]): number {
  let total = 0;
  for (let i = 0; i <= shipments.length; i += 1) {
    total += shipments[i].weightKg;
  }
  return total;
}
"""

# Reverses cleanly against SHIPMENTS_TS: line 8 goes back to `<`.
CHANGE_PATCH = """\
diff --git a/src/shipments.ts b/src/shipments.ts
--- a/src/shipments.ts
+++ b/src/shipments.ts
@@ -5,7 +5,7 @@

 export function totalWeight(shipments: Shipment[]): number {
   let total = 0;
-  for (let i = 0; i < shipments.length; i += 1) {
+  for (let i = 0; i <= shipments.length; i += 1) {
     total += shipments[i].weightKg;
   }
   return total;
"""

MANIFEST = """\
id: TS-0001
title: Off-by-one in the shipment weight total
language: typescript
diff: change.patch
defects:
  - id: TS-0001-d1
    class: boundary-error
    severity: high
    locality:
      tier: local
    location:
      file: src/shipments.ts
      lines: [8, 8]
    description: >
      The loop bound reads one past the end of the array, so the final
      iteration dereferences undefined.
distractors:
  - kind: naming-inconsistency
    location:
      file: src/shipments.ts
      lines: [2, 3]
    note: Plausible style complaint about interface field naming; not a defect.
"""


def build(
    root: Path,
    *,
    manifest: str = MANIFEST,
    patch: str = CHANGE_PATCH,
    source: str = SHIPMENTS_TS,
    notes: str | None = "Provenance: hand-authored for the loader tests.\n",
) -> Path:
    """Writes a complete, valid fixture tree. Each test breaks exactly one thing."""
    repo = root / "repo" / "src"
    repo.mkdir(parents=True)
    (repo / "shipments.ts").write_text(source, encoding="utf-8")
    (root / "fixture.yaml").write_text(textwrap.dedent(manifest), encoding="utf-8")
    (root / "change.patch").write_text(patch, encoding="utf-8")
    if notes is not None:
        (root / "NOTES.md").write_text(notes, encoding="utf-8")
    return root


# --- acceptance ------------------------------------------------------------


def test_valid_fixture_loads(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))

    assert fixture.id == "TS-0001"
    assert fixture.touched_files == ("src/shipments.ts",)
    assert fixture.hunks == (Hunk(file="src/shipments.ts", start=5, end=11),)
    assert fixture.defects[0].id == "TS-0001-d1"
    assert fixture.distractors[0].kind == "naming-inconsistency"
    assert fixture.unverified_localities == ["TS-0001-d1"]


def test_load_is_repeatable_and_reads_the_tree_without_writing(tmp_path: Path) -> None:
    """`git apply --check` must not touch `repo/`, or the second load would fail."""
    root = build(tmp_path / "TS-0001")
    before = (root / "repo" / "src" / "shipments.ts").read_text(encoding="utf-8")

    load_fixture(root)
    load_fixture(root)

    assert (root / "repo" / "src" / "shipments.ts").read_text(encoding="utf-8") == before


# --- diff parsing ----------------------------------------------------------


def test_parse_diff_ignores_deleted_files() -> None:
    diff = textwrap.dedent(
        """\
        --- a/src/gone.ts
        +++ /dev/null
        @@ -1,3 +0,0 @@
        -export const gone = 1;
        --- a/src/kept.ts
        +++ b/src/kept.ts
        @@ -1,2 +1,3 @@
         export const kept = 1;
        """
    )
    touched, hunks = parse_diff(diff)

    assert touched == ("src/kept.ts",)
    assert hunks == (Hunk(file="src/kept.ts", start=1, end=3),)


def test_parse_diff_reads_a_single_line_hunk_header() -> None:
    _, hunks = parse_diff("+++ b/a.ts\n@@ -1 +1 @@\n-x\n+y\n")

    assert hunks == (Hunk(file="a.ts", start=1, end=1),)


def test_a_pure_deletion_hunk_is_empty_and_overlaps_nothing() -> None:
    _, hunks = parse_diff("+++ b/a.ts\n@@ -4,2 +3,0 @@\n-x\n-y\n")

    assert hunks[0].is_empty
    assert not hunks[0].overlaps(1, 100)


# --- layout ----------------------------------------------------------------


def test_missing_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="no fixture directory"):
        load_fixture(tmp_path / "absent")


def test_missing_manifest_is_a_manifest_error(tmp_path: Path) -> None:
    root = build(tmp_path / "TS-0001")
    (root / "fixture.yaml").unlink()

    with pytest.raises(ManifestError, match="no manifest"):
        load_fixture(root)


def test_missing_repo_directory_is_rejected(tmp_path: Path) -> None:
    root = build(tmp_path / "TS-0001")
    shutil.rmtree(root / "repo")

    with pytest.raises(FixtureError, match="no repo/ directory"):
        load_fixture(root)


def test_missing_notes_is_rejected(tmp_path: Path) -> None:
    """Provenance is the corpus's only defence of realism, so it is required."""
    with pytest.raises(FixtureError, match="no NOTES.md"):
        load_fixture(build(tmp_path / "TS-0001", notes=None))


def test_missing_patch_is_rejected(tmp_path: Path) -> None:
    root = build(tmp_path / "TS-0001")
    (root / "change.patch").unlink()

    with pytest.raises(FixtureError, match="which is missing"):
        load_fixture(root)


def test_manifest_may_not_point_the_diff_out_of_the_fixture(tmp_path: Path) -> None:
    manifest = MANIFEST.replace("diff: change.patch", "diff: ../../elsewhere.patch")

    with pytest.raises(ManifestError, match="inside the fixture directory"):
        load_fixture(build(tmp_path / "TS-0001", manifest=manifest))


# --- the answer-key boundary ----------------------------------------------


@pytest.mark.parametrize("name", ["fixture.yaml", "NOTES.md"])
def test_an_answer_key_copy_inside_repo_is_rejected(tmp_path: Path, name: str) -> None:
    """The one leak the per-call path boundary cannot see: it never fires."""
    root = build(tmp_path / "TS-0001")
    shutil.copy(root / name, root / "repo" / "src" / name)

    with pytest.raises(FixtureError, match="answer-key copies inside repo/"):
        load_fixture(root)


def test_surviving_git_history_is_rejected(tmp_path: Path) -> None:
    root = build(tmp_path / "TS-0001")
    (root / "repo" / ".git").mkdir()

    with pytest.raises(FixtureNotIsolated, match="version-control history"):
        load_fixture(root)


def test_a_symlink_in_the_repo_is_rejected(tmp_path: Path) -> None:
    root = build(tmp_path / "TS-0001")
    (root / "repo" / "src" / "key.yaml").symlink_to(root / "fixture.yaml")

    with pytest.raises(FixtureNotIsolated, match="symlinks"):
        load_fixture(root)


# --- the diff agrees with the tree ----------------------------------------


def test_a_patch_that_does_not_reverse_is_rejected(tmp_path: Path) -> None:
    """Phase 1 gate condition. The pilot shipped two patches that had drifted."""
    drifted = SHIPMENTS_TS.replace("total += shipments[i].weightKg;", "total += 1;")

    with pytest.raises(FixtureError, match="does not reverse against repo/"):
        load_fixture(build(tmp_path / "TS-0001", source=drifted))


def test_an_empty_patch_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="is empty"):
        load_fixture(build(tmp_path / "TS-0001", patch="\n\n"))


def test_a_patch_with_no_post_image_headers_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="names no post-image files"):
        load_fixture(build(tmp_path / "TS-0001", patch="not a diff at all\n"))


def test_a_diff_touching_a_missing_file_is_rejected(tmp_path: Path) -> None:
    patch = CHANGE_PATCH.replace("src/shipments.ts", "src/absent.ts")

    with pytest.raises(FixtureError, match="touches files absent from repo/"):
        load_fixture(build(tmp_path / "TS-0001", patch=patch))


# --- ground truth is anchored ---------------------------------------------


def test_a_defect_in_a_missing_file_is_rejected(tmp_path: Path) -> None:
    manifest = MANIFEST.replace(
        "      file: src/shipments.ts\n      lines: [8, 8]",
        "      file: src/absent.ts\n      lines: [8, 8]",
    )

    with pytest.raises(FixtureError, match="defect TS-0001-d1 points at src/absent.ts"):
        load_fixture(build(tmp_path / "TS-0001", manifest=manifest))


def test_a_defect_past_the_end_of_its_file_is_rejected(tmp_path: Path) -> None:
    """An unanchored location can never be matched, so its recall is fixed at zero."""
    manifest = MANIFEST.replace("lines: [8, 8]", "lines: [8, 400]")

    with pytest.raises(FixtureError, match="cites lines 8–400"):
        load_fixture(build(tmp_path / "TS-0001", manifest=manifest))


def test_a_distractor_in_a_missing_file_is_rejected(tmp_path: Path) -> None:
    manifest = MANIFEST.replace(
        "      file: src/shipments.ts\n      lines: [2, 3]",
        "      file: src/absent.ts\n      lines: [2, 3]",
    )

    with pytest.raises(FixtureError, match="distractor 1 points at src/absent.ts"):
        load_fixture(build(tmp_path / "TS-0001", manifest=manifest))


# --- locality claims the diff rules out -----------------------------------


def test_structural_locality_reads_the_diff_not_the_manifest(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    location = fixture.defects[0].location

    assert fixture.structural_locality(location) is Locality.LOCAL


def test_local_is_refused_for_a_defect_in_an_untouched_file(tmp_path: Path) -> None:
    root = tmp_path / "TS-0001"
    build(root)
    (root / "repo" / "src" / "other.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (root / "fixture.yaml").write_text(
        MANIFEST.replace(
            "      file: src/shipments.ts\n      lines: [8, 8]",
            "      file: src/other.ts\n      lines: [1, 1]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(FixtureError, match="is not touched by the diff"):
        load_fixture(root)


def test_local_is_refused_for_lines_outside_every_hunk(tmp_path: Path) -> None:
    manifest = MANIFEST.replace("lines: [8, 8]", "lines: [2, 2]")

    with pytest.raises(FixtureError, match="fall outside every diff hunk"):
        load_fixture(build(tmp_path / "TS-0001", manifest=manifest))


def test_a_tag_further_out_than_the_structure_requires_is_allowed(tmp_path: Path) -> None:
    """The pilot's L-1 shape: changed lines are visible, but knowing they are
    wrong needs a file the diff never touched. Only measurement can settle that,
    so the loader must not second-guess a tag in this direction."""
    manifest = MANIFEST.replace("tier: local", "tier: cross_file")

    fixture = load_fixture(build(tmp_path / "TS-0001", manifest=manifest))

    assert fixture.defects[0].locality.tier is Locality.CROSS_FILE


# --- corpus ----------------------------------------------------------------


def test_load_corpus_returns_fixtures_sorted_by_id(tmp_path: Path) -> None:
    build(tmp_path / "b-second", manifest=MANIFEST.replace("TS-0001", "TS-0002"))
    build(tmp_path / "a-first")

    corpus = load_corpus(tmp_path)

    assert [f.id for f in corpus] == ["TS-0001", "TS-0002"]


def test_load_corpus_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Ids key every score, so a collision merges two fixtures' results silently."""
    build(tmp_path / "one")
    build(tmp_path / "two")

    with pytest.raises(FixtureError, match="duplicate fixture id"):
        load_corpus(tmp_path)


def test_load_corpus_ignores_directories_without_a_manifest(tmp_path: Path) -> None:
    build(tmp_path / "TS-0001")
    (tmp_path / "scratch").mkdir()

    assert [f.id for f in load_corpus(tmp_path)] == ["TS-0001"]


def test_one_broken_fixture_fails_the_whole_corpus(tmp_path: Path) -> None:
    """Skipping it would quietly measure 14 fixtures while the README says 15."""
    build(tmp_path / "TS-0001")
    build(tmp_path / "TS-0002", manifest=MANIFEST.replace("TS-0001", "TS-0002"), notes=None)

    with pytest.raises(FixtureError, match="no NOTES.md"):
        load_corpus(tmp_path)
