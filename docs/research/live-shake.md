# live-shake.md: shake a live Claude Code session at an idle point

Date: 2026-10-07. Claude Code 2.1.293 (the binary under `~/.local/bin/claude`). Model for all runs: `--model haiku` (the API rows name `claude-haiku-5-5`). Spent: about 0.65 USD, measured from `total_cost_usd`.

Tags:
- **[measured]**: measured in this session.
- **[binary]**: read in the 2.1.293 binary (`strings`).
- **[types]**: read in the generated 2.1.292 mod types (`micro-compaction-evidence/types-2.1.292.d.ts`).
- **[unverified]**: not checked.

## Verdict

- **An idle edit of the session file is safe, and it survives resume. The running process does not see it.** [measured]
  - The edit kept every row, every uuid and parent link, and every unchanged byte. The live process appended its later rows to the edited file.
  - The live process sent the unshaken history on the next turns (104,766 tokens). A later `--resume` sent 59,682 tokens.
- **No mod API reloads history.** [types] [binary] The only in-process route is `session.compact`. It rebuilds messages and re-appends them to the file.
- **Two mechanisms work** (opinion on the choice, measured on the parts):
  1. **Edit at idle, then reload.** A `prompt.submit` hook edits the file before the turn starts. The live process uses the shake only after a reload: a new process with `--resume`, or `/resume <same id>` in the TUI. The binary has a same-id branch for `/resume`, but I could not test the TUI, because a new directory shows the workspace-trust prompt (a human step). [unverified]
  2. **Compact in memory, then repair the file.** A `session.compact` hook gives the live effect at once (61,141 tokens). The file then holds duplicates, and resume loads them. A file repair at the next idle point removes the duplicates (resume 61,768 tokens, 0 duplicates). The cost is the loss of the attachment rows that follow each rebuilt result.
- **New constraint: thinking does not survive any shake on the wire.** [measured] [binary] Claude Code sends `thinking.block_binding.prefix_mismatch_behavior`. After any edit of earlier history, the server drops every later thinking block (`thinking_drop`, reason `prefix_mismatch`). This happened in all three variants that changed history, and not in the variant that changed nothing. Rows on disk keep thinking byte for byte, but the model does not read it.
- **Claude Code already has a resume-safe projection, but it is off.** [binary] [measured] `content-replacement` rows replace tool_result content by `tool_use_id` at request time and are re-applied on resume. The server flag `tengu_hawthorn_steeple` gates them. It is `false` for this account, and the external build ignores environment and config overrides. An appended row had no effect (resume 105,489 tokens).

## 1. How Claude Code writes the session JSONL

- **Open, append, close for each chunk. No descriptor stays open.** [binary] [measured]
  - Rows go to a per-file write queue. A timer drains it every 100 ms (`FLUSH_INTERVAL_MS=100`), in chunks up to 100 MiB (`MAX_CHUNK_BYTES`).
  - The direct path calls `fs/promises.appendFile(path, data, {mode: 0o600})`. That opens the path with the `a` flag (`O_APPEND`) for each call. The "only if exists" path opens with `O_RDWR|O_APPEND` and checks the last byte for a torn line.
  - `lsof -p <pid>` at idle showed no open descriptor on the JSONL, in all four runs.
- **The engine rewrites the file itself during a live session.** [binary]
  - `performCompactTranscript` (local GC) runs inside the write queue after a `compact_boundary`, when the file is over 5 MiB (`F5o=5242880`). It drops pre-boundary transcript rows, but keeps rows that post-boundary rows name as parents.
  - Its discipline: stat the size and inode; sample 4 KiB at the head, the middle and the tail; write a temp file; copy any bytes appended meanwhile (whole lines only); check the inode and the samples again; `fsync`; `rename`. A change aborts it with `source_changed`.
  - `removeMessageByUuid` also rewrites in the queue.
- **Reads during a live session.** [binary] It reads the file for the GC above, for the tail-byte check, for the request-replay index (only when request recording is on), and for a uuid set that stops duplicate appends. None of them reads content back into the conversation. The conversation lives in memory.
- **Consequence for an external edit.** If the edit writes a temp file and renames it, later appends open the path and land in the new file. [measured] Two races remain:
  - A row in the queue during the edit. In the `prompt.submit` run, the turn-2 user row was created 43 ms before the edit ended. It reached the disk after the rename, so nothing was lost. [measured]
  - An `appendFile` that opens the old inode just before the rename and writes just after it. That row goes to the unlinked file and is lost. The window is microseconds. [unverified, by reasoning] The engine's own GC has no such window, because it runs inside the queue.
- **Storage v5.** The binary has a second storage backend (`storageV5`, `replaceRecords` with version preconditions). These runs used the plain file. An external edit under that backend could break its version tracking. [unverified]

## 2. Safe idle point

- **`prompt.submit` without `e.turnId` is the safe point.** [types] [measured]
  - Types: `turnId` is "absent for a prompt submitted while the session was idle". `next(e)` "resolves once the prompt entered the session and its turn started". Before `next(e)`, no turn runs.
  - The hook budget is 10 s of the hook's own time, and the clock stops during `$` calls. `$.process.run` allows up to 10 minutes. So a hook can run a file edit and block the turn until it ends.
  - Measured: the hook ran `shake.py` through `$.process.run` in 42 ms (`work/e2-hook/saved.submit.log`). The turn-2 request came after the hook ended. The file had all rows, 0 duplicate uuids and 0 dangling parents.
  - It fires for `--input-format stream-json` user messages too. [measured]
- **`turn.complete` is not a safe point.** [types] [binary] It fires "at the point its duration is reported". Rows of the ending turn may still be in the 100 ms queue.
- **`$.prompt.submit` from a plugin "runs once it is idle".** [types] It is a queued operation, but it starts a model turn of its own. [unverified]
- **No mod API exposes the write queue or a flush.** [types] A hook can only lower the risk:
  1. Wait until the file size is stable for more than 2 queue intervals (for example 300 ms).
  2. Use the temp-and-rename discipline above.
  3. Keep the old file open across the rename. After 300 ms, compare its size with the snapshot. If it grew, append the extra whole lines to the new file. (opinion)

## 3. Can the running process pick up the edit?

- **Not by itself.** [measured] Turns 2 and 3 after the edit sent 104,766 and 104,846 tokens. Before the edit it was 104,690.
- **`/resume <same id>` in the TUI: possible, not tested.** [binary] [unverified] The in-REPL resume handler reads the transcript from disk and replaces the conversation. It compares the target id with the current id (`_o!==xo`) and only skips a read-file-cache reset when they match, so the same id looks like a supported case. `/resume` is `local-jsx`, so it does not work in `-p` mode. A mod cannot type it: no op runs a slash command.
- **New process with `--resume`: works.** [measured] 59,682 tokens, the same thinking and attachment rows, no duplicates.
- **Mod API: no reload or replace op.** [types] `turn.step` pins the messages ("the messages are the engine's"). `session.messages` is read-only. `session.compact` is the only writer.
- **`$.session.compact()` with a hook: works in process.** [measured] The `/compact shake` turn made no model call. The next turn sent 61,141 tokens.
- **`content-replacement` rows: no effect while the flag is off.** [measured] [binary] See the verdict.

## 4. Is the combination consistent?

Run `e3-compact`: in-place file shake at idle, then `/compact shake` through the mod's `session.compact` hook (handles kept, except on the two user messages whose results were shaken).

- **As is: no.** [measured] Resume sent 64,287 tokens (live: 61,141). The loaded history held every tool_use, every thinking block, the newest unshaken result (53k characters) and the final answer twice.
  - Cause 1: the handled tool_result copy keeps `parentUuid` = the old tool_use row (line 87 → line 44). This is the micro-compaction bug again.
  - Cause 2: after I repaired that link, resume still loaded the old rows (63,955 tokens, same duplicates). The loader also pulls pre-boundary rows that share a `message.id` or `tool_use_id` with post-boundary copies. [measured; loader code not read]
- **With a file repair: yes.** [measured] I repaired the file in 2 steps:
  1. Relink each post-boundary row whose parent is pre-boundary to the row before it.
  2. Drop the pre-boundary transcript rows (user, assistant, attachment, system), as the engine's GC does past 5 MiB.
  - After the repair: resume 61,768 tokens, 0 duplicate tool_use or tool_result, 0 dangling parents.
  - Once the pre-boundary rows are dropped, the in-place shake of old rows does nothing.
- **What the compact route loses.** [measured]
  - Attachment rows after each rebuilt result: 34 → 23 in turn 1. The lost rows were `read_truncation_notice`, `hook_success`, `prompt_snapshot`, `deferred_tools_delta`, `mcp_instructions_delta`, `total_tokens_reminder` and `budget_usd`.
  - `toolUseResult` on the rebuilt rows.
  - Kept: thinking rows on disk (2 of 2).
  - Each shake appends a `compact_boundary` and a full copy of the history, and the user sees a "Compacted" notice.
  - The engine's `sessionRowsOffDisk` does not know about rows that an external repair deleted. Rewind or fork from such a row may fail. [unverified]

## Measurements

Scenario: turn 1 reads `big1.txt`, `big2.txt`, `big3.txt` one at a time (each 1,500 lines; Read cut each at 817 lines, about 53k characters). The shake keeps the newest 16k tokens (64,000 characters), so it shakes the `big1` and `big2` results. Turns 2 and 3 say "Reply with the single word ok." "Request" is input + cache read + cache creation of the call. All values are [measured].

| Run | Turn 1 last call | Turn 2 | Turn 3 | Resume |
|---|---|---|---|---|
| e1: file shake at idle (driver) | 104,690 | 104,766 | 104,846 | 59,682 |
| e2: file shake in `prompt.submit` (mod) | 104,793 | 105,169 | 105,246 | 59,738 |
| e3: file shake, then `/compact shake` | 104,730 | no call | 61,141 | 64,287 |
| e3 after relink only (fork) | | | | 63,955 |
| e3 after relink + pre-boundary drop (fork) | | | | 61,768 |
| e4: `content-replacement` row (flag off) | 104,695 | 104,771 | 104,848 | 105,489 |

| File check | e1 | e2 | e3 as is | e3 repaired |
|---|---|---|---|---|
| Bad lines, duplicate uuids, dangling parents | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 |
| Duplicate tool_use / tool_result ids | 0 / 0 | 0 / 0 | 3 / 3 | 0 / 0 |
| Thinking blocks on disk | 1 of 1 | 2 of 2 | 4 (2 copies) | 2 |
| Lines changed by the shake | 2 of 55 | 2 of 56 | 2 of 56 | |
| `thinking_drop` row after the edit | yes (1) | yes (2) | yes (2) | |

- **Byte check (e1):** only lines 23 and 36 differ from the backup. Each is equal to the original apart from the tool_result `content`. My re-serialization of the original rows was byte-identical, so the JS and Python JSON forms match for these rows.
- **Thinking drop:** each `thinking_drop` row has `reason: prefix_mismatch` and names the first changed message. e4, which changed no message, has none.

## Recommended design (opinion)

1. **Default: edit at idle, then reload at a natural break.**
   - A mod hook on `prompt.submit`, only when `e.turnId` is absent and only when a trigger asks for it (a size threshold or a command). It waits for a stable file size, runs the temp-and-rename shake with the straggler check, and then calls `next(e)`.
   - The shake persists. The live process uses it after `--resume` (Orca can restart a worker between tasks) or after `/resume <same id>` in the TUI. First verify `/resume <same id>` by hand in a trusted directory.
   - It keeps every row, attachment and thinking block on disk. Thinking after the first shaken result is still dropped on the wire.
2. **Only if the live effect without a restart is required: compact plus repair.**
   - The `session.compact` hook keeps handles, except on messages whose results are shaken.
   - At the next idle `prompt.submit`, the hook repairs the file: relink, then drop pre-boundary transcript rows.
   - Accept the loss of the attachment rows after rebuilt results, a boundary per shake, and a "Compacted" notice. Test `$.session.compact()` from inside `prompt.submit` first. [unverified]
3. **Upstream request:** expose `content-replacement` (the `tengu_hawthorn_steeple` budget mechanism) to mods, for example as an op that sets a replacement for one `tool_use_id`. It already re-applies on resume, needs no file edit, and leaves every row unchanged.
4. **ADR-0001 impact:** the ADR rejected the strip-handles approach because it lost thinking. Thinking after a changed message is now dropped server-side in every variant. The deciding criteria become attachments, duplicates and the need for a reload.

## Evidence

All paths are under `/private/tmp/claude-501/-Users-serhiichuk-Repos-agents/25250090-c99b-4ed8-800a-070cc842dc8f/scratchpad/live-shake/`:

- `shake.py`: the in-place shake (temp, tail copy, inode and size checks, rename). `cap-benchmark` had written no `shake.py` when I started.
- `analyze.py`: the row, chain, thinking and duplicate summary.
- `live.py`: the driver. It keeps one `claude -p --input-format stream-json` process for 3 turns, then runs `--resume`.
- `mod/`: the research mod (`prompt.submit` shake, `session.compact` shake). `claude plugin validate` passes with warnings (no author, no `.catch`).
- `work/<run>/report.json`, `work/<run>/<sid>.stream.jsonl`: per-run results and the raw stream.
- `work/e3-compact/relink-fork.stream.jsonl`, `work/e3-compact/gc-fork.stream.jsonl`: the repair forks.
- `bin/strings.txt`, `bin/ctx.py`: the binary strings and the context grep. Offsets: write queue ~25,333,637; `rwe` ~25,371,544; GC ~25,349,000; replacement budget ~19,180,529; flag gate `LQo` ~19,176,828; in-REPL resume ~43,532,171.

Sessions are in `~/.claude/projects/-private-tmp-claude-501--Users-serhiichuk-Repos-agents-25250090-c99b-4ed8-800a-070cc842dc8f-scratchpad-live-shake-work-<run>/`:

- `6a85bec8-…` (e1), `0d5d47e6-…` (e2), `01548c3e-…` (e3), `01984d91-…` (e4).
- e3 forks: `6680c7c9-…` (as is), `e97fd7d3-…` (relinked), `ca9a7aca-…` (repaired).
- Backups next to them: `.bak` (before the shake), `.live` (after the live process), `.prefix` (before the relink), `.relinked` (before the drop).

## Side effects

- I created the sessions and backups listed above. I did not delete them. The engine also created an empty `memory/` directory in each project directory.
- I installed no plugin and loaded the mod only with `--plugin-dir`. I did not change `~/.claude/settings.json` or `~/.claude.json`; I only read `cachedGrowthBookFeatures`. I touched no existing session. No interactive prompt appeared, and I pushed nothing.
