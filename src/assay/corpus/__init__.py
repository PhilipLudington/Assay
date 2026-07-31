"""Corpus format: manifest schema, taxonomy, loader, locality verification.

`assay.corpus.locality` is deliberately not re-exported, matching
`assay.executor`'s rule for `hooks` and `probe`: it imports the Anthropic SDK in
order to run a reviewer, and nothing that only needs to *load* a fixture should
pay for that import. Re-exporting it would also make
`python -m assay.corpus.locality` import the module twice.
"""

from assay.corpus.loader import (
    LOCALITY_ORDER,
    MANIFEST_NAME,
    NOTES_NAME,
    REPO_DIR,
    Fixture,
    FixtureError,
    Hunk,
    load_corpus,
    load_fixture,
    parse_diff,
)
from assay.corpus.manifest import (
    Defect,
    Distractor,
    FixtureManifest,
    LocalityTag,
    Location,
    ManifestError,
    load_manifest,
)
from assay.corpus.taxonomy import (
    EXCLUDED_CLASSES,
    TAXONOMY,
    ClassDefinition,
    DefectClass,
    Locality,
    Severity,
    all_classes,
    describe,
)

__all__ = [
    "EXCLUDED_CLASSES",
    "LOCALITY_ORDER",
    "MANIFEST_NAME",
    "NOTES_NAME",
    "REPO_DIR",
    "TAXONOMY",
    "ClassDefinition",
    "Defect",
    "DefectClass",
    "Distractor",
    "Fixture",
    "FixtureError",
    "FixtureManifest",
    "Hunk",
    "Locality",
    "LocalityTag",
    "Location",
    "ManifestError",
    "Severity",
    "all_classes",
    "describe",
    "load_corpus",
    "load_fixture",
    "load_manifest",
    "parse_diff",
]
