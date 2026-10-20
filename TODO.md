# TODO

- [ ] Test a prompt typed while the queued `/resume` runs: does the redraw keep
  the text in the prompt box?
- [ ] Test the reload with Monitor tasks, cron jobs and Orca peer messages
  (background shells and subagents are measured to survive it).
- [ ] The classic `SessionStart` hooks add their context again on each reload
  (for example ponytail). Measure what that costs per shake.
- [ ] Explain why the threshold shake freed 31k tokens where the mod estimated
  15.5k (the test outputs were repeated letters).
- [ ] Test `/rewind` and fork from a row before a shake.
- [ ] Check storage v5 (`replaceRecords`) sessions; the rewrite assumes the
  plain JSONL file.
- [ ] Headless (`-p`) sessions shake the file but cannot reload; check that the
  next `--resume` (an Orca worker restart) loads the shaken file.
- [ ] Check whether to set `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`: its
  default and effect are untested. Claude Code 2.1.304 already saves large
  new results as `<persisted-output>`.
- [ ] Re-check the file format after each Claude Code update; the mod depends on
  an undocumented format.
- [ ] Upstream request: expose `content-replacement` (flag
  `tengu_hawthorn_steeple`) to mods as an op, and a history reload op.
- [ ] Update ADR-0003 in the `agents` repo: the file route replaced the compact
  route on 2026-10-20 (the guard skips `session.compact` on a Team login).

Decisions: [ADR-0003](../agents/docs/decisions/0003-shake-session-file-at-idle.md)
in the `agents` repo (see README "Decisions"). Frozen research and review copies
from 2026-10-07/08 are in `docs/research/`.
