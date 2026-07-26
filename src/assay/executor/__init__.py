"""Executor: how a reviewer is run, and what it is allowed to reach.

The path boundary lives here rather than in `assay.corpus` because it is a
property of *execution*, not of the fixture format — the same fixture is safe
or unsafe depending on how the reviewer is launched.
"""

from assay.executor.confinement import (
    GIT_ARTIFACT_NAMES,
    PATH_FIELDS,
    BoundaryViolation,
    FixtureLayout,
    PathBoundary,
    git_artifacts,
)

__all__ = [
    "GIT_ARTIFACT_NAMES",
    "PATH_FIELDS",
    "BoundaryViolation",
    "FixtureLayout",
    "PathBoundary",
    "git_artifacts",
]
