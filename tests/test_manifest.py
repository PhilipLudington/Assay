"""Manifest validation.

The acceptance case is the easy half. What matters is that every malformed
manifest is *rejected* — a fixture that loads but is subtly wrong still
produces numbers, and nothing about the output looks wrong.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from assay.corpus import DefectClass, Locality, ManifestError, Severity, load_manifest

VALID = """\
id: TS-0001
title: Correction endpoint bypasses the event log
language: typescript
diff: change.patch
defects:
  - id: TS-0001-d1
    class: broken-invariant
    severity: high
    locality:
      tier: cross_file
      verified: true
      evidence: "0/10 single-shot runs found it (2026-07-26, claude-opus-5)"
    location:
      file: src/routes/shipments.ts
      lines: [81, 81]
    description: >
      The handler writes through the raw repository method, so no tracking
      event is appended and no webhook fires.
distractors:
  - kind: naming-inconsistency
    location:
      file: src/routes/shipments.ts
      lines: [26, 30]
    note: Plausible style complaint about handler naming; not a defect.
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "fixture.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_valid_manifest_loads(tmp_path: Path) -> None:
    manifest = load_manifest(write(tmp_path, VALID))

    assert manifest.id == "TS-0001"
    defect = manifest.defects[0]
    assert defect.defect_class is DefectClass.BROKEN_INVARIANT
    assert defect.severity is Severity.HIGH
    assert defect.locality.tier is Locality.CROSS_FILE
    assert defect.locality.verified is True
    assert manifest.unverified_localities == []


def test_missing_file_is_a_manifest_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="no manifest"):
        load_manifest(tmp_path / "absent.yaml")


def test_malformed_yaml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(write(tmp_path, "id: TS-0001\n  bad: [indent\n"))


def test_non_mapping_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="must contain a mapping"):
        load_manifest(write(tmp_path, "- just\n- a\n- list\n"))


def test_fixture_without_distractors_is_rejected(tmp_path: Path) -> None:
    """Precision is meaningless without something plausible to wrongly flag."""
    text = VALID.split("distractors:")[0] + "distractors: []\n"
    with pytest.raises(ManifestError, match="distractors"):
        load_manifest(write(tmp_path, text))


def test_unknown_defect_class_is_rejected(tmp_path: Path) -> None:
    """The taxonomy is closed; an open vocabulary makes per-class recall meaningless."""
    with pytest.raises(ManifestError, match="broken-invariant|defect_class|class"):
        load_manifest(write(tmp_path, VALID.replace("broken-invariant", "vibes-based")))


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    """A typo'd key must not be silently ignored into a default."""
    with pytest.raises(ManifestError, match="severty|Extra inputs"):
        load_manifest(write(tmp_path, VALID.replace("severity: high", "severty: high")))


def test_defect_id_must_be_prefixed_with_fixture_id(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="prefixed with the fixture id"):
        load_manifest(write(tmp_path, VALID.replace("TS-0001-d1", "d1")))


def test_duplicate_defect_ids_are_rejected(tmp_path: Path) -> None:
    doubled = VALID.replace(
        "distractors:",
        textwrap.dedent(
            """\
              - id: TS-0001-d1
                class: async-race
                severity: low
                locality:
                  tier: local
                location:
                  file: src/routes/shipments.ts
                  lines: [90, 92]
                description: >
                  A second defect deliberately reusing the first defect's id.
            distractors:"""
        ),
    )
    with pytest.raises(ManifestError, match="duplicate defect id"):
        load_manifest(write(tmp_path, doubled))


@pytest.mark.parametrize(
    "bad_id",
    [
        '""',
        '"   "',
        '"TS-0001- d1"',
        '"TS-0001-d1 "',
        '"TS-0001-\\td1"',
        '"TS-0001-d1\\u00a0"',
        "|\n      TS-0001-d1",
        '"TS-0001-d1\\u200b"',
        '"TS-0001-d1\\ufeff"',
        '"TS-0001-d1:x"',
    ],
    ids=[
        "empty",
        "blank",
        "internal-space",
        "trailing-space",
        "tab",
        "non-breaking-space",
        "block-scalar-newline",
        "zero-width-space",
        "byte-order-mark",
        "label-delimiter",
    ],
)
def test_defect_id_must_be_a_bare_token(tmp_path: Path, bad_id: str) -> None:
    """The defect id is the corpus's primary label and gets the same rule as `kind`.

    `assay.eval.precision` spells it `defect:<id>` and validates a hand-written
    label file against these exact strings, so `"TS-0001-d1 "` is only scorable
    by a label file carrying the same invisible trailing space.

    The parametrization mirrors the distractor-kind cases deliberately: both
    fields go through one `_bare_token` helper, and each group of cases pins a
    different property of it. The tab, the NBSP and the `|` block scalar keep
    the rule from being narrowed to `" " in value`. The zero-width space and the
    BOM are why the rule is an allowlist at all: both are `str.isspace()`-False
    and `\\s`-False, so any whitespace blacklist admits them. The colon pins the
    one exclusion that is not about invisibility — it is the label delimiter, so
    `defect:TS-0001-d1:x` cannot be read back into a field and a value.

    The `match` names the field, not just the shared tail: `_bare_token` takes
    `what` as an argument, so two call sites that had their arguments swapped
    would otherwise point every author at the wrong field with every test green.
    """
    text = VALID.replace("id: TS-0001-d1", f"id: {bad_id}")
    with pytest.raises(ManifestError, match="defect id must be a bare token"):
        load_manifest(write(tmp_path, text))


def test_defect_id_of_bare_prefix_is_rejected(tmp_path: Path) -> None:
    """`TS-0001-` passes the prefix check and the token rule, and names no defect.

    This is the one hole the token rule does not cover: it is non-empty and
    carries no whitespace. With one defect in the fixture it looks harmless;
    with two there is nothing left to tell them apart, and `defect:TS-0001-`
    reads as a truncated label rather than an identity.
    """
    text = VALID.replace("id: TS-0001-d1", 'id: "TS-0001-"')
    with pytest.raises(ManifestError, match="fixture prefix with no suffix"):
        load_manifest(write(tmp_path, text))


def test_padded_defect_id_does_not_defeat_the_uniqueness_rule(tmp_path: Path) -> None:
    """The token rule is what keeps `_ids_are_consistent_and_unique` honest.

    Compared as raw strings, `"TS-0001-d1 "` and `"TS-0001-d1"` are distinct
    ids, so a trailing space would have bought a duplicate defect past the
    uniqueness validator — the same defeat a padded kind bought against the
    distractor rule.

    What this pins is the *ordering*, and it is worth being exact about: the
    rejection comes from `Defect.id`'s field validator, which pydantic runs
    while building the second defect, before `_ids_are_consistent_and_unique`
    is ever reached. That is the point — the padded id never survives long
    enough to be compared — so the assertion names the token rule rather than
    the uniqueness message. Exact duplicates stay pinned by
    `test_duplicate_defect_ids_are_rejected`, which is where the uniqueness
    validator itself is exercised.
    """
    doubled = VALID.replace(
        "distractors:",
        textwrap.dedent(
            """\
              - id: "TS-0001-d1 "
                class: async-race
                severity: low
                locality:
                  tier: local
                location:
                  file: src/routes/shipments.ts
                  lines: [90, 92]
                description: >
                  The first defect's id again, with a trailing space nobody can see.
            distractors:"""
        ),
    )
    with pytest.raises(ManifestError, match="defect id must be a bare token"):
        load_manifest(write(tmp_path, doubled))


def test_duplicate_distractor_kinds_are_rejected(tmp_path: Path) -> None:
    """`kind` is what the precision scorer keys bites on, so it must be unique.

    Two distractors sharing a kind merge into one counter in
    `assay.eval.precision` and stay separate in `assay.corpus.locality`, so the
    two reports of one batch would disagree about how many distractors the
    fixture has.
    """
    doubled = VALID + (
        "  - kind: naming-inconsistency\n"
        "    location:\n"
        "      file: src/routes/shipments.ts\n"
        "      lines: [40, 44]\n"
        "    note: A second distractor deliberately reusing the first one's kind.\n"
    )
    with pytest.raises(ManifestError, match="duplicate distractor kind"):
        load_manifest(write(tmp_path, doubled))


@pytest.mark.parametrize(
    "bad_kind",
    [
        '""',
        '"   "',
        '"stale batch timestamp"',
        '"naming-inconsistency "',
        '"stale\\tbatch-timestamp"',
        '"naming-inconsistency\\u00a0"',
        "|\n      naming-inconsistency",
        '"naming-inconsistency\\u200b"',
        '"naming-inconsistency\\ufeff"',
        '"naming:inconsistency"',
    ],
    ids=[
        "empty",
        "blank",
        "internal-space",
        "trailing-space",
        "tab",
        "non-breaking-space",
        "block-scalar-newline",
        "zero-width-space",
        "byte-order-mark",
        "label-delimiter",
    ],
)
def test_distractor_kind_must_be_a_bare_token(tmp_path: Path, bad_kind: str) -> None:
    """`kind` is the distractor's only name, so what is in it is not cosmetic.

    An empty kind labels a nameless bait `distractor:` in
    `assay.eval.precision`, and a label file can only score a padded kind by
    carrying the same invisible padding.

    Mirrors the defect-id parametrization case for case, because both fields go
    through one `_bare_token` helper: the tab and the NBSP prove the rule is not
    `" " in value`; the block scalar is the padded case an author reaches by
    formatting rather than by typo, since YAML hands `kind: |` back with a
    trailing newline; the zero-width space and the BOM are `str.isspace()`-False
    and `\\s`-False, which is why the rule is an allowlist and not a blacklist;
    and the colon is the label delimiter, so `distractor:naming:inconsistency`
    could not be read back into a field and a value.
    """
    text = VALID.replace("kind: naming-inconsistency", f"kind: {bad_kind}")
    with pytest.raises(ManifestError, match="distractor kind must be a bare token"):
        load_manifest(write(tmp_path, text))


def test_padded_kind_does_not_defeat_the_uniqueness_rule(tmp_path: Path) -> None:
    """The rejection above is what keeps `_distractor_kinds_are_unique` honest.

    Compared as raw strings, `"x "` and `"x"` are distinct kinds, so a trailing
    space would have bought a duplicate kind past the uniqueness validator.
    """
    padded = VALID + (
        '  - kind: "naming-inconsistency "\n'
        "    location:\n"
        "      file: src/routes/shipments.ts\n"
        "      lines: [40, 44]\n"
        "    note: The first kind again, with a trailing space nobody can see.\n"
    )
    with pytest.raises(ManifestError, match="distractor kind must be a bare token"):
        load_manifest(write(tmp_path, padded))


@pytest.mark.parametrize(
    "bad_path",
    ["/etc/passwd", "../fixture.yaml", "../../secrets.env"],
)
def test_absolute_and_traversing_paths_are_rejected(tmp_path: Path, bad_path: str) -> None:
    """A location that escapes repo/ would point the matcher outside the fixture."""
    with pytest.raises(ManifestError, match="repo-relative"):
        load_manifest(write(tmp_path, VALID.replace("src/routes/shipments.ts", bad_path)))


def test_backwards_line_range_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="runs backwards"):
        load_manifest(write(tmp_path, VALID.replace("lines: [81, 81]", "lines: [90, 20]")))


def test_zero_indexed_lines_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="1-based"):
        load_manifest(write(tmp_path, VALID.replace("lines: [81, 81]", "lines: [0, 4]")))


def test_verified_locality_without_evidence_is_rejected(tmp_path: Path) -> None:
    """A verified tag with no evidence is an assertion wearing a measurement's name."""
    text = VALID.replace(
        '      evidence: "0/10 single-shot runs found it (2026-07-26, claude-opus-5)"\n',
        "",
    )
    with pytest.raises(ManifestError, match="must carry its evidence"):
        load_manifest(write(tmp_path, text))


def test_unverified_locality_is_allowed_but_reported(tmp_path: Path) -> None:
    """Authoring precedes verification; the manifest must say which it is."""
    text = VALID.replace("      verified: true\n", "").replace(
        '      evidence: "0/10 single-shot runs found it (2026-07-26, claude-opus-5)"\n',
        "",
    )
    manifest = load_manifest(write(tmp_path, text))

    assert manifest.defects[0].locality.verified is False
    assert manifest.unverified_localities == ["TS-0001-d1"]


def test_other_languages_are_rejected(tmp_path: Path) -> None:
    text = VALID.replace("language: typescript", "language: python")
    with pytest.raises(ManifestError, match="v1 ships exactly one language"):
        load_manifest(write(tmp_path, text))


def test_fixture_id_format_is_enforced(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="String should match pattern"):
        load_manifest(write(tmp_path, VALID.replace("id: TS-0001", "id: fixture-one")))
