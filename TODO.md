# TODO

- [ ] Transcript noise that the mod cannot remove:
  - a queued shake shows the `/compact shake …` row and the engine's
    `Compacted (ctrl+o to see full summary)` line. `$.session.compact()` would
    avoid both, but called under a hook's work (a command, a turn) the engine
    skips the plugin's own `session.compact` hook and its `.catch`, and core
    then writes a native summary (live test 2026-10-12). Retry if the engine
    asks the `.catch` on re-entry.
  - the `PostCompact` line with the long shell command comes from Orca's
    `~/.orca/agent-hooks/claude-hook.sh`, which prints `{}`; every compaction
    shows it. A fix belongs in Orca (print `{"suppressOutput": true}`;
    unverified).
- [ ] Check whether `return {}` from `/shake` shows an empty output row.
- [ ] Skip the startup repair check when the session has no `shake/` dir
  (review 3, P3: about 15 ms of subprocess time on the first prompt of every
  session).
- [ ] Check whether to set `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`: its
  default and effect are untested. A Read cap limits new large reads, which
  the shake frees only later.
- [ ] Explain why a resumed session is 10-15k tokens larger than the live one
  after a shake (attachment rows? thinking counted after load?).
- [ ] Check that the 3 s repair timeout is enough on a slow disk; the live tests
  anchored, but the wait was not recorded.
- [ ] Test `/rewind` and fork from a row before a shake boundary.
- [ ] Check storage v5 (`replaceRecords`) sessions; the repair assumes the plain
  JSONL file.
- [ ] Headless (`-p`) sessions: check that the auto trigger's queued
  `/compact shake auto` runs there.
- [ ] Re-check the loader facts (`g1r`, `S1r`, `nOn`, `zKr`) after each Claude
  Code update; the mod depends on an undocumented file format.
- [ ] Upstream request: expose `content-replacement` (flag
  `tengu_hawthorn_steeple`) to mods as an op, and a history reload op.
- [ ] Optional: the idle file shake + mod-queued `/resume <same id>` route
  (ADR-0003) as a fallback that keeps attachment rows.

Decisions: [ADR-0003](../agents/docs/decisions/0003-shake-session-file-at-idle.md)
in the `agents` repo (see README "Decisions"). Frozen research and review copies
from 2026-10-07/08 are in `docs/research/`.
