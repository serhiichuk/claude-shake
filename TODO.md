# TODO

- [ ] Test the automatic shake (`turn.complete`, usage >= 60%) once on a
  session copy. Only the manual `/compact shake` has run live. The user-scope
  install turns it on in every session; until it passes, lower
  `thresholdPercent` only on a copy, or disable the plugin for work sessions if
  they approach 60%.
- [ ] `/shake` command: register `/shake`, return at once, and queue
  `$.command.run({ command: 'compact', args: 'shake' })` after the hook returns
  (e.g. `setTimeout(..., 0)`). The engine refuses `$.session.compact()` and
  `$.command.run` inside the command's own hook. Untested.
- [ ] Transcript noise after a shake:
  - the queued `/shake-repair` shows as a typed command plus an empty
    `shake+plannotator:` answer (the label lists every plugin that hooks
    `command.run`). Try returning `{}` (no `text`), or drop the command and run
    the repair from a timer after the `session.compact` hook returns
    (`prompt.submit` already waits for a running repair). Untested.
  - the `PostCompact` line with the long shell command comes from Orca's agent
    hook in `~/.claude/settings.json`, not from this mod; every compaction
    (native, Jev, shake) shows it. A hook can hide its output with
    `{"suppressOutput": true}`; whether that hides this line is unverified.
- [ ] Skip the startup repair check when the session has no `shake/` dir
  (review 3, P3: about 15 ms of subprocess time on the first prompt of every
  session).
- [ ] Explain why a resumed session is 10-15k tokens larger than the live one
  after a shake (attachment rows? thinking counted after load?).
- [ ] Check that the 3 s repair timeout is enough on a slow disk; the live tests
  anchored, but the wait was not recorded.
- [ ] Test `/rewind` and fork from a row before a shake boundary.
- [ ] Check storage v5 (`replaceRecords`) sessions; the repair assumes the plain
  JSONL file.
- [ ] Headless (`-p`) sessions: `$.session.compact()` is refused there; only
  `/compact shake` works. Decide whether the auto trigger should queue
  `/compact shake` in headless mode.
- [ ] Re-check the loader facts (`g1r`, `S1r`, `nOn`, `zKr`) after each Claude
  Code update; the mod depends on an undocumented file format.
- [ ] Upstream request: expose `content-replacement` (flag
  `tengu_hawthorn_steeple`) to mods as an op, and a history reload op.
- [ ] Optional: the idle file shake + mod-queued `/resume <same id>` route
  (ADR-0003) as a fallback that keeps attachment rows.

Research and reviews are in `docs/research/` (copies of the artifact files from
2026-10-07/08; `adr-0003-shake.md` is a copy of
`~/Repos/agents/docs/decisions/0003-shake-session-file-at-idle.md`).
