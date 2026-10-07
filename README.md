# shake

A Claude Code 2.1.293 mod (function-hook plugin). It shrinks a long session
while you keep working in it: during a compaction it replaces old, large tool
results with a `<persisted-output>` placeholder that points to a saved copy.
Every other message stays as it is. After the compaction it writes anchors on
the compaction boundary in the session file, so a later `--resume` loads the
shaken history without duplicates.

The plugin name is `shake`, because Claude Code reserves names that start with
`claude-`.

## How it works

- **Trigger.** After each main-loop turn that ends with an answer, the mod reads
  the context usage. If the usage is at or above the threshold, it calls
  `$.session.compact({ instructions: 'shake' })`. The engine also raises
  `session.compact` for its own auto-compaction, and the mod handles that too.
  For a manual test, type `/compact shake`.
- **Shake** (`session.compact` hook). The mod acts on `/compact shake`, on its
  own trigger and on `auto`. It skips `precompute`, subagent and fork
  transcripts, and a plain `/compact`.
  - The newest tool output (16k tokens) stays as it is.
  - An older tool result larger than 2,000 characters is saved to
    `<project dir>/<session id>/shake/<tool_use_id>.txt` (file mode 600,
    directory mode 700, never overwritten). Its text becomes the native
    placeholder: `Output too large (…). Full output saved to: <path>` and a
    500-character preview that ends on a code point.
  - A result that starts with `[shaken:`, `<persisted-output>` or
    `<truncated-output>` is never shaken again.
  - Assistant messages, `tool_use` blocks, `tool_use_id`s and `is_error` flags
    stay. Each message that the mod did not change keeps its engine handle.
  - If the shake frees less than 15% of the used context, the mod does not
    shake. On `auto`, native compaction runs instead. On `/compact shake` and on
    the mod's own trigger, the compaction is skipped with a one-line reason.
- **Anchor repair** (`/shake-repair`). The shake hook queues this command. It
  runs when the session is idle. An idle `prompt.submit` runs the same repair
  after a load, after a failed queue and once after a timeout. It also waits
  for a repair that is still running, so no turn starts during a rewrite. A
  prompt waits at most about 3 s plus the rewrite. After a refusal, or after
  a second timeout, the mod gives up on that boundary and shows a toast. The
  shake records its time in
  `<project dir>/<session id>/shake/last-shake.json`. The repair:
  1. finds the last `compact_boundary`. It stops if the boundary already has
     anchors, if a native summary follows it, or if it is not the one
     boundary at or after the recorded shake time (another plugin or a
     native compaction wrote it);
  2. waits until the new boundary and every tool result of the shaken
     transcript are on disk, and the file size is stable for 250 ms (timeout
     3 s);
  3. checks that the rows after the boundary form one chain;
  4. adds `compactMetadata.preservedMessages = {anchorUuid: <boundary uuid>,
     uuids: <rows after the boundary, in order>}` to the boundary line and
     changes no other byte;
  5. writes a temp file in the same directory, copies whole lines appended
     meanwhile, checks the inode, calls fsync and renames. A hard-link backup
     (`<session>.jsonl.shake-bak.<ns>`) exists until the rename succeeded. If
     rows reached the old file during the rename, the repair copies them to
     the new file and keeps that backup. After each repair, only the newest
     backup of the session stays.

  On resume, the loader (`g1r`) then relinks the listed rows and drops the
  pre-boundary originals from memory. The rows stay in the file.

## Requirements

- Claude Code 2.1.293 (the mod API is early access and changes between
  releases).
- `python3` on `PATH`. The file work runs in `bin/shake_io.py`, because the
  mod environment has no rename, fsync or file modes.

## Install

Load the plugin for one session:

```sh
claude --plugin-dir /Users/serhiichuk/Repos/claude-shake
```

`$.session.compact()` works only in the interactive terminal UI. In `-p` and
SDK sessions, only `/compact shake` and the engine's auto-compaction reach the
hook.

## Config

All values are in `CONFIG` in `hooks/shake.ts`. There are no other options.

| Key | Default | Meaning |
|---|---|---|
| `thresholdPercent` | 60 | Context usage that starts a shake after a turn |
| `keepTokens` | 16000 | Newest tool output that is never shaken |
| `tokensPerChar` | 0.34 | Token estimate for one character |
| `minResultChars` | 2000 | Smallest result that is shaken |
| `floorShare` | 0.15 | Least share of the used context a shake must free |

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
6. Type `/compact shake`. Expected: a toast `shake: replaced N old tool
   results` and a "Compacted" notice, or one line that says the shake is below
   the floor.
7. Wait 1 second. The queued `/shake-repair` runs by itself.
8. In a second terminal, run `bin/shake-check <fork path>`. Expected:
   - the last boundary has `"anchors": true`;
   - `loader.relink` is `anchors applied`;
   - all `duplicate_*` counts are 0;
   - `saved_files_missing` is 0.
9. Run `/context`. Expected: fewer used tokens than in step 5.
10. Send one prompt, for example `Reply with ok`. Expected: a normal answer.
11. Exit, then run the resume command again. Expected: `/context` shows about
    the same usage as in step 9, and `bin/shake-check` still reports 0
    duplicates.
12. Optional: ask the model to read one saved file from a placeholder.
    Expected: it reads the full original output.
13. Optional, for the automatic trigger: set `thresholdPercent` to a value
    under the current usage, save the file, and send one prompt. Expected:
    after the answer, the same toast and notice as in step 6.
14. Remove the fork when done: the fork `.jsonl` file and the
    `<project dir>/<new id>/` directory.

## Measured

One live test on 2.1.293 (the user's run, an Opus fork of a 551k-token
session):

- `/compact shake`: context 551k -> 202.7k tokens. The first request after
  `--resume`: 217.7k tokens.
- The boundary was anchored. `bin/shake-check` reported 0 duplicates.
- The same file without anchors: 81 duplicate `tool_use` ids on the path for
  files of 5 MiB or less, and only 38 loaded rows on the path above 5 MiB.

## Known limits

- `$.session.compact()` is available only in the TUI. Headless sessions refuse
  it; there, use `/compact shake` or rely on auto-compaction.
- A changed user message loses its engine handle. Its attachment rows and its
  `toolUseResult` record are not written again (measured: 34 to 23 attachment
  rows in the research run).
- Each shake writes a `compact_boundary` and shows a "Compacted" notice.
- The server drops the thinking after the first changed message, and the
  prompt cache is written again once per shake.
- The anchor repair was measured in one live resume only (see Measured).
- Above 5 MiB, the engine's own transcript GC deletes the unlisted
  pre-boundary rows from the file, as it does after a native compaction.
  `/rewind` to a point before the shake may then fail.
- The repair refuses (and leaves the file as it is) when the rows after the
  boundary do not form one chain, for example after a rewind.
- Storage v5 is not supported. Without a plain session file, the repair does
  nothing.

## Checks

```sh
claude plugin validate .
claude plugin test .          # selection, placeholder and preview unit checks
python3 test/test_repair.py   # save, repair and fork on a copied fixture
```

`test/test_repair.py` takes a hook-compacted session file as its argument. The
default is the e3 file of the live-shake research run. The fixture is only
copied.

Type-check: after one load with `--plugin-dir`, the engine writes
`.claude-plugin/types/`, and `tsc -p .` works. Before that, use the
`tsconfig.json` from the header of the types file that the `plugin-authoring`
skill writes.
