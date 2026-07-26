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

**The hook fails closed on its own bugs.** Everything in the callback body is
wrapped, and any internal error denies the call. This is not defensive habit —
the SDK's `_handle_control_request` catches an exception out of a hook with a
bare `except Exception`, replies to the CLI with `{"subtype": "error", ...}`,
and logs nothing on the Python side. What the CLI then does under
`bypassPermissions` is undocumented, and "probably denies" is not a control.
Note also that the SDK invokes the callback as
``callback(request_data.get("input"), ...)`` — the input can legitimately be
``None``, so subscripting it unguarded is a live crash path, not a hypothetical.

**The check stays synchronous.** `Path.resolve()` is blocking I/O on the event
loop, which is normally worth offloading. Not here: it is a few syscalls
against a local, symlink-free fixture of a few dozen files, and dispatching to
a thread costs more than the resolution it would avoid. The pathological cases
that would justify an offload — deep symlink chains, network mounts — are
precisely what `assert_isolated` refuses at startup.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    HookCallback,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
)

from assay.executor.confinement import BoundaryViolation, PathBoundary, assert_isolated

logger = logging.getLogger(__name__)


def _deny(reason: str) -> HookJSONOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def boundary_hook(boundary: PathBoundary) -> HookCallback:
    """Builds the `PreToolUse` callback that enforces `boundary`."""

    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        tool_name = "<unknown>"
        try:
            if not isinstance(input_data, dict):
                raise TypeError(f"hook input was {type(input_data).__name__}, not a mapping")
            if input_data.get("hook_event_name") != "PreToolUse":
                return {}

            raw_name = input_data.get("tool_name")
            if not isinstance(raw_name, str):
                raise TypeError(f"tool_name was {type(raw_name).__name__}, not a string")
            tool_name = raw_name

            # Typed `Any` on purpose: this arrives off the wire, so the static
            # type is a claim about the SDK's schema, not about what a CLI on
            # the far side actually sent. `check` re-validates the shape.
            tool_input: Any = input_data.get("tool_input", {})
            violation = boundary.check(tool_name, tool_input)
        except Exception as error:  # noqa: BLE001 — deliberately broad; see docstring
            # Denying is the safe direction, but a boundary that broke must not
            # look like a boundary that held: record it so the run's transcript
            # shows the failure instead of a clean sheet.
            logger.exception("path boundary failed internally; denying the call")
            violation = BoundaryViolation(
                tool=tool_name,
                field=None,
                value=None,
                reason=(
                    "boundary check failed internally "
                    f"({error.__class__.__name__}: {error})"
                ),
            )
            boundary.record(violation)
            return _deny(f"Refused because the fixture boundary errored — {violation.reason}")

        if violation is None:
            # Silence, not "allow": approving here would override deny rules
            # configured elsewhere in the executor.
            return {}

        boundary.record(violation)
        return _deny(
            f"Refused by the fixture boundary — {violation.message}. "
            "The review is confined to this repository; there is nothing "
            "above it you are meant to see."
        )

    return hook


def confinement_hooks(repo: Path) -> tuple[PathBoundary, dict[str, list[HookMatcher]]]:
    """Returns the boundary and the `hooks=` mapping to hand `ClaudeAgentOptions`.

    Raises `FixtureNotIsolated` if `repo` carries version-control history or
    symlinks — the two leak channels the per-call boundary cannot see. Checked
    here, before the run, because a leaky fixture yields numbers indistinguishable
    from good ones.

    `matcher=None` matches every tool, which is what default-deny requires: a
    per-tool matcher would let an unlisted tool through without ever consulting
    the boundary.
    """
    assert_isolated(repo)
    boundary = PathBoundary(repo)
    matchers = {"PreToolUse": [HookMatcher(matcher=None, hooks=[boundary_hook(boundary)])]}
    return boundary, matchers
