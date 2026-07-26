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
because those paths happened not to exist. That is the absence of a control,
not evidence of one.

Two design choices are worth stating, because both look like over-engineering
until you know why:

**Default-deny on the tool name.** A tool this module does not know about is
refused rather than passed through. The alternative — allow unknown tools and
check the ones we recognise — means the next tool added to the reviewer's
toolset silently bypasses the boundary. A refusal is a loud, cheap failure; a
bypass is a silent, expensive one.

**Resolution before comparison.** Every candidate path is resolved (symlinks
followed, `..` collapsed) and then compared against the resolved root. String
prefix matching would pass `repo/../fixture.yaml` and any symlink pointing out
of the tree.

What this module does *not* cover: a `Glob` pattern that stays inside `repo/`
but expands across a symlink pointing out of it. The declared path is checked,
not the expansion. The control for that is the fixture-authoring standard —
fixtures ship no symlinks — and `git_artifacts` below is the same kind of
layout assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Path-bearing fields per tool. The reviewer's toolset is exactly these three
#: (DESIGN: `Read`/`Glob`/`Grep` only); anything else is denied outright.
#:
#: `Grep.pattern` is deliberately absent — it is a regular expression, not a
#: path, and checking it would reject ordinary patterns like `\.\./`. `Glob`'s
#: `pattern` *is* checked, because `Glob("../*.yaml")` is a real escape route.
PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "Read": ("file_path",),
    "Glob": ("pattern", "path"),
    "Grep": ("path", "glob"),
}


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


class PathBoundary:
    """Decides whether a tool call stays inside the fixture's `repo/`.

    Pure and synchronous by design — no SDK types, no I/O beyond path
    resolution — so the isolation test can exercise every escape route without
    a model call. The Agent SDK adapter lives in `assay.executor.hooks`.
    """

    def __init__(self, root: Path) -> None:
        # strict=False: the root must exist in practice, but resolving
        # non-strictly keeps this constructible in tests against a path that
        # is about to be created.
        self.root = root.resolve()
        self.violations: list[BoundaryViolation] = []

    def check(self, tool_name: str, tool_input: dict[str, Any]) -> BoundaryViolation | None:
        """Returns the violation this call would commit, or None if it is safe."""
        fields = PATH_FIELDS.get(tool_name)
        if fields is None:
            return BoundaryViolation(
                tool=tool_name,
                field=None,
                value=None,
                reason=(
                    "tool is not on the read-only allowlist "
                    f"({', '.join(sorted(PATH_FIELDS))})"
                ),
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
        self.violations.append(violation)

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
#: History is a leak channel of its own: `git log` on a fixture built by
#: reverting a defect hands the reviewer the answer in a commit message.
GIT_ARTIFACT_NAMES = frozenset(
    {".git", ".gitmodules", ".hg", ".svn", ".jj", ".bzr"}
)


def git_artifacts(root: Path) -> list[Path]:
    """Returns any version-control artifacts found under `root`.

    A non-empty result means the fixture was not stripped and its defect may be
    recoverable from history without ever crossing the path boundary.
    """
    found = [
        path
        for path in root.rglob("*")
        if path.name in GIT_ARTIFACT_NAMES
    ]
    return sorted(found)


@dataclass
class FixtureLayout:
    """Where a fixture's answer key sits relative to the reviewer's cwd.

    Exists so the isolation test asserts against one description of the layout
    rather than re-deriving it, and so a future layout change breaks the test
    instead of quietly widening the boundary.
    """

    root: Path
    repo_dirname: str = "repo"
    answer_key_names: tuple[str, ...] = ("fixture.yaml", "ANSWER.md")
    #: Files that live at the fixture root and are legitimately outside `repo/`.
    sibling_names: tuple[str, ...] = field(default=("change.patch", "NOTES.md"))

    @property
    def repo(self) -> Path:
        return self.root / self.repo_dirname

    def answer_keys(self) -> list[Path]:
        return [self.root / name for name in self.answer_key_names]
