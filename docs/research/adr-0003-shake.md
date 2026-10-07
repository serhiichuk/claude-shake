# ADR-0003: Shake the Claude Code session file at an idle point

## Status

The user chose the compact hook + anchor repair route on 2026-10-08. It is
implemented in `~/Repos/claude-shake` and measured live (see "Measured results
of the shake"). The idle-file-shake recommendation below is kept as the record
of the earlier analysis. Reopens [ADR-0001](0001-no-in-place-shake-plugin.md): its main
reason (a shake that persists loses thinking) no longer separates the options,
because the server drops the thinking after any history edit.

## Date

2026-10-07

## Context

A long orchestrator session fills with old tool output that has no further use.
Native compaction keeps only a summary. `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`
can limit a new large Read, but it does not free context that is already used.
The user needs a shake mod for Claude Code: replace old tool results with a
placeholder and keep the rest of the history.

Tags: **[measured]** was measured in a test, **[binary]** was read in the Claude
Code 2.1.292 or 2.1.293 binary, **[types]** was read in the generated mod
types, **[upstream]** was stated in a fast-jev-compaction issue or PR and
checked as noted, **[unverified]** was not checked.

Evidence is in `~/.agents/artifacts/agents/main/research/20261007-mods-context/`:
- `live-shake.md`: the idle edit, the compact route, and the thinking drop;
- `benchmark/shake-report.md`: the offline shake of one session copy;
- `benchmark/report.md`: the output-cap benchmark;
- `jev-upstream/scout.md`: a scan of all 134 fast-jev-compaction issues and PRs;
- `jev-upstream/verify-loader.md`, `verify-mod-api.md`, `verify-shake-risks.md`:
  checks of the upstream claims against the 2.1.293 binary and types.

## Facts

### Thinking and the prompt cache

- **The server drops thinking after any edit of history it has seen.**
  [measured] Each test variant that changed history wrote a `thinking_drop`
  row with `reason: prefix_mismatch`. That includes the idle edit followed by
  `--resume`. The variant that changed no message had no such row.
- **Only the thinking after the first changed message is dropped.** [measured]
  The `thinking_drop` row names the first changed message. The thinking before
  it is still sent.
- **The thinking stays on disk.** [measured] The file shake kept every thinking
  row and signature byte for byte (33 of 33 in the offline test). The server
  does not use the dropped blocks.
- **The client cannot keep thinking after a prefix change.** [binary] Claude
  Code sends the `thinking-binding-controls-2026-08-01` beta. The env var
  `CLAUDE_CODE_POLISHED_DEWDROP` sets
  `thinking.block_binding.prefix_mismatch_behavior`:
  - `drop` sends `drop_block`;
  - `block` sends `error`, so a mismatch returns HTTP 400;
  - any other value sends nothing, and the server default applies.

  No value keeps the thinking. This account's cached flag
  `tengu_polished_dewdrop` is `"off"`, so Claude Code sends no value, and the
  server still dropped the blocks. [binary] [measured]
- **Native compaction loses all thinking.** It keeps only a summary.
- **Each history edit rewrites the prompt cache once.** [measured] After the
  offline shake, the next request wrote 73,124 cache tokens: 0.314 USD for
  that turn against 0.050 USD without the shake. The break-even point was not
  computed. [unverified]

### The session file

- **Claude Code opens, appends and closes the file for each chunk.** [binary]
  [measured] A timer drains the write queue every 100 ms. `lsof` showed no open
  descriptor at idle.
- **Claude Code rewrites the file itself.** [binary] Its GC writes a temp file,
  copies the appended bytes, checks the inode, and renames. An external edit
  that uses the same temp-and-rename method lost no rows. [measured]
- **One race remains.** [unverified] An append that opens the old inode just
  before the rename goes to the unlinked file. The window is microseconds.
- **The running process does not read the conversation back from the file.**
  [binary] [measured] After an idle edit, the live turns still sent 104.8k
  tokens. A later `--resume` sent 59.7k tokens.
- **No mod op reloads or replaces history directly.** [types] `session.messages`
  is read-only. `session.compact` is the only writer.
- **A mod can run a slash command.** [types] [binary] `$.command.run({command,
  args?})` queues `/<command> <args>` with priority `later`, and it runs when the
  session is idle. It rejects a name that is not in the session's command list.
- **`/resume <same id>` in the TUI reloads from disk.** [binary] [unverified]
  - `/resume` is a `local-jsx` command. The REPL resume handler replaces the
    transcript and has a branch for the same id.
  - Its holder check ignores `interactive` holders, so the TUI does not block
    its own id.
  - A queued `local-jsx` command runs through the same branch as a typed one.
    No check refuses a plugin origin there.
  - So `$.command.run({command: 'resume', args: <session id>})` should reload
    the shaken file. Nothing was run.
  - The read may run before the 100 ms write queue writes the last rows of the
    turn. No flush before the read was found.
- **Headless sessions cannot reload.** [binary] In `-p` and stream-json, the
  command list keeps only `prompt` commands and `local` commands with
  `supportsNonInteractive`. `/resume` is not in it.

### The safe idle point

- **`prompt.submit` without `e.turnId` runs while no turn is active.** [types]
  [measured] The hook can block the turn until `next(e)`. A shake in this hook
  took 42 ms and lost no rows.
- **`turn.complete` is not safe for a file edit.** [types] [binary] Rows of the
  ending turn can still be in the 100 ms queue.
- **`prompt.submit` refuses ops that wait on the turn.** [binary] Inside
  `prompt.submit`, both `$.command.run` and `$.session.compact()` reject with
  "it would wait on the turn this hook is holding; run it from a later event
  (turn.complete)". Both are allowed from `turn.complete`.
- **`prompt.submit` has no `agentId`.** [types] [binary] Subagents and forks do
  not raise it. A shake hook must skip events with `e.turnId` set. Events with
  `origin.kind` `task-notification`, `peer`, `plugin` or `scheduled-trigger`
  also arrive at idle without `turnId`.
- **`session.compact` and `turn.complete` also fire for subagents.** [types]
  [binary] [upstream] `session.compact` gets `trigger: 'precompute'` and
  subagent or fork transcripts (`agentId`). `turn.complete` fires for subagent
  turns and for reasons `aborted`, `refusal` and `error`. A hook must filter on
  `!e.agentId`, and on `reason === 'answer'` for `turn.complete`.
- **Storage v5 is not covered.** [unverified] The binary has a second storage
  backend with version checks. An external edit could break it. The tests used
  the plain file.

### Measured results of the shake

- **Offline shake of one copy** (`766f1e04`, Sonnet replay): [measured]
  - The first request after resume was 90,523 tokens against 108,566 (-16.6%).
  - 20 results with 53,002 characters were replaced. The newest ~16k tokens
    were kept.
  - uuids, parent links, 33 thinking blocks and 226 attachment rows stayed the
    same. 0 dangling parents, 0 unpaired tool calls.
  - Claude finished all 3 next messages, with 0 refusals and 0 reads of the
    saved files.
  - An Edit after a shaken Read was accepted. The plain copy also accepted it,
    so the test does not show whether resume restores the file-read state.
  - The sample is 2 runs per variant on one session.
- **Idle shake of a live session** (Haiku): [measured]

  | Run | Live turns | Resume |
  |---|---|---|
  | file shake at idle | 104,766 | 59,682 |
  | file shake in `prompt.submit` | 105,169 | 59,738 |
  | file shake, then `/compact` hook | 61,141 | 64,287 (duplicates) |
  | the same, after the file repair | | 61,768 |
  | `content-replacement` row, flag off | 104,771 | 105,489 |

- **Compact hook + anchor repair, live** (`claude-shake` mod, Opus, TUI,
  `/compact shake`, 2026-10-08): [measured]

  | Session copy | Before | After shake | After resume | File after |
  |---|---|---|---|---|
  | `69d7e831` orchestrator | 551k | 202.7k | 217.7k | 5.8 MB |
  | `160b5937` this research session | 292.8k | 206.2k | 216.8k | 5.4 MB |

  - The queued `/shake-repair` anchored the boundary in both runs.
  - `shake-check` on the loaded chain: 0 duplicate tool calls or results, and
    the same thinking count as before the shake.
  - The second copy answered a recall question about earlier work correctly,
    with 0 reads of the saved files (one sample).
  - The resumed context was 10-15k tokens larger than the live one. The cause
    is not checked. [unverified]
- **Without anchors the same shaken file loads wrongly.** [measured with
  `shake-check`, which mirrors the loader] On the `69d7e831` copy with the
  anchors removed:
  - full parse (5 MiB or less, or `CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP=1`):
    699 rows, 81 duplicate tool calls, every thinking block twice;
  - the default path above 5 MiB: only 38 rows and a broken parent link, so
    almost all history is lost.

  With the anchors, both paths load the same 476 rows with 0 duplicates. A shake
  appends a copy of the history, so the file often grows past 5 MiB.
- **`CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP` is a test switch only.** It forces the
  full-parse path. With anchors, both paths load correctly, so normal use does
  not need it.
- **The offline token estimate is about 20% high.** [measured] The rate was
  about 0.34 tokens per character, not 0.42.

### Compaction hooks

- **A hook that keeps handles does not survive resume.** [measured] Resume
  loaded every tool call, thinking block and the final answer twice.
  fast-jev-compaction's resumed request grew 29% (ADR-0001).
- **How the loader brings the old rows back.** [binary] [upstream]
  - For a file of 5 MiB or less, the loader (`g1r`) deletes pre-boundary rows
    only if a boundary has `compactMetadata.preservedMessages` or
    `preservedSegment`. A hook boundary has neither, so the old rows stay in
    the row map.
  - The chain walk (`MSt`) then reaches them through a stale `parentUuid`
    (Cause 1).
  - `S1r` gathers every assistant row in the whole map with the same
    `message.id`, and the tool_result rows under them. It has no boundary
    check (Cause 2). A second path recovers tool results by `tool_use_id`.
  - Above 5 MiB, the byte scanner (`nOn`) cuts all rows before a boundary
    without anchors. `CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP` turns this off.
- **The anchor shape.** [binary] `preservedMessages: {anchorUuid, uuids,
  allUuids?}` and `preservedSegment: {headUuid, anchorUuid, tailUuid}`. Native
  compaction writes them with the last summary row as the anchor. The listed
  uuids name the original rows, in place.
- **A hook cannot write anchors.** [binary] [types] `SessionCompactResult` has no
  `compactMetadata` field, and the hook path (`zKr`) clears both anchors.
- **A file repair could write anchors.** [binary] [unverified] Add
  `preservedMessages = {anchorUuid: <boundary uuid>, uuids: <post-boundary rows
  in order>}` to the last boundary. `g1r` would relink the listed rows and
  delete the unlisted pre-boundary rows from the map, so `S1r` finds no
  originals. The rows stay on disk for rewind and fork. Attachment rows are not
  restored. Failure cases fall back to the full old history:
  - a listed uuid is missing (`tengu_relink_walk_broken`);
  - the anchored boundary is not the last boundary;
  - above 5 MiB, a duplicate uuid line or an unlisted anchor before the
    boundary.
- **`$.session.compact()` is refused in headless sessions.** [binary] [upstream]
  The op rejects with "not available in a headless (-p / SDK) session yet". The
  `/compact` slash command works there and raises the same `session.compact`
  event (that is what the live-shake test ran).
- **A file repair makes the compact route clean.** [measured] The repair relinks
  each post-boundary row whose parent is pre-boundary, then drops the
  pre-boundary rows. After it, resume had 0 duplicates.
- **The compact route loses attachment rows and `toolUseResult`.** [measured]
  Attachment rows after the rebuilt results fell from 34 to 23. Each shake also
  appends a `compact_boundary` and shows a "Compacted" notice. Rewind or fork
  from a deleted row may fail. [unverified]
- **A hook without handles deletes thinking and attachments from the file.**
  [measured] Thinking 98 → 1, attachment rows 367 → 19 (ADR-0001).

### Shake limits and rules

- **Re-shaking a placeholder destroys the original.** [binary] [measured]
  Claude Code's own `<persisted-output>` has a 2,000-character preview. Neither
  test `shake.py` detects it, so a second shake would save the placeholder
  instead of the original. 4 of 8 large sessions have such blocks. Rule: a
  shaken result is never changed again; skip `[shaken:`, `<persisted-output>`
  and `<truncated-output>`, and never overwrite a saved file.
- **A shake has a floor.** [measured] In 8 large sessions, tool results are
  22-61% of the characters, and one shake frees 6-38%. Assistant text,
  `tool_use` inputs (12-35%) and machine-generated user text (up to 35%) stay.
  In 5 of 8 sessions the tool-result share falls later in the session.
  [upstream] Jev reports the same floor over repeated rounds (#70). Native
  compaction stays as the backstop.
- **Keep every call and result block.** [upstream] Deleting tool calls led the
  model to report work it did not do (#65) and to doubt its earlier answers
  (#123). The file shake keeps every `tool_use` and `tool_result` with its
  `is_error` flag (56 of 56 pairs). [measured]
- **A cut can split a surrogate pair.** [binary] [upstream] A UTF-16 cut leaves a
  lone surrogate (#110, #128). Claude Code's own preview cut (`slice(0, 2000)`)
  is not surrogate-safe. Python slicing works on code points. 0 of 592 session
  files have a lone surrogate. [measured] Rule: cut a preview on a code point.
- **A modified thinking block in the latest assistant message.** [binary]
  [upstream] [unverified] #107 suspects it causes HTTP 400. Claude Code 2.1.293
  has an error class for it (`thinking_blocks_modified`) and retries once
  without thinking. The saved runs had no such error, but in each one the
  latest assistant message had no thinking. Rule: never edit assistant rows,
  and never set `CLAUDE_CODE_POLISHED_DEWDROP=block`.

### The native `content-replacement` feature

- **It limits the tool results in one message.** [binary] If the new results
  in one user message exceed 200,000 characters (`zLn`), Claude Code saves the
  largest ones to files and replaces them with a placeholder.
- **It never replaces an old result.** [binary] A result is replaced only when
  it is new. A result that was sent once unchanged is frozen. A replaced result
  gets the same replacement on every request. The prefix therefore never
  changes, so the cache and thinking survive.
- **Replacements are stored as rows and applied again on resume.** [binary]
  The row is `{"type":"content-replacement","replacements":[{"kind":"tool-result","toolUseId":…,"replacement":…}]}`.
  The original `tool_result` row stays unchanged. On resume, `iar` applies a
  replacement for any `tool_use_id` in the history.
- **The flag `tengu_hawthorn_steeple` gates it, and it is off.** [binary]
  [measured] `LQo` returns early when the flag is false. An appended row had no
  effect.
- **The flag cannot be turned on in a reliable way.** [binary]
  - In the external build, `getEnvironmentOverrides()` returns `null` and
    `readConfigOverrides()` returns nothing.
  - `cachedGrowthBookFeatures` in `~/.claude.json` is read only when no remote
    payload was fetched, and each refresh overwrites it.
  - A binary patch breaks on each auto-update and breaks the macOS code
    signature.
- **A replacement of an old result costs the same as a shake.** [binary, by
  reasoning] It changes the prefix, so the cache is rewritten and the thinking
  after it is dropped. It also applies only on resume, because the live
  process does not read rows.
- **The model reads the full output only if it decides to.** [measured] The
  native placeholder is `<persisted-output>Output too large (…). Full output
  saved to: <path> Preview (first …)`. Nothing expands it. The model must call
  Read or Bash on the path.

### Output caps

- **Most large output comes from Read.** [measured] Over 118 sessions larger
  than 1 MB, an 8,000-character cap on every tool would have removed 3.8% of
  request tokens. Of the removed characters, Read made 79%, Bash 17% and MCP 2%.
- **`claude-output-cap` leaves out Read and Bash.** The saving is about
  0.1-0.2% of tokens (estimate). A Read cap in a hook breaks line numbers and
  the file-read state that Edit checks. [measured]
- **`CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` exists.** [binary] [unverified]
  Its default and its effect were not tested.
- **A cap does not free context that is already used.** Only a shake or a
  compaction does.

## Recommendation (opinion, not decided)

A Claude Code mod that shakes the session file at an idle point:
1. In `prompt.submit` without `e.turnId`, if the context is over a threshold,
   wait until the file size is stable, then replace old tool results in the
   file with temp-and-rename. Then call `next(e)`.
2. Save each original result to a file. Write the native `<persisted-output>`
   placeholder with that path.
3. Load the shaken history at the next reload: an Orca worker restart,
   `--resume`, or `/resume <same id>`.
4. Shake rarely and in large batches. Each shake rewrites the cache once and
   drops the thinking after its oldest edited result.

## Alternatives considered

| Option | Live effect | Clean resume | Main loss |
|---|---|---|---|
| Native `/compact` | yes | yes | all detail, only a summary |
| Compact hook, handles kept | yes | no | resume loads duplicates |
| Compact hook, no handles | yes | yes | thinking and attachments in the file |
| Compact hook + file repair | yes | yes | some attachment rows, a notice |
| Compact hook + anchor repair | yes | yes [measured] | some attachment rows |
| Idle file shake + reload | after reload | yes | needs a reload |
| `content-replacement` rows | after reload | yes | flag is off |

All options except native compaction keep the thinking before the first edit.
All options rewrite the cache once for each shake.

Compact hook + file repair is the fallback if the effect is needed without a
reload. It has more moving parts. `$.session.compact()` is refused inside
`prompt.submit` and in headless sessions; it is allowed from `turn.complete` in
the TUI.

## Consequences of the recommendation

- The thinking after the oldest shaken result is lost for each shake. Native
  compaction loses more.
- The live process uses the shake only after a reload. Orca must restart the
  worker, or the session must run `/resume <same id>`.
- An orchestrator that the user talks to directly does not shrink until it is
  reloaded. In the TUI, the mod could queue the reload itself:
  `$.command.run({command: 'resume', args: <session id>})` from the main-loop
  `turn.complete`. This is untested. If it fails, only a compact route shrinks
  the session while the user keeps talking to it.
- The mod depends on an undocumented file format. Each Claude Code update needs
  a check of the shake on a copy.
- Open checks before a choice:
  - `/resume <same id>` in the TUI, queued by a mod from `turn.complete`, loads
    the shaken file (this decides between the idle shake and the compact route
    for a direct orchestrator);
  - a shake of a session whose final answer has thinking (the #107 case);
  - the guard for the append race;
  - storage v5;
  - `/rewind` and the interactive UI after a shake;
  - the cache break-even point.
- Upstream request: expose `content-replacement` to mods as an op that sets a
  replacement for one `tool_use_id`, and a reload op.
