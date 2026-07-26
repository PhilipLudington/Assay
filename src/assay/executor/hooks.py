"""Agent SDK adapter for the path boundary.

The mechanism here is a **`PreToolUse` hook**, not the `can_use_tool`
permission callback, and the choice is forced rather than stylistic. The Agent
SDK auto-approves a tool call before `can_use_tool` runs when either
`permission_mode="bypassPermissions"` is set or `allowed_tools` grants a whole
tool — both of which the reviewer configuration does. The SDK says so itself,
and names the remedy::

    can_use_tool will not be invoked: permission_mode 'bypassPermissions'
    auto-approves every tool call (except explicit deny rules) before the
    callback is consulted. To gate every tool call, use a PreToolUse hook
    instead.

    -- claude_agent_sdk.types._get_can_use_tool_shadowed_warning

So a boundary built on `can_use_tool` would be a control that never fires,
which is worse than no control: it would look enforced in code review.

The hook returns an explicit `deny` only for violations and stays silent
otherwise. Silence is deliberate — approving is the permission mode's job, and
a hook that returned `allow` would override deny rules configured elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
)

from assay.executor.confinement import PathBoundary


def boundary_hook(
    boundary: PathBoundary,
) -> Any:
    """Builds the `PreToolUse` callback that enforces `boundary`.

    Typed loosely on return because the SDK's `HookCallback` alias is a bare
    `Callable` type; the signature below is the contract that matters.
    """

    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}

        violation = boundary.check(input_data["tool_name"], input_data["tool_input"])
        if violation is None:
            return {}

        boundary.record(violation)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Refused by the fixture boundary — {violation.message}. "
                    "The review is confined to this repository; there is "
                    "nothing above it you are meant to see."
                ),
            }
        }

    return hook


def confinement_hooks(repo: Path) -> tuple[PathBoundary, dict[str, list[HookMatcher]]]:
    """Returns the boundary and the `hooks=` mapping to hand `ClaudeAgentOptions`.

    `matcher=None` matches every tool, which is what default-deny requires: a
    per-tool matcher would let an unlisted tool through without ever consulting
    the boundary.
    """
    boundary = PathBoundary(repo)
    matchers = {"PreToolUse": [HookMatcher(matcher=None, hooks=[boundary_hook(boundary)])]}
    return boundary, matchers
