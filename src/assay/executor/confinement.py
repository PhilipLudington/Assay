"""The answer-key boundary: reviewers see `repo/`, and nothing above it.

This is the project's highest-severity failure mode. A reviewer that reads
`fixture.yaml` scores perfectly and *nothing about the output looks wrong* —
the run completes, the transcript is well-formed, and every published number is
silently invalid. DESIGN records the decision plainly: isolation is enforced by
the executor and asserted by a test, because convention is not a control.

The 2026-07-26 QA review found the pilot harness enforcing nothing beyond
`cwd`, under `permission_mode="bypassPermissions"`. An audit of all 34 pilot
transcripts found no escape, so no recorded number is contaminated — but 22
calls did attempt absolute paths outside the working directory and failed only
because those paths did not exist. That is the absence of a control, not
evidence of one.

Three design choices are worth stating, because each looks like
over-engineering until you know why:

**Default-deny on the tool name.** A tool this module does not know about is
refused rather than passed through. The alternative — allow unknown tools and
check the ones we recognise — means the next tool added to the reviewer's
toolset silently bypasses the boundary. A refusal is a loud, cheap failure; a
bypass is a silent, expensive one.

The one exception is `CONTROL_PLANE_TOOLS`, and it was bought with a real
failure: the 2026-07-30 live probe found `StructuredOutput` — the channel the
CLI uses to deliver a `--json-schema` result — being denied by this very rule.
Every agentic run returned zero findings and a parse error. Default-deny was
right and the allowlist was simply incomplete; see the constant below.

**Resolution before comparison.** Every candidate path is resolved (symlinks
followed, `..` collapsed) and then compared against the resolved root. String
prefix matching would pass `repo/../fixture.yaml` and any symlink pointing out
of the tree.

**Preconditions are checked, not assumed.** `check()` guards the paths a
reviewer *declares*. It cannot guard what `Glob` and `Grep` do when they expand
a pattern themselves: a pattern rooted inside `repo/` can still match across a
symlink pointing out of it. That hole used to be closed by the sentence
"fixtures ship no symlinks" in a README, which is a convention, not a control.
`assert_isolated()` now enforces it — along with the absence of version-control
history, which is a leak channel of its own, since `git log` on a fixture built
by reverting a defect hands over the answer in a commit message.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Path-bearing fields per tool. The reviewer's toolset is exactly these three
#: (DESIGN: `Read`/`Glob`/`Grep` only); anything else is denied outright.
#:
#: `Grep.pattern` is deliberately absent — it is a regular expression, not a
#: path, and checking it would reject ordinary searches for `\.\./`. `Glob`'s
#: `pattern` *is* checked, because `Glob("../*.yaml")` is a real escape route,
#: as is `Grep`'s `glob` filter.
PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "Read": ("file_path",),
    "Glob": ("pattern", "path"),
    "Grep": ("path", "glob"),
}

#: Tools that belong to the harness's own control plane rather than to the
#: reviewer's navigation, and are therefore allowed without a path check.
#:
#: `StructuredOutput` is the reviewer's *answer channel*: setting
#: `output_format={"type": "json_schema", ...}` makes the SDK pass
#: `--json-schema` to the CLI, which collects the result through a tool call of
#: this name. Denying it does not confine the reviewer — it gags it. The
#: 2026-07-30 boundary probe caught exactly that: two denied `StructuredOutput`
#: calls, zero findings, and a `parse_error` on every agentic run.
#:
#: Allowing it opens no read channel. The direction of travel is model → harness,
#: and the payload is a claim the reviewer is making, not a file it is opening.
#: Its inputs are deliberately **not** path-checked, and that is not laxity: a
#: finding legitimately carries a repo-relative `file`, so scanning this tool for
#: path-shaped fields would reject correct output for looking like an escape.
#:
#: The list is a name allowlist and stays short. A tool earns a place here only
#: when it cannot read anything — which is a claim to re-check whenever the CLI
#: changes, since the behaviour belongs to a dependency.
CONTROL_PLANE_TOOLS = frozenset({"StructuredOutput"})

#: Cap on violations retained per run. A reviewer that loops on a denied path
#: must not be able to inflate one transcript record without limit; the count
#: of what was dropped is kept, because "we stopped recording" and "it stopped
#: happening" have to stay distinguishable.
MAX_RECORDED_VIOLATIONS = 100

#: Cap on the attempted-path string persisted per violation.
MAX_RECORDED_VALUE_CHARS = 512


class FixtureNotIsolated(RuntimeError):
    """A fixture cannot be reviewed safely. Never downgraded to a warning."""


@dataclass(frozen=True)
class BoundaryViolation:
    """A tool call that would have left `repo/`, and why it was refused.

    Recorded rather than merely blocked: the risk register requires auditing
    what reviewers *attempted*, not just what they achieved. An attempt is
    evidence about the fixture (something in it points at the answer key) even
    when the boundary holds.
    """

    tool: str
    field: str | None
    value: Any
    reason: str

    @property
    def message(self) -> str:
        where = f"{self.tool}.{self.field}" if self.field else self.tool
        return f"{where}: {self.reason}"

    def as_record(self) -> dict[str, Any]:
        """The transcript form. Bounded, so one run cannot bloat one record."""
        value = self.value
        if isinstance(value, str) and len(value) > MAX_RECORDED_VALUE_CHARS:
            value = value[:MAX_RECORDED_VALUE_CHARS] + "…[truncated]"
        return {
            "tool": self.tool,
            "field": self.field,
            "value": value,
            "reason": self.reason,
        }


class PathBoundary:
    """Decides whether a tool call stays inside the fixture's `repo/`.

    Pure and synchronous by design — no SDK types, no I/O beyond path
    resolution — so the isolation test can exercise every escape route without
    a model call. The Agent SDK adapter lives in `assay.executor.hooks`.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.violations: list[BoundaryViolation] = []
        #: Violations that occurred past `MAX_RECORDED_VIOLATIONS`.
        self.suppressed_violations = 0

    def check(self, tool_name: str, tool_input: dict[str, Any]) -> BoundaryViolation | None:
        """Returns the violation this call would commit, or None if it is safe.

        Total: every input shape reaches a decision. The caller treats an
        exception out of here as a denial anyway (see `assay.executor.hooks`),
        but it should not have to.
        """
        if tool_name in CONTROL_PLANE_TOOLS:
            return None

        fields = PATH_FIELDS.get(tool_name)
        if fields is None:
            return BoundaryViolation(
                tool=tool_name,
                field=None,
                value=None,
                reason=(
                    "tool is not on the read-only allowlist "
                    f"({', '.join(sorted(PATH_FIELDS))}) nor a control-plane tool "
                    f"({', '.join(sorted(CONTROL_PLANE_TOOLS))})"
                ),
            )

        if not isinstance(tool_input, dict):
            return BoundaryViolation(
                tool=tool_name,
                field=None,
                value=tool_input,
                reason=f"expected a tool input mapping, got {type(tool_input).__name__}",
            )

        for name in fields:
            if name not in tool_input:
                continue
            value = tool_input[name]
            if value is None:
                continue
            if not isinstance(value, str):
                return BoundaryViolation(
                    tool=tool_name,
                    field=name,
                    value=value,
                    reason=f"expected a string path, got {type(value).__name__}",
                )
            reason = self._reject(value)
            if reason is not None:
                return BoundaryViolation(
                    tool=tool_name, field=name, value=value, reason=reason
                )
        return None

    def record(self, violation: BoundaryViolation) -> None:
        if len(self.violations) >= MAX_RECORDED_VIOLATIONS:
            self.suppressed_violations += 1
            return
        self.violations.append(violation)

    def records(self) -> list[dict[str, Any]]:
        """Violations in transcript form, for persistence."""
        return [violation.as_record() for violation in self.violations]

    def _reject(self, value: str) -> str | None:
        """Returns why `value` is out of bounds, or None if it is inside `root`."""
        # `~` is refused rather than resolved: whether the tool expands it is
        # the CLI's business, and a boundary that depends on someone else's
        # expansion rules is not a boundary.
        if value.startswith("~"):
            return "home-directory expansion is not permitted inside a fixture"

        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.root / candidate

        try:
            resolved = candidate.resolve()
        except (OSError, ValueError, RuntimeError) as error:
            # RuntimeError covers symlink loops on some platforms; ValueError
            # covers embedded NUL bytes. An unresolvable path is refused —
            # "we could not tell" is not "it is fine".
            return f"path could not be resolved ({error.__class__.__name__})"

        if resolved != self.root and not resolved.is_relative_to(self.root):
            return f"resolves to {resolved}, outside the fixture repo at {self.root}"
        return None


#: Names that indicate version-control history survived into a fixture repo.
GIT_ARTIFACT_NAMES = frozenset({".git", ".gitmodules", ".hg", ".svn", ".jj", ".bzr"})


def git_artifacts(root: Path) -> list[Path]:
    """Returns any version-control artifacts found under `root`.

    A non-empty result means the fixture was not stripped and its defect may be
    recoverable from history without ever crossing the path boundary.
    """
    return sorted(path for path in root.rglob("*") if path.name in GIT_ARTIFACT_NAMES)


def symlinks(root: Path) -> list[Path]:
    """Returns any symlinks under `root`.

    These are the hole `check()` cannot close. A `Glob` or `Grep` pattern that
    is entirely inside `repo/` is approved on its declared path, and the tool
    then expands it itself — across any symlink it finds. Rather than trying to
    predict expansions, the fixture is required to contain no symlinks at all.
    """
    return sorted(path for path in root.rglob("*") if path.is_symlink())


def assert_isolated(repo: Path) -> None:
    """Raises unless `repo` is safe to hand to a reviewer.

    Called before a run starts rather than after it finishes: a run against a
    leaky fixture produces numbers that cannot be distinguished from good ones,
    so the only useful time to find out is before any tokens are spent.
    """
    if not repo.is_dir():
        raise FixtureNotIsolated(f"fixture repo does not exist: {repo}")

    problems: list[str] = []
    if found := git_artifacts(repo):
        problems.append(
            "version-control history survived into the fixture "
            f"({', '.join(str(p.relative_to(repo)) for p in found)}) — the defect "
            "may be recoverable from commit messages"
        )
    if found := symlinks(repo):
        problems.append(
            "fixture contains symlinks "
            f"({', '.join(str(p.relative_to(repo)) for p in found)}) — Glob and "
            "Grep expand patterns across these, which the path boundary cannot see"
        )
    if problems:
        raise FixtureNotIsolated(f"{repo} is not safe to review: " + "; ".join(problems))
