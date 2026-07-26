"""Shared pilot plumbing. Throwaway — deleted at the end of Phase 1.

Nothing here is a preview of the real corpus loader. It exists so the three
measurement scripts agree on what a fixture is, what the review-context floor
is, and how a dollar is computed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PILOT_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = PILOT_DIR / "fixtures"
OUT_DIR = PILOT_DIR / "out"
FIXTURE_NAMES = ("small", "medium", "large")

DEFAULT_MODEL = "claude-opus-5"

# USD per million tokens, (input, output). Cache writes bill at 1.25x input,
# cache reads at 0.1x input.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def price_for(model: str) -> tuple[float, float]:
    for known, prices in PRICING.items():
        if model.startswith(known):
            return prices
    raise KeyError(
        f"no price on file for {model!r}; add it to PRICING rather than "
        "guessing, or the cost numbers in FINDINGS.md are fiction"
    )


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Dollar cost of one call. Batch API discount is *not* applied."""
    per_in, per_out = price_for(model)
    return (
        input_tokens * per_in
        + cache_creation_tokens * per_in * 1.25
        + cache_read_tokens * per_in * 0.10
        + output_tokens * per_out
    ) / 1_000_000


class FixtureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Fixture:
    name: str
    root: Path

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def patch_path(self) -> Path:
        return self.root / "change.patch"

    @property
    def answer_path(self) -> Path:
        return self.root / "ANSWER.md"

    def source_files(self) -> list[Path]:
        return sorted(p for p in self.repo.rglob("*.ts") if p.is_file())

    def diff(self) -> str:
        return self.patch_path.read_text(encoding="utf-8")

    def touched_files(self) -> list[str]:
        """Repo-relative paths the diff modifies, in diff order."""
        seen: list[str] = []
        for line in self.diff().splitlines():
            match = re.match(r"^\+\+\+ b/(.+)$", line)
            if match and match.group(1) not in seen:
                seen.append(match.group(1))
        return seen

    def floor(self) -> str:
        """The review-context floor from DESIGN: the diff, plus the full
        contents of every file the diff touches. Identical across modes."""
        parts = [
            "The change under review:",
            "",
            "```diff",
            self.diff().rstrip(),
            "```",
            "",
            "Full current contents of every file the change touches:",
            "",
        ]
        for relative in self.touched_files():
            path = self.repo / relative
            if not path.exists():
                raise FixtureError(f"{self.name}: diff touches missing file {relative}")
            parts += [
                f"--- {relative} ---",
                "```typescript",
                path.read_text(encoding="utf-8").rstrip(),
                "```",
                "",
            ]
        return "\n".join(parts)

    def validate(self) -> None:
        """Fails loudly rather than quietly producing meaningless numbers."""
        if not self.repo.is_dir():
            raise FixtureError(f"{self.name}: no repo/ directory")
        if not self.answer_path.is_file():
            raise FixtureError(f"{self.name}: no ANSWER.md")

        # The answer key must be unreachable from the reviewer's cwd.
        if self.answer_path.resolve().is_relative_to(self.repo.resolve()):
            raise FixtureError(f"{self.name}: ANSWER.md is inside repo/")
        stray = [p for p in self.repo.rglob("ANSWER.md")]
        if stray:
            raise FixtureError(f"{self.name}: answer key copies inside repo/: {stray}")
        if (self.repo / ".git").exists():
            raise FixtureError(f"{self.name}: repo/ carries git history")

        # The diff must actually describe this tree. A patch that has drifted
        # from repo/ silently changes what the reviewer is asked to review.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(self.repo, Path(tmp) / "repo")
            result = subprocess.run(
                ["git", "apply", "--reverse", "--check", str(self.patch_path)],
                cwd=Path(tmp) / "repo",
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise FixtureError(
                    f"{self.name}: change.patch does not reverse against repo/ "
                    f"({result.stderr.strip()})"
                )


def load_fixture(name: str) -> Fixture:
    if name not in FIXTURE_NAMES:
        raise FixtureError(f"unknown fixture {name!r}; expected one of {FIXTURE_NAMES}")
    fixture = Fixture(name=name, root=FIXTURES_DIR / name)
    fixture.validate()
    return fixture


def all_fixtures() -> list[Fixture]:
    return [load_fixture(name) for name in FIXTURE_NAMES]


# --- reviewer prompts -------------------------------------------------------
#
# Two specializations, so the caching question can be asked across reviewers
# on one fixture and not just across repeats of one reviewer.

_SHARED_RULES = """\
Report only defects you can point at in the code. For each one give the file, \
the line range, a short class name, a severity, your confidence from 0 to 1, \
and an explanation of what goes wrong and under what conditions.

Do not report style, naming, formatting, or test-coverage opinions. Do not \
report anything you cannot tie to a specific location. If you find nothing, \
return an empty list — an empty list is a valid and sometimes correct answer.\
"""

REVIEWERS: dict[str, str] = {
    "correctness": (
        "You are reviewing a code change for correctness defects: logic errors, "
        "incorrect edge-case handling, broken invariants, race conditions, and "
        "data-integrity problems.\n\n" + _SHARED_RULES
    ),
    "security": (
        "You are reviewing a code change for security defects: missing or "
        "incorrect authorization, injection, unsafe handling of untrusted "
        "input, secret exposure, and unsafe defaults.\n\n" + _SHARED_RULES
    ),
}

FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Repo-relative path, e.g. src/worker/pool.ts",
                    },
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "claimed_class": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "confidence": {"type": "number"},
                    "message": {"type": "string"},
                },
                "required": [
                    "file",
                    "start_line",
                    "end_line",
                    "claimed_class",
                    "severity",
                    "confidence",
                    "message",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def review_task(fixture: Fixture) -> str:
    return (
        f"Review the change below. The repository is a TypeScript project "
        f"({len(fixture.source_files())} source files).\n\n" + fixture.floor()
    )


# --- transcript io ----------------------------------------------------------


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def transcript_path(mode: str, fixture: str, reviewer: str, stamp: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / f"{mode}-{fixture}-{reviewer}-{stamp}.jsonl"


def append_record(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_records(pattern: str = "*.jsonl") -> Iterator[dict[str, Any]]:
    if not OUT_DIR.is_dir():
        return
    for path in sorted(OUT_DIR.glob(pattern)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)
