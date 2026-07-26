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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from assay.executor import (
    GIT_ARTIFACT_NAMES,
    MAX_RECORDED_VALUE_CHARS,
    MAX_RECORDED_VIOLATIONS,
    BoundaryViolation,
    FixtureNotIsolated,
    PathBoundary,
    assert_isolated,
    git_artifacts,
    symlinks,
)
from assay.executor.hooks import boundary_hook, confinement_hooks


@dataclass
class Fixture:
    """A fixture tree shaped like a corpus fixture.

    Deliberately a *test* helper. An earlier revision exported this from
    `assay.executor`, which put fixture-on-disk knowledge in the execution
    layer, duplicated `pilot/common.py`, and pre-empted the corpus loader that
    will own the real thing. Layout belongs to `assay.corpus`; this is scaffolding.
    """

    root: Path

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    def answer_keys(self) -> list[Path]:
        return [self.root / "fixture.yaml", self.root / "ANSWER.md"]


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    built = Fixture(root=tmp_path.resolve())
    (built.repo / "src" / "worker").mkdir(parents=True)
    (built.repo / "src" / "worker" / "pool.ts").write_text("export const n = 1;\n")
    (built.repo / "package.json").write_text("{}\n")
    (built.root / "fixture.yaml").write_text("id: TS-0001\n")
    (built.root / "ANSWER.md").write_text("The bug is on line 81.\n")
    (built.root / "change.patch").write_text("--- a\n+++ b\n")
    return built


@pytest.fixture
def boundary(fixture: Fixture) -> PathBoundary:
    return PathBoundary(fixture.repo)


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
        # Recognised tool, no path argument at all: nothing to object to.
        ("Read", {}),
        ("Grep", {"pattern": "n", "path": None}),
    ],
)
def test_legitimate_calls_are_allowed(
    boundary: PathBoundary, tool: str, tool_input: dict[str, Any]
) -> None:
    assert boundary.check(tool, tool_input) is None


def test_absolute_path_inside_repo_is_allowed(
    boundary: PathBoundary, fixture: Fixture
) -> None:
    inside = str(fixture.repo / "src" / "worker" / "pool.ts")

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
    boundary: PathBoundary, fixture: Fixture
) -> None:
    for key in fixture.answer_keys():
        assert key.exists(), "the fixture under test must actually have an answer key"
        assert boundary.check("Read", {"file_path": str(key)}) is not None


def test_symlink_out_of_the_repo_is_denied(
    boundary: PathBoundary, fixture: Fixture
) -> None:
    # A string prefix check would pass this: the declared path is inside repo/.
    (fixture.repo / "notes.yaml").symlink_to(fixture.root / "fixture.yaml")

    violation = boundary.check("Read", {"file_path": "notes.yaml"})

    assert violation is not None
    assert "fixture.yaml" in violation.reason


def test_symlinked_directory_out_of_the_repo_is_denied(
    boundary: PathBoundary, fixture: Fixture
) -> None:
    (fixture.repo / "up").symlink_to(fixture.root, target_is_directory=True)

    assert boundary.check("Read", {"file_path": "up/fixture.yaml"}) is not None


def test_sibling_directory_sharing_a_name_prefix_is_denied(
    boundary: PathBoundary, fixture: Fixture
) -> None:
    # The classic string-prefix bug: `/tmp/x/repo-evil` starts with `/tmp/x/repo`.
    evil = fixture.root / "repo-evil"
    evil.mkdir()
    (evil / "leak.txt").write_text("answer\n")

    assert boundary.check("Read", {"file_path": str(evil / "leak.txt")}) is not None


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


def test_grep_glob_filter_can_traverse_and_is_denied(boundary: PathBoundary) -> None:
    # `glob` is declared in PATH_FIELDS; this is the test that proves the
    # declaration does something. Its absence was a QA finding.
    violation = boundary.check("Grep", {"pattern": "bug", "glob": "../*.yaml"})

    assert violation is not None
    assert violation.field == "glob"


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


def test_non_mapping_tool_input_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Read", "../fixture.yaml")  # type: ignore[arg-type]

    assert violation is not None
    assert "expected a tool input mapping" in violation.reason


def test_unresolvable_path_is_denied(boundary: PathBoundary) -> None:
    violation = boundary.check("Read", {"file_path": "src\x00/pool.ts"})

    assert violation is not None
    assert "could not be resolved" in violation.reason


@pytest.mark.parametrize("error", [OSError("boom"), RuntimeError("symlink loop")])
def test_resolution_failure_is_denied(
    boundary: PathBoundary, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    # The symlink-loop branch is platform-dependent and cannot be provoked
    # portably, so the failure is injected instead. The assertion that matters
    # is the direction: an unresolvable path denies, never allows.
    def explode(self: Path, *args: Any, **kwargs: Any) -> Path:
        raise error

    monkeypatch.setattr(Path, "resolve", explode)

    violation = boundary.check("Read", {"file_path": "src/worker/pool.ts"})

    assert violation is not None
    assert "could not be resolved" in violation.reason


# --- recorded evidence is bounded --------------------------------------------


def test_violations_are_capped_but_the_overflow_is_counted(
    boundary: PathBoundary,
) -> None:
    for _ in range(MAX_RECORDED_VIOLATIONS + 5):
        violation = boundary.check("Read", {"file_path": "../fixture.yaml"})
        assert violation is not None
        boundary.record(violation)

    # "We stopped recording" and "it stopped happening" must stay distinguishable.
    assert len(boundary.violations) == MAX_RECORDED_VIOLATIONS
    assert boundary.suppressed_violations == 5


def test_recorded_value_is_truncated(boundary: PathBoundary) -> None:
    huge = "../" + "a" * (MAX_RECORDED_VALUE_CHARS * 2)
    violation = boundary.check("Read", {"file_path": huge})
    assert violation is not None

    record = violation.as_record()

    assert len(record["value"]) < len(huge)
    assert record["value"].endswith("…[truncated]")


def test_records_round_trip_the_fields_a_transcript_needs(
    boundary: PathBoundary,
) -> None:
    violation = boundary.check("Grep", {"pattern": "x", "glob": "../*.yaml"})
    assert violation is not None
    boundary.record(violation)

    assert boundary.records() == [
        {
            "tool": "Grep",
            "field": "glob",
            "value": "../*.yaml",
            "reason": violation.reason,
        }
    ]


# --- leak channels the per-call boundary cannot see --------------------------


def test_a_clean_fixture_has_no_history_or_symlinks(fixture: Fixture) -> None:
    assert git_artifacts(fixture.repo) == []
    assert symlinks(fixture.repo) == []
    assert_isolated(fixture.repo)  # must not raise


@pytest.mark.parametrize("name", sorted(GIT_ARTIFACT_NAMES))
def test_surviving_history_is_detected(fixture: Fixture, name: str) -> None:
    (fixture.repo / name).mkdir()

    assert git_artifacts(fixture.repo) == [fixture.repo / name]
    with pytest.raises(FixtureNotIsolated, match="version-control history"):
        assert_isolated(fixture.repo)


def test_nested_history_is_detected(fixture: Fixture) -> None:
    (fixture.repo / "src" / "vendor").mkdir()
    (fixture.repo / "src" / "vendor" / ".git").mkdir()

    assert git_artifacts(fixture.repo) == [fixture.repo / "src" / "vendor" / ".git"]


def test_symlinks_are_refused_before_a_run(fixture: Fixture) -> None:
    # Glob and Grep expand across these themselves, so the per-call boundary
    # never sees the escape. The fixture is required to contain none.
    (fixture.repo / "up").symlink_to(fixture.root, target_is_directory=True)

    assert symlinks(fixture.repo) == [fixture.repo / "up"]
    with pytest.raises(FixtureNotIsolated, match="symlinks"):
        assert_isolated(fixture.repo)


def test_missing_repo_is_refused(fixture: Fixture) -> None:
    with pytest.raises(FixtureNotIsolated, match="does not exist"):
        assert_isolated(fixture.root / "nope")


# --- the SDK adapter ---------------------------------------------------------


def pre_tool_use(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s-1",
        "transcript_path": "/dev/null",
        "cwd": ".",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "toolu_1",
    }


def decision(output: dict[str, Any]) -> str | None:
    specific = output.get("hookSpecificOutput")
    return None if specific is None else specific.get("permissionDecision")


async def test_hook_denies_and_records_an_escape(boundary: PathBoundary) -> None:
    hook = boundary_hook(boundary)

    output = await hook(pre_tool_use("Read", {"file_path": "../fixture.yaml"}), None, {})  # type: ignore[arg-type]

    assert decision(output) == "deny"  # type: ignore[arg-type]
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


# The fail-closed cases below are the QA review's blocker: the SDK reduces an
# exception out of a hook to an unlogged protocol error, and what the CLI does
# next under `bypassPermissions` is undocumented. The boundary must not depend
# on that answer.


@pytest.mark.parametrize(
    "event",
    [
        None,  # the SDK calls the hook with request_data.get("input") — can be None
        "not-a-mapping",
        {"hook_event_name": "PreToolUse"},  # no tool_name at all
        {"hook_event_name": "PreToolUse", "tool_name": 42, "tool_input": {}},
    ],
)
async def test_hook_fails_closed_on_malformed_input(
    boundary: PathBoundary, event: Any
) -> None:
    hook = boundary_hook(boundary)

    output = await hook(event, None, {})  # type: ignore[arg-type]

    assert decision(output) == "deny"  # type: ignore[arg-type]
    assert boundary.violations, "a boundary that broke must not look like one that held"
    assert "failed internally" in boundary.violations[0].reason


async def test_hook_fails_closed_when_the_check_itself_raises(
    boundary: PathBoundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: Any, **kwargs: Any) -> BoundaryViolation | None:
        raise ValueError("unanticipated input shape")

    monkeypatch.setattr(boundary, "check", explode)
    hook = boundary_hook(boundary)

    output = await hook(pre_tool_use("Read", {"file_path": "package.json"}), None, {})  # type: ignore[arg-type]

    assert decision(output) == "deny"  # type: ignore[arg-type]
    assert "unanticipated input shape" in boundary.violations[0].reason


def test_confinement_hooks_matches_every_tool(fixture: Fixture) -> None:
    _, matchers = confinement_hooks(fixture.repo)

    (matcher,) = matchers["PreToolUse"]
    assert matcher.matcher is None, "a per-tool matcher would let unknown tools through"


def test_confinement_hooks_refuses_a_leaky_fixture(fixture: Fixture) -> None:
    (fixture.repo / ".git").mkdir()

    # Before the run, not after: a run against a leaky fixture produces numbers
    # indistinguishable from good ones.
    with pytest.raises(FixtureNotIsolated):
        confinement_hooks(fixture.repo)
