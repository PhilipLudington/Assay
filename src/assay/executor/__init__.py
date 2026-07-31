"""Executor: how a reviewer is run, and what it is allowed to reach.

The path boundary lives here rather than in `assay.corpus` because it is a
property of *execution*, not of the fixture format — the same fixture is safe
or unsafe depending on how the reviewer is launched.

`assay.executor.hooks` and `assay.executor.probe` are deliberately not
re-exported: they import the Agent SDK, and nothing that only needs the
boundary's logic or the tool policy should pay for that.
"""

from assay.executor.confinement import (
    CONTROL_PLANE_TOOLS,
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
from assay.executor.policy import DENIED_TOOLS, READ_ONLY_TOOLS

__all__ = [
    "CONTROL_PLANE_TOOLS",
    "DENIED_TOOLS",
    "GIT_ARTIFACT_NAMES",
    "MAX_RECORDED_VALUE_CHARS",
    "MAX_RECORDED_VIOLATIONS",
    "PATH_FIELDS",
    "READ_ONLY_TOOLS",
    "BoundaryViolation",
    "FixtureNotIsolated",
    "PathBoundary",
    "assert_isolated",
    "git_artifacts",
    "symlinks",
]
