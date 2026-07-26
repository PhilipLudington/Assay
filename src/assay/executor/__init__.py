"""Executor: how a reviewer is run, and what it is allowed to reach.

The path boundary lives here rather than in `assay.corpus` because it is a
property of *execution*, not of the fixture format — the same fixture is safe
or unsafe depending on how the reviewer is launched.

`assay.executor.hooks` is deliberately not re-exported: it imports the Agent
SDK, and nothing that only needs the boundary's logic should pay for that.
"""

from assay.executor.confinement import (
    GIT_ARTIFACT_NAMES,
    MAX_RECORDED_VALUE_CHARS,
    MAX_RECORDED_VIOLATIONS,
    PATH_FIELDS,
    BoundaryViolation,
    FixtureNotIsolated,
    PathBoundary,
    assert_isolated,
    git_artifacts,
    symlinks,
)

__all__ = [
    "GIT_ARTIFACT_NAMES",
    "MAX_RECORDED_VALUE_CHARS",
    "MAX_RECORDED_VIOLATIONS",
    "PATH_FIELDS",
    "BoundaryViolation",
    "FixtureNotIsolated",
    "PathBoundary",
    "assert_isolated",
    "git_artifacts",
    "symlinks",
]
