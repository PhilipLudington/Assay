# Project Bugs

Defects found by review that do not block the current milestone live here with a
`**Deferred:**` line saying why; the ones that do block it are lines in `PLAN.md`
`## Next Up` (which carries no `**Blocks when:**` sentence yet — until it does, "on the
published results table" is the test). Routing rule:
`~/.claude/rules/plan-format.md` § Next Up.

## [ ] Bug 1: The transcript and label files `main` reads get no syntax or shape check, so a malformed one escapes the `LocalityError` contract

**Status:** Open

**Deferred:** after the v1 results table — the escaping error names the real problem
(`JSONDecodeError` says where the JSON breaks; `AttributeError: 'list' object has no
attribute 'get'` says the file is a list), no published number moves, and nothing in
this repo writes such a file. It shares its fix site with the `PLAN.md` Next Up line
"A non-dict record in `runs` escapes the error contract too": one shape check at
`classify`'s entry covers the transcript itself, and one `try` around each
`json.loads` in `main` covers the syntax.

**Description:** `assay.corpus.locality.main` reads `--from` and `--labels` with a bare
`json.loads` (`locality.py:1380`, `:1369`), and `classify` calls `transcript.get(...)`
on whatever it was handed (`:993`; `main` reaches `transcript.get("fixture")` at
`:1384` first). This branch added the object check for `--labels` (`load_labels`) and
walked past the identical hole for `--from`, and past the syntax hole for both. Every
other malformed input in this module — a repeated or non-integer `run_index`, a
non-object label file, a non-boolean label value — is refused as `LocalityError`; these
two are the last raw-exception paths on the CLI's own inputs.

**Steps to reproduce:**
1. `printf '{' > bad.json` and run
   `.venv/bin/python -m assay.corpus.locality corpus/ts/TS-0001-reservation-double-release --from results/locality/TS-0001-20260731T170244Z.json --labels bad.json`
2. `echo '["not","a","transcript"]' > list.json` and run
   `.venv/bin/python -m assay.corpus.locality corpus/ts/TS-0001-reservation-double-release --from list.json`

**Expected:** `LocalityError` naming the file and what is wrong with it, the way
`load_labels` does for a non-object label file.

**Actual:** Step 1 raises `json.decoder.JSONDecodeError: Expecting property name
enclosed in double quotes: line 1 column 2 (char 1)`; step 2 raises `AttributeError:
'list' object has no attribute 'get'`. Both reproduce identically on `main`
(verified 2026-09-14).

**Found by:** /qa-review on `reject-non-boolean-label-values`, 2026-09-14 — Test
Coverage (the syntax half) and Generalist (the shape half); verified by probe and by
reading `locality.py:993`, `:1369`, `:1380`, `:1384`.

---
