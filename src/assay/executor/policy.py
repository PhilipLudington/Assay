"""The reviewer's tool policy — one definition, because two of them drifted.

These lists say which tools a confined reviewer may call and which are refused
outright. They live here, in production code, rather than in whichever script
happens to launch a run, for a reason the project has already paid for twice:

- The first boundary probe ran without an `output_format`, so the reviewer
  reached for `ReportFindings` instead of `StructuredOutput` and the run
  exercised a tool the real reviewer would never use.
- The second copy of this list, in `assay.executor.probe`, omitted `TodoWrite`
  while `pilot/run_agentic.py` denied it. The probe's whole evidentiary claim is
  that it runs *the reviewer's exact configuration*; a probe running a different
  tool policy proves the boundary holds in a world we do not run in.

Both failures share a shape: the configuration under test was not the
configuration in use, and nothing made that visible. A single importable
definition removes the failure mode rather than documenting it.

This module deliberately imports no Agent SDK. `assay.executor.__init__`
re-exports it, and nothing that only needs to know the tool policy should have
to pay for the SDK import to find it out.

Fields beyond these two that must stay identical between probe and reviewer —
`permission_mode="bypassPermissions"` and `setting_sources=[]` — are set at each
call site with the comment explaining why. They have not drifted, and hoisting
them here would mean re-exporting SDK-typed literals from an SDK-free module.
"""

from __future__ import annotations

#: The reviewer navigates the repository and does nothing else. Everything here
#: is read-only by construction; the path boundary constrains *where* each one
#: may read (see `assay.executor.confinement.PATH_FIELDS`).
READ_ONLY_TOOLS = ["Read", "Glob", "Grep"]

#: Denied outright, independent of any path they might carry. `Bash` and `Task`
#: matter most: both can reach the filesystem through a channel the per-call
#: path check cannot inspect, so neither is constrainable by field inspection
#: the way `Read` is. Note this list is belt-and-braces — `PathBoundary` already
#: default-denies any tool it does not recognise — but stating it to the SDK
#: keeps the tool out of the model's menu rather than refusing it after it asks.
DENIED_TOOLS = [
    "Bash",
    "Write",
    "Edit",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
]
