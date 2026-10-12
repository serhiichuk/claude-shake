# TODO

- [ ] Test the automatic shake (`turn.complete`, usage >= 60%) once on a
  session copy. Only the manual `/compact shake` has run live. The user-scope
  install turns it on in every session; until it passes, lower
  `thresholdPercent` only on a copy, or disable the plugin for work sessions if
  they approach 60%.
- [ ] Test the floor fix and `/shake` live. A manual `/compact shake` now has
  no floor (`e.trigger === 'manual'`). `/shake` queues `/compact shake` from
  `$.clock.after(0, ...)`, because the engine refuses `$.command.run` inside
  the command's own hook. Unverified:
  - that the queued run is not refused;
  - that a plugin-queued `/compact` arrives with `trigger: 'manual'` (if it
    arrives as `plugin`, the floor applies to `/shake`);
  - that `return {}` shows no empty output row.

  The auto trigger keeps `floorShare` for the floor and its retry gate
  (`retryAboveTokens`). Before a lower auto floor, get the cache cost per
  shake (see the cache item below).
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
- [ ] Check prompt cache invalidation: measure the cache write on the first
  request after a shake (`cache_creation_input_tokens`) and the cost per shake.
  Find the break-even point against keeping the full history.
  Cache TTL facts (scout report, 2026-10-12, from
  https://code.claude.com/docs/en/prompt-caching.md, not re-read): on a
  subscription the main loop gets 1 h and subagents get 5 min. Overrides:
  `promptCacheTtl` / `CLAUDE_CODE_PROMPT_CACHE_TTL` and
  `subagentPromptCacheTtl` / `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` (`5m` or
  `1h`). A 1 h write costs 2x base input, a 5 min write 1.25x.
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
- [ ] Headless (`-p`) sessions: `$.session.compact()` is refused there; only
  `/compact shake` works. Decide whether the auto trigger should queue
  `/compact shake` in headless mode.
- [ ] Re-check the loader facts (`g1r`, `S1r`, `nOn`, `zKr`) after each Claude
  Code update; the mod depends on an undocumented file format.
- [ ] Upstream request: expose `content-replacement` (flag
  `tengu_hawthorn_steeple`) to mods as an op, and a history reload op.
- [ ] Optional: the idle file shake + mod-queued `/resume <same id>` route
  (ADR-0003) as a fallback that keeps attachment rows.

Decisions: [ADR-0003](../agents/docs/decisions/0003-shake-session-file-at-idle.md)
in the `agents` repo (see README "Decisions"). Frozen research and review copies
from 2026-10-07/08 are in `docs/research/`.
