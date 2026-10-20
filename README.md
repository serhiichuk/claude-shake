# shake

A Claude Code 2.1.304 mod (function-hook plugin). It shrinks a long session
while you keep working in it: at an idle point it replaces old, large tool
results in the session file with a `<persisted-output>` placeholder that points
to a saved copy. Every other line stays as it is. Then it queues
`/resume <same session id>`, so the session loads the shaken file at once.

The mod uses no compaction. On a Team or Enterprise login, the built-in
`cc-plugin-sec-default` guard skips the `session.compact` hook of a user
plugin, so the compaction route of 0.3.x did not work there.

The plugin name is `shake`, because Claude Code reserves names that start with
`claude-`.

## Decisions

The design decisions live in the `agents` repo, not here. These links assume
both repos are checked out side by side under `~/Repos`.

- [ADR-0003: shake route and all facts it depends on](../agents/docs/decisions/0003-shake-session-file-at-idle.md)
  ([GitHub](https://github.com/serhiichuk/agents/blob/main/docs/decisions/0003-shake-session-file-at-idle.md))
- [ADR-0001: the earlier rejection of an in-place shake](../agents/docs/decisions/0001-no-in-place-shake-plugin.md)
  ([GitHub](https://github.com/serhiichuk/agents/blob/main/docs/decisions/0001-no-in-place-shake-plugin.md))

`docs/research/` holds frozen copies of the reports and reviews the ADR cites.
Update the ADR, not the copies.

## How it works

- **Threshold shake.** After each main-loop turn that ends with an answer, the
  mod reads the used context. If it is at or above `thresholdTokens`, and the
  shake frees at least `floorShare` of it, the mod shakes. After a try, the
  next one waits until the context grows by `floorShare`.
- **Idle shake.** After each main-loop turn, and when a session starts or
  resumes, the mod starts a timer that ends when the prompt cache expires: the
  time of the last main-loop request plus 1.5 times the cache lifetime (90
  minutes for the 1 h cache, as in omp; the margin keeps a shake off a cache
  that is still warm). A new prompt stops it. When it fires, the next request
  writes the whole cache in any case, so the mod shakes with no floor, if any
  tool result is old enough. On a resume after a longer pause, the timer fires
  at once.
  - The cache lifetime comes from the session file: the newest cache write
    shows `ephemeral_1h_input_tokens` (60 minutes) or
    `ephemeral_5m_input_tokens` (5 minutes). This follows
    `CLAUDE_CODE_PROMPT_CACHE_TTL`, `promptCacheTtl` and the plan default
    without reading them. With no cache write found, the mod uses 60.
- **Manual shake.** Type `/shake`. It has no floor.
- **Selection.**
  - The newest tool output (16k tokens) stays as it is.
  - An older tool result larger than 2,000 characters is saved to
    `<project dir>/<session id>/shake/<tool_use_id>.txt` (file mode 600,
    directory mode 700, never overwritten). Its text becomes the native
    placeholder: `Output too large (…). Full output saved to: <path>` and a
    500-character preview that ends on a code point.
  - A result that starts with `[shaken:`, `<persisted-output>` or
    `<truncated-output>` is never shaken again. Claude Code itself saves large
    new results as `<persisted-output>` (measured on 2.1.304: a 25,000-character
    Bash output), so these are not shaken.
- **File rewrite** (`bin/shake_io.py shake`):
  1. waits until the file size is stable for 250 ms and the file ends with a
     whole line (timeout 3 s);
  2. replaces the `content` of each selected `tool_result` block, in every row
     that holds it, and changes no other line. `tool_use` blocks, ids,
     `is_error` flags, thinking, attachment rows and `toolUseResult` records
     stay;
  3. writes a temp file in the same directory, copies whole lines appended
     meanwhile, checks the inode, calls fsync and renames. A hard-link backup
     (`<session>.jsonl.shake-bak.<ns>`) exists until the rename succeeded. If
     rows reached the old file during the rename, the rewrite copies them to
     the new file and keeps that backup. After each rewrite, only the newest
     backup of the session stays.

  A prompt that you send during the rewrite waits for it.
- **Reload.** The live process does not read the file back, so the mod queues
  `/resume <same session id>` with `$.command.run`. It runs when the main loop
  is idle and redraws the transcript from the file. Background shells and
  background subagents keep running across it, and their results still reach
  the session (measured). Classic `SessionEnd` and `SessionStart` hooks run
  with the source `resume`.
- **Status line.** After the reload, the mod writes one dim transcript line
  that the model does not read: `Shook N tool results (~X tokens freed).`, as
  omp shows it. `/shake` with nothing to shake shows `Nothing to shake.`
- **Cost.** Each shake makes the next request write the prompt cache of all
  messages after the first changed one again, and the server drops the
  thinking after that message. The break-even is about `20 x kept / freed`
  requests with the 1 h cache.

## Requirements

- Claude Code 2.1.304 (the mod API is early access and changes between
  releases).
- `python3` on `PATH`. The file work runs in `bin/shake_io.py`, because the
  mod environment has no rename, fsync or file modes.
- An interactive session (the TUI). A headless (`-p`) session has no `/resume`
  command: the mod shakes the file, and the session loads it at its next
  `--resume`.

## Install

Install from GitHub:

```sh
claude plugin marketplace add serhiichuk/claude-shake
claude plugin install shake@claude-shake
```

To get a new version, run `claude plugin marketplace update claude-shake`.

Load the plugin from a local clone for one session:

```sh
claude --plugin-dir /path/to/claude-shake
```

`--plugin-dir` overrides an installed copy of the same plugin for that session.

## Config

Four values are plugin settings. Change them in `/config`, or in
`settings.json` under `pluginConfigs.shake.options`.

| Setting | Default | Meaning |
|---|---|---|
| `thresholdTokens` | 150000 | Used context that starts a threshold shake |
| `floorShare` | 0.33 | Least share of the used context a threshold shake must free |
| `idleShake` | true | Shake with no floor when the prompt cache expires |
| `cacheTtlMinutes` | 0 | Cache lifetime override; 0 reads it from the session |

The other values are in `CONFIG` in `hooks/shake.ts`:

| Key | Default | Meaning |
|---|---|---|
| `keepTokens` | 16000 | Newest tool output that is never shaken |
| `tokensPerChar` | 0.34 | Token estimate for one character |
| `minResultChars` | 2000 | Smallest result that is shaken |

With `--plugin-dir`, a saved edit reloads the module in the running session.

## Tools for a manual test

- `bin/shake-fork <session id or path>`: copies a session to a new id in the
  same project directory. Only the `sessionId` values change; `cost-state`
  rows are left out. The source file is read only, and its sha256 is checked
  before and after. It prints the `claude --resume` command with a `cd` to the
  cwd of the first row: Claude Code finds a session through the project
  directory of the directory the session started in, not the last cwd. If
  that cwd does not map to the project directory name, it prints a warning.
- `bin/shake-check <session.jsonl>`: prints rows, boundaries with or without
  anchors, and what the loader would load: duplicate message blocks,
  `tool_use` ids and `tool_result` ids, dangling parents, thinking blocks,
  shaken results and saved files present. It mirrors the 2.1.293 loader on a
  best-effort basis.

## Manual test

Each step that sends a prompt to the model costs API tokens.

1. Pick a long session with large old tool outputs (more than 100k tokens of
   context). Note its session id.
2. Run `bin/shake-fork <session id>`. Expected: `source sha256 (unchanged)`, a
   `fork:` path and a `cd … && claude --resume <new id> --plugin-dir …`
   command.
3. Run `bin/shake-check <fork path>`. Keep the output as the baseline.
4. Run the printed command. Expected: the session opens with no plugin error
   line. `claude --debug` shows the plugin's lines in the debug log.
5. Run `/context` and note the used tokens.
6. Type `/shake`. Expected: the transcript redraws, then the dim line
   `Shook N tool results (~X tokens freed).`, or `Nothing to shake.`
7. In a second terminal, run `bin/shake-check <fork path>`. Expected:
   - all `duplicate_*` counts are 0;
   - `dangling_parents` is 0;
   - `saved_files_missing` is 0.
8. Send one prompt, for example `Reply with ok`. Expected: a normal answer.
9. Run `/context`. Expected: fewer used tokens than in step 5.
10. Exit, then run the resume command again. Expected: `/context` shows about
    the same usage as in step 9.
11. Optional: ask the model to read one saved file from a placeholder.
    Expected: it reads the full original output.
12. Optional, for the automatic triggers: set `thresholdTokens` to a value
    under the current usage (or `cacheTtlMinutes` to 1 for the idle shake,
    which then fires 90 s after the last request), and send one prompt.
    Expected: the same redraw and line as in step 6.
13. Remove the fork when done: the fork `.jsonl` file and the
    `<project dir>/<new id>/` directory.

## Measured

Live tests on 2.1.304 with the Team login and the guard active (Haiku forks,
2026-10-20; report in `~/.agents/artifacts/claude-shake/main/20261020-file-route-spike/`):

- A mod-queued `/resume <same id>` loaded an edited file: a fork with 2 results
  replaced sent 7,019 fewer tokens than the unedited control.
- The threshold shake from `turn.complete` shook 11 results. The next request
  sent 140,250 tokens against 171,658 before.
- The idle shake fired 90 s after the last request (`cacheTtlMinutes: 1`) and
  shook 8 results.
- After both shakes, `bin/shake-check` reported 0 duplicates, 0 dangling parents
  and 0 missing saved files.
- A background shell and a background subagent kept running across the reload,
  and both results reached the session.

## Known limits

- Each reload redraws the transcript, and the classic `SessionStart` hooks add
  their context again.
- The server drops the thinking after the first changed message, and the
  prompt cache is written again once per shake.
- Headless sessions do not reload (see Requirements).
- Not tested: a prompt typed while the reload runs, `/rewind` and fork after a
  shake, Monitor tasks and cron jobs across the reload.
- Storage v5 is not supported. Without a plain session file, the rewrite
  refuses.

## Checks

```sh
claude plugin validate .
claude plugin test .          # selection, placeholder and preview unit checks
python3 test/test_io.py       # save, shake, cache, check and fork on a copied fixture
```

`test/test_io.py` takes a session file with large tool results as its
argument. The default is the e3 file of the live-shake research run. The
fixture is only copied.

Type-check: after one load with `--plugin-dir`, the engine writes
`.claude-plugin/types/`, and `tsc -p .` works. Before that, use the
`tsconfig.json` from the header of the types file that the `plugin-authoring`
skill writes.
