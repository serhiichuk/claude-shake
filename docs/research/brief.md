# Brief: claude-shake mod, route 1 (compact hook + anchor repair)

Repo: /Users/serhiichuk/Repos/claude-shake (new, empty, git initialized, branch main). Do not commit. Do not push.
Artifact dir: /Users/serhiichuk/.agents/artifacts/claude-shake/main/ (write your report there as impl-report.md).
Claude Code version: 2.1.293.

## Read first
1. /Users/serhiichuk/Repos/agents/docs/decisions/0003-shake-session-file-at-idle.md (all facts; sections "Compaction hooks", "Shake limits and rules", "The safe idle point").
2. /Users/serhiichuk/.agents/artifacts/agents/main/research/20261007-mods-context/jev-upstream/verify-loader.md and verify-mod-api.md (loader `g1r`/`S1r`, anchor shape, `$.command.run`, refusals).
3. The `plugin-authoring` skill (invoke it with the Skill tool) for the mod format, hot reload and typings.
4. Prior research mod (worked on 2.1.293): /Users/serhiichuk/.agents/artifacts/agents/main/research/20261007-mods-context/live-shake-src/mod/ (register.ts, hooks.json, tsconfig.json) and live-shake-src/{shake.py,analyze.py}. Generated types for 2.1.293: /private/tmp/claude-501/-Users-serhiichuk-Repos-agents/25250090-c99b-4ed8-800a-070cc842dc8f/scratchpad/live-shake/mod/.claude-plugin/types/claude-code/index.d.ts (also obtainable as the skill describes).
5. Session fork helper for tests: /Users/serhiichuk/.agents/artifacts/agents/main/research/20261007-mods-context/benchmark/bench.py (`fork`).

## Goal
A Claude Code plugin (function-hook mod) that shrinks a long session live by replacing old tool results with a placeholder during compaction, and keeps the session correct across `--resume`.

## Behavior
1. **Trigger.** `turn.complete` for the main loop only (`!e.agentId && e.reason === 'answer'`). If context usage is over a threshold (config, default 60% of the window), call `$.session.compact()`. Then queue the repair: `void $.command.run({ command: 'shake-repair' })`. Guard against overlapping dispatches: claim the guard before any await (fast-jev #107 race).
   Also give the user a manual trigger for testing (e.g. a registered `/shake` command, or `/compact shake` detected in the hook, as the research mod did). Check which one the engine allows; `$.session.compact()` is refused inside `prompt.submit` and in headless sessions.
2. **`session.compact` hook.** Act only on our own trigger, on `auto`, and on the manual test trigger. Skip `precompute` and any event with `agentId`. A plain user `/compact` keeps native behavior.
   - Keep the newest N tokens of tool output (config, default 16k tokens at 0.34 tok/char) untouched.
   - For older `tool_result` blocks over a size limit (config, default 2,000 chars): save the original text to a file (session-scoped dir, mode 600, dir 700, never overwrite an existing file), and replace the content with a `<persisted-output>` placeholder in Claude Code's native wording: "Output too large (…). Full output saved to: <path>" plus an optional short preview. Cut any preview on a code point boundary.
   - Never re-shake: skip content that starts with `[shaken:`, `<persisted-output>` or `<truncated-output>`.
   - Keep every `tool_use` and `tool_result` block, the `is_error` flag, and every assistant message unchanged. Keep handles on every message that you did not change.
   - If the shake frees less than a floor (config, default 15% of the usage), do not shake; fall through to native compaction (`next(e)` or whatever the API defines).
3. **`/shake-repair` command** (registered with `$.command.register`; its `command.run` hook returns `{ text: '' }`). Also run the same repair from `prompt.submit` when `!e.turnId` (before `next(e)`), as a second trigger. Both must be idempotent.
   - Find the last `compact_boundary` written by our hook (no `compactMetadata.preservedMessages`/`preservedSegment`). If it already has anchors, do nothing.
   - Wait until the boundary row and all rows the hook wrote after it are on disk (count or uuids, plus a stable size over >2 queue intervals of 100 ms). Do not rely on a timer alone. Time out safely and leave the file untouched.
   - Set `compactMetadata.preservedMessages = { anchorUuid: <boundary uuid>, uuids: [<post-boundary transcript rows, in chain order>] }` (verify the exact shape and semantics against `g1r` in verify-loader.md and the binary). Consider `preservedSegment` too only if the code requires it.
   - Rewrite the file with the engine's discipline: temp file in the same dir, change only the boundary line, keep every other byte, copy any lines appended meanwhile (whole lines), check inode, fsync, rename. Keep a backup until the rename succeeded. If the boundary line serialization would change key order or separators beyond the added field, abort.
   - Never edit the file while a turn runs.
4. **Config** in one place with the defaults above. No other options.

## Tooling for the user's manual test (required)
- `bin/shake-fork <session-id-or-path>`: copy a session JSONL to a new session id in the same project dir (reuse the bench.py fork logic or call it), print the `claude --resume <new-id> --plugin-dir <repo>` command. Never modify the source session; verify its sha256 before and after.
- `bin/shake-check <session.jsonl>`: print rows, boundaries (with/without anchors), duplicate `message.id` / `tool_use_id` counts on the chain the loader would load (best effort, mirror `g1r` + `S1r` logic as described in verify-loader.md), dangling parents, thinking block count, shaken result count, saved files present.
- README.md: install (`--plugin-dir`), config, the manual test procedure in numbered steps with expected results, and the known limits (TUI only for `$.session.compact`; attachments lost on changed messages; "Compacted" notice; anchor repair unmeasured).

## Constraints
- Do not run `claude` with a prompt (no API spend). `claude plugin validate <repo>` and any typecheck are fine.
- Do not touch any real session file. Tests use fixtures or forks in a temp dir.
- Thrown errors: static English messages, runtime values in `cause`.
- Comments only for constraints the code cannot express.
- Smallest working design: no abstraction layers, no extra options.

## Acceptance
- `claude plugin validate` passes; TypeScript typechecks against the 2.1.293 types.
- One runnable self-check (e.g. `test/repair.test.ts` or a Python script) that, on a fixture built from a real hook-compacted file shape (the e3 run under /private/tmp/claude-501/-Users-serhiichuk-Repos-agents/25250090-c99b-4ed8-800a-070cc842dc8f/scratchpad/live-shake/work/ if it exists, copied to a temp dir): writes anchors, keeps all other lines byte-identical, is idempotent, refuses on a partially written tail, and shake-check then reports 0 duplicates on the loaded chain.
- A unit check of the shake selection: keep-window, size limit, never re-shake, preview cut on a code point, assistant messages untouched.
- impl-report.md: files, how each acceptance item was checked (commands + output), what is unverified, open risks.
