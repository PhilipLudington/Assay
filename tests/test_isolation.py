"""The isolation test. Treated as a correctness test, not a nicety.

If this file fails, every number the project will ever produce is invalid and
the failure is silent — a contaminated run completes normally and reports a
perfect score. DESIGN says so in as many words, and PLAN gates Phase 2 on it.

The structure follows the escape routes rather than the API surface: each test
is a way *out* of `repo/` that a reviewer could plausibly find, and the
assertion is that the boundary closes it. Adding a new route here is cheaper
than discovering it in a published result.

Scope note, stated plainly because the gap matters: these tests prove the
boundary's *logic*. That the Agent SDK honours a `PreToolUse` deny under
`permission_mode="bypassPermissions"` is asserted from the SDK's own
documentation (see `assay.executor.hooks`) and is not exercised here — that
needs a live run, which lands with the first confined measurement run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assay.executor import FixtureLayout, PathBoundary, git_artifacts
from assay.executor.hooks import boundary_hook, confinement_hooks


@pytest.fixture
def layout(tmp_path: Path) -> FixtureLayout:
    """A fixture tree shaped exactly like a corpus fixture."""
    fixture = FixtureLayout(root=tmp_path.resolve())
    (fixture.repo / "src" / "worker").mkdir(parents=True)
    (fixture.repo / "src" / "worker" / "pool.ts").write_text("export const n = 1;\n")
    (fixture.repo / "package.json").write_text("{}\n")
    (fixture.root / "fixture.yaml").write_text("id: TS-0001\n")
    (fixture.root / "ANSWER.md").write_text("The bug is on line 81.\n")
    (fixture.root / "change.patch").write_text("--- a\n+++ b\n")
    return fixture


@pytest.fixture
def boundary(layout: FixtureLayout) -> PathBoundary:
    return PathBoundary(layout.repo)


# --- the work the reviewer is actually supposed to do -----------------------


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"file_path": "src/worker/pool.ts"}),
        ("Read", {"file_path": "./package.json"}),
        ("Glob", {"pattern": "**/*.ts"}),
        ("Glob", {"pattern": "*.ts", "path": "src/worker"}),
        ("Grep", {"pattern": "export", "path": "src"}),
        # A regex containing `..` is a pattern, not a path. Rejecting it would
        # break ordinary searches while buying no safety.
        ("Grep", {"pattern": r"\.\./", "path": "src"}),
        ("Grep", {"pattern": "n", "glob": "*.ts"}),
    ],
)
def test_legitimate_calls_are_allowed(
    boundary: PathBoundary, tool: str, tool_input: dict[str, object]
) -> None:
    assert boundary.check(tool, tool_input) is None


def test_absolute_path_inside_repo_is_allowed(
    boundary: PathBoundary, layout: FixtureLayout
) -> None:
    inside = str(layout.repo / "src" / "worker" / "pool.ts")

    assert boundary.check("Read", {"file_path": inside}) is None


# --- every route to the answer key ------------------------------------------


def test_relative_traversal_to_the_answer_key_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Read", {"file_path": "../fixture.yaml"})

    assert violation is not None
    assert "outside the fixture repo" in violation.reason


def test_traversal_disguised_by_a_descent_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Read", {"file_path": "src/worker/../../../ANSWER.md"})

    assert violation is not None


def test_absolute_path_to_the_answer_key_is_denied(
    boundary: PathBoundary, layout: FixtureLayout
) -> None:
    for key in layout.answer_keys():
        assert key.exists(), "the fixture under test must actually have an answer key"
        assert boundary.check("Read", {"file_path": str(key)}) is not None


def test_symlink_out_of_the_repo_is_denied(
    boundary: PathBoundary, layout: FixtureLayout
) -> None:
    # A string prefix check would pass this: the declared path is inside repo/.
    (layout.repo / "notes.yaml").symlink_to(layout.root / "fixture.yaml")

    violation = boundary.check("Read", {"file_path": "notes.yaml"})

    assert violation is not None
    assert "fixture.yaml" in violation.reason


def test_symlinked_directory_out_of_the_repo_is_denied(
    boundary: PathBoundary, layout: FixtureLayout
) -> None:
    (layout.repo / "up").symlink_to(layout.root, target_is_directory=True)

    assert boundary.check("Read", {"file_path": "up/fixture.yaml"}) is not None


def test_glob_pattern_can_traverse_and_is_denied(boundary: PathBoundary) -> None:
    # The reason Glob.pattern is a checked field: this is a working escape.
    violation = boundary.check("Glob", {"pattern": "../*.yaml"})

    assert violation is not None
    assert violation.field == "pattern"


def test_glob_path_argument_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Glob", {"pattern": "*.md", "path": ".."})

    assert violation is not None
    assert violation.field == "path"


def test_grep_over_the_parent_directory_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Grep", {"pattern": "bug", "path": "../"})

    assert violation is not None
    assert violation.field == "path"


def test_home_directory_expansion_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Read", {"file_path": "~/.anthropic/settings.json"})

    assert violation is not None
    assert "home-directory" in violation.reason


def test_nonexistent_path_outside_the_repo_is_still_denied(
    boundary: PathBoundary,
) -> None:
    # The pilot's 22 out-of-tree attempts failed only because the paths did not
    # exist. Absence is not a control; the boundary must refuse regardless.
    assert boundary.check("Read", {"file_path": "/etc/definitely-not-here"}) is not None


# --- default-deny ------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Bash", "Write", "Edit", "Task", "WebFetch", ""])
def test_tools_outside_the_allowlist_are_denied(
    boundary: PathBoundary, tool: str
) -> None:
    violation = boundary.check(tool, {})

    assert violation is not None
    assert "allowlist" in violation.reason


def test_non_string_path_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Read", {"file_path": ["../fixture.yaml"]})

    assert violation is not None
    assert "expected a string path" in violation.reason


def test_unresolvable_path_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Read", {"file_path": "src\x00/pool.ts"})

    assert violation is not None
    assert "could not be resolved" in violation.reason


# --- version-control history is its own leak channel -------------------------


def test_a_clean_fixture_has_no_history(layout: FixtureLayout) -> None:
    assert git_artifacts(layout.repo) == []


def test_surviving_git_history_is_detected(layout: FixtureLayout) -> None:
    (layout.repo / ".git").mkdir()
    (layout.repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    assert git_artifacts(layout.repo) == [layout.repo / ".git"]


# --- the SDK adapter ---------------------------------------------------------


def pre_tool_use(tool_name: str, tool_input: dict[str, object]) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s-1",
        "transcript_path": "/dev/null",
        "cwd": ".",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "toolu_1",
    }


async def test_hook_denies_and_records_an_escape(boundary: PathBoundary) -> None:
    hook = boundary_hook(boundary)

    output = await hook(pre_tool_use("Read", {"file_path": "../fixture.yaml"}), None, {})  # type: ignore[arg-type]

    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"  # type: ignore[typeddict-item,index]
    (recorded,) = boundary.violations
    assert (recorded.tool, recorded.field, recorded.value) == (
        "Read",
        "file_path",
        "../fixture.yaml",
    )
    assert "outside the fixture repo" in recorded.reason


async def test_hook_stays_silent_on_a_legitimate_call(boundary: PathBoundary) -> None:
    hook = boundary_hook(boundary)

    # Silence, not "allow": approving here would override deny rules set
    # elsewhere in the executor.
    output = await hook(pre_tool_use("Read", {"file_path": "package.json"}), None, {})  # type: ignore[arg-type]

    assert output == {}
    assert boundary.violations == []


async def test_hook_ignores_other_events(boundary: PathBoundary) -> None:
    hook = boundary_hook(boundary)
    event = pre_tool_use("Read", {"file_path": "../fixture.yaml"})
    event["hook_event_name"] = "PostToolUse"

    assert await hook(event, None, {}) == {}  # type: ignore[arg-type]
    assert boundary.violations == []


def test_confinement_hooks_matches_every_tool(layout: FixtureLayout) -> None:
    _, matchers = confinement_hooks(layout.repo)

    (matcher,) = matchers["PreToolUse"]
    assert matcher.matcher is None, "a per-tool matcher would let unknown tools through"
