# impl-report: shake mod, route 1 (compact hook + anchor repair)

Date: 2026-10-08. Repo: `/Users/serhiichuk/Repos/claude-shake` (branch `main`, no commit, no push). Claude Code 2.1.293. No `claude` prompt ran. No API call was made. No real session file was changed.

## Files

- `.claude-plugin/plugin.json`: the manifest. The plugin name is `shake`. `claude plugin validate` refuses `claude-shake`, because names that start with `claude-` are reserved.
- `hooks/hooks.json`: names `./register.ts`.
- `hooks/shake.ts`: `CONFIG` (the five options with the brief's defaults) and the pure logic: `selectOld`, `freedTokens`, `estimatedTokens`, `preview`, `placeholder`, `replaceResults`.
- `hooks/register.ts`: the hooks `session.start` (registers `/shake-repair`), `command.run` (`/shake-repair`, returns `{ text: '' }`), `prompt.submit` (repair when idle and pending), `turn.complete` (threshold trigger), and `session.compact` (the shake).
- `bin/shake_io.py`: the file side, called through `$.process.run`: `save` (originals, modes 600/700, `O_EXCL`) and `repair` (anchors).
- `bin/shake-check`, `bin/shake-fork`: the manual test tools.
- `test/shake.test.ts`: unit checks of the selection, run by `claude plugin test`.
- `test/test_repair.py`: the self-check of save, repair, check and fork on a copied fixture.
- `README.md`, `tsconfig.json` (extends the types the engine writes on load), `.gitignore`.

## Design decisions to review

- **Manual trigger: `/compact shake`, not a `/shake` command.** [code] `C9t` in the 2.1.293 binary lists `command.run`. So `$.session.compact()` from a `command.run` hook is refused ("it would compact under the turn this hook is holding"). `/compact shake` raises `session.compact` with `trigger: 'manual'` and `instructions: 'shake'`. It works in the TUI and in headless sessions.
- **The repair is queued from the `session.compact` hook, not from `turn.complete`.** This one place covers all three triggers (own, `auto`, `/compact shake`). The `turn.complete` hook only calls `$.session.compact()`. If the queue call rejects, the next idle `prompt.submit` runs the repair.
- **Deviation from the brief: below the floor, only `auto` falls through to native compaction.** For `/compact shake` and the mod's own trigger, the hook returns `{ skip }` with a reason. Reason (opinion): a fall-through at the 60% threshold would run a full native compaction early and lose all detail, the opposite of the mod's goal. After a skip, the own trigger waits until the usage grows by `floorShare`. To follow the brief exactly, replace the `skip` return in `hooks/register.ts` (line 93) with `return next(e)`.
- **The anchor list is all rows after the boundary that have a `uuid`, in file order.** [code] `g1r` sets the parent of `uuids[0]` to `anchorUuid` and the parent of each next row to the row before it. File order fixes the stale parent link that the hook wrote (e3 row 87 pointed to a pre-boundary row). The repair refuses when a row's parent is neither the row before it nor a pre-boundary row, because a relink would then change the topology (for example after a rewind).
- **"Rows on disk" is checked by `tool_use_id`, not by a count.** A `SessionMessage` has no uuid, and I could not verify how many rows one message becomes. The hook records the time and the ids of all tool results in its output. The repair waits for a boundary with a newer timestamp, for every one of those ids as a `tool_result` after it, for a newline at the end of the file, and for a stable size over 250 ms (2.5 queue intervals).
- **The placeholder preview is 500 characters, not the native 2,000.** It is a constant beside `CONFIG`, not an option. A 2,000-character preview would leave little to free on results of 2,000 to 4,000 characters.
- **Feedback goes to a toast and the debug log, not to `$.ui.log` in the transcript.** I could not verify whether a transcript log line writes a row with a uuid after the boundary.

## Acceptance items

1. **`claude plugin validate` passes.**
   `claude plugin validate .` printed `✔ Validation passed` (exit 0). It lists the hooks `session.start, command.run{command=shake-repair}, prompt.submit, turn.complete, session.compact` and `answers its own command: command.run{command=shake-repair}`.
2. **TypeScript typechecks against the 2.1.293 types.**
   `tsc -p <scratch tsconfig>` exited 0 with the header tsconfig of the types file, `include` = the types + `hooks` + `test`. Checked against both 2.1.293 type files: the one the `plugin-authoring` skill wrote in this session and the one in the live-shake research scratchpad. `tsc -p .` in the repo works only after one `--plugin-dir` load, because the engine writes `.claude-plugin/types/` then.
3. **Unit check of the shake selection** (`claude plugin test .`): 5 pass, 0 fail.
   - keep window: a result inside the newest 16k tokens stays; the newest result stays even at 200k characters;
   - size limit: a result of exactly 2,000 characters stays;
   - never re-shake: `<persisted-output>`, `[shaken:` and `<truncated-output>` results stay;
   - preview: a cut before an emoji keeps no lone surrogate; a newline in the second half is used;
   - assistant messages and unchanged messages are deep-equal with their handles; the changed message has no handle and keeps `tool_use_id` and `isError: true`.
   - Mutation check: with `>=` in place of `>` and without the surrogate guard, 2 of 5 tests failed. Restored, 5 of 5 pass.
4. **Repair self-check** (`python3 test/test_repair.py`, 4.3 s, exit 0). The fixture is the e3 run file `…live-shake-work-e3-compact/01548c3e-2358-4b76-9097-93997239dc25.jsonl.live`: the hook-compacted file after the live turn (116 rows, 1 boundary without anchors). Each test copies it to a temp dir. Output:
   ```
   ok repair anchors, keeps other lines, idempotent; duplicates 3 -> 0
   ok partial tail: timed out, file untouched
   ok waits for the expected tool result rows and the new boundary
   ok refuses a branched chain and a boundary that does not round-trip
   ok save: 600/700 modes, no overwrite, unsafe id skipped
   ok fork: new id, bytes kept except sessionId, source unchanged
   all checks passed; fixture unchanged
   ```
   - Anchors: the boundary line equals the original after the removal of `preservedMessages`. Every other line is byte-identical. `uuids` lists the 48 post-boundary uuid rows in file order. The file mode stays 600. No temp or backup file is left.
   - Idempotent: a second run reports `already anchored`, and the sha256 does not change.
   - Partial tail: a line without a newline at the end gives exit 2 and an unchanged file.
   - Wait: with an expected tool id missing, exit 2. With a boundary older than `since`, exit 2. A row appended 0.4 s into the wait is kept, and it is the last listed uuid.
   - Refusals (exit 3, file unchanged): a branched chain; a boundary line that does not round-trip byte for byte.
   - shake-check on the fixture: before, 3 duplicate `tool_use` ids, 1 duplicate `tool_result` id, 6 duplicate message blocks, 7 recovered rows. After, all 0, `relink: anchors applied`, 46 rows loaded, 2 thinking blocks loaded (4 in the file).
   - Fixture sha256 before and after: `677131da9ced243362dd415975f5a56fba155a8fcb43df81daddca6b7ba845c0`.

## Unverified

- No part of the mod ran in a live session. In particular these are untested:
  - that `$.session.compact()` from a detached promise after `turn.complete` is accepted in the TUI;
  - that `$.command.run` from inside a `session.compact` hook queues `/shake-repair`;
  - that the engine writes the hook's tool results within the 10 s wait;
  - that `$.process.run` and `$.session.usage` work inside these hooks.
- The live resume after the anchor repair is not measured: 0 duplicates is a result of `shake-check`, which mirrors `g1r` and `S1r` on a best-effort basis. It does not mirror the timestamp fallback (`k1r`) or `y1r`. The real duplicate count and whether thinking is kept need the manual test.
- Above 5 MiB, the byte scanner (`nOn`) and the GC with an anchor equal to the boundary itself were not read in detail. A native partial compaction also uses the boundary as anchor, so I expect it to work.
- The interrupted-turn resume check (`oAo`) expects the anchor to be a summary row. With a boundary anchor it should only skip a prefill (verify-loader.md). Not checked.
- The size text in the placeholder (`29.3KB`) follows observed native output (`18KB`, `16.1KB`). The native formatter itself was not read. The blank line before `Preview (first …)` follows the output seen in this session, not the strings dump.
- Whether a `SessionMessage` maps to user/assistant rows in a fixed way (this is why the wait uses tool ids).

## Open risks

- The append race at the rename stays (microseconds). The repair narrows it: after the rename it compares the hard-link backup with the bytes it copied. If the old inode grew, it appends the missing whole lines to the new file and keeps the backup.
- Each shake changes the history: the thinking after the first changed message is dropped, and the cache is written again once.
- A module reload resets the module state. The first idle prompt after a load then runs one repair without an expectation (2 s timeout).
- The first prompt of every session with the mod runs one `python3` process to check the file (no wait when the last boundary has anchors or is native, or when the file has no boundary).
- A rewind after a shake makes the repair refuse, so that boundary stays without anchors and a resume loads duplicates.
- The mod depends on undocumented formats (session JSONL, `preservedMessages`, `g1r`). Check it on a fork after each Claude Code update.

## Manual test

The numbered steps with expected results are in `README.md`, section "Manual test".

## Round 2: fixes from the cross-model review

Source: `review-gemini.md`, the items the coordinator verified. No `claude` prompt ran. No commit, no push. Not changed on purpose: the `turn.complete` guard (the check and `isCompacting = true` run in one synchronous continuation after `await next(e)`), and the floor deviation (the user decides).

### Changes

1. **[P1] A prompt waits for a running repair.** `prompt.submit` without `turnId` now awaits `repair($)` when a repair is pending or in flight: `if (!e.turnId && (isRepairPending || repairing))`. `repair` shares the in-flight promise, so a prompt during the stability wait or the rewrite waits for it to end.
2. **[P1] A failed repair retries.** `runRepair` clears `isRepairPending` and `expectation` only after exit 0. On exit 2 or 3 both stay, and the next idle prompt retries with a 2 s timeout (`IDLE_REPAIR_TIMEOUT_SECONDS`). The toast shows once per module load. If a newer shake replaced the expectation while the helper ran, the older run does not clear it.
3. **[P1] The retry mark resets.** After a compaction that was not skipped, `retryAboveTokens = 0`.
4. **[P2] A kept backup does not block.** The backup name is `<session>.jsonl.shake-bak.<time_ns>`. The check that refused when a backup existed is removed.
5. **[P3] Placeholders do not fill the keep window.** `selectOld` skips a shaken result before it adds to the window count.
6. **[P3] String content in shake-check.** `blocks()` reads a string `message.content` as one text block.
7. **[P2] Anchor only this mod's boundary.** `save` now takes `{since, items}` and, when it saved at least one file, writes `{"since": <ms>}` to `<project dir>/<session id>/shake/last-shake.json` (mode 600, temp file and rename). `repair` uses `--expect`'s `since`, or the recorded time when there is no expectation. It reports `done` with one of these reasons and changes nothing:
   - `not ours (no shake recorded)`;
   - `not ours (older than the last shake)`;
   - `not ours (another compaction followed the shake)`: more than one boundary at or after the shake time.

   With `--expect`, a boundary older than `since` still means wait.

Files changed: `hooks/register.ts`, `hooks/shake.ts`, `bin/shake_io.py`, `bin/shake-check`, `test/shake.test.ts`, `test/test_repair.py`, `README.md`.

### New checks

- `test/shake.test.ts`: "a shaken placeholder does not fill the keep window".
- `test/test_repair.py`:
  - `test_anchors_only_our_boundary`: no record, a record newer than the boundary, and a second boundary after the shake. Each one is `done`, and the sha256 does not change;
  - `test_old_backup_does_not_block`: an existing `.shake-bak.1` stays, and the repair anchors;
  - `test_check_counts_string_content`: two same-id assistant rows with string content give 1 duplicate message block;
  - `test_save`: no record without a saved file; the record holds `since` with mode 600.
- Mutation checks:
  - shake-check without the string fix: the string-content test failed (`duplicate_message_blocks: 0`);
  - `selectOld` without the skip: 2 of 6 TypeScript tests failed.
  - Both files were restored, and `diff -q` against the copies printed `restored`.
- Items 1 to 3 change hook state that the test kit cannot reach without `$.process.run`. They have no automated test. They were checked by reading the code and by `tsc`.

### Commands and output

```
$ claude plugin validate .
  ❯ ./register.ts hooks: session.start, command.run{command=shake-repair}, prompt.submit, turn.complete, session.compact
  ❯ ./register.ts answers its own command: command.run{command=shake-repair}
  ❯ ./register.ts gating hook without .catch: prompt.submit
  ❯ ./register.ts gating hook without .catch: session.compact
  ❯ ./register.ts calls: $.clock.now, $.command.register, $.command.run, $.process.run (via runHelper), $.session.compact, $.session.id (via runRepair, saveOriginals), $.session.usage, $.ui.log, $.ui.toast
✔ Validation passed                                   (exit 0)

$ tsc -p <scratchpad>/tsconfig.json                    (skill 2.1.293 types)    exit 0
$ tsc -p <scratchpad>/tsconfig-research.json           (research 2.1.293 types) exit 0

$ claude plugin test .
(pass) selects only old, large, unshaken results outside the keep window
(pass) the newest result stays even when it alone exceeds the window
(pass) a shaken placeholder does not fill the keep window
(pass) replacement keeps assistants, unchanged handles, ids and is_error
(pass) preview never splits a surrogate pair
(pass) preview prefers a newline in the second half
 6 pass
 0 fail

$ python3 test/test_repair.py
ok repair anchors, keeps other lines, idempotent; duplicates 3 -> 0
ok partial tail: timed out, file untouched
ok waits for the expected tool result rows and the new boundary
ok refuses a branched chain and a boundary that does not round-trip
ok anchors only the boundary of the recorded shake
ok a kept backup from an earlier repair does not block the next one
ok shake-check counts string message content as a text block
ok save: 600/700 modes, no overwrite, unsafe id skipped, shake recorded
ok fork: new id, bytes kept except sessionId, source unchanged
all checks passed; fixture unchanged                  (exit 0)

$ shasum -a 256 <e3 fixture>.jsonl.live
677131da9ced243362dd415975f5a56fba155a8fcb43df81daddca6b7ba845c0   (unchanged)
```

### Remaining risks after round 2

- A prompt can now wait for a repair: up to 10 s while a queued repair waits for the shake's rows, and up to about 2 s on each idle retry. A repair that always fails (for example, a branched chain after a rewind) runs again at each idle prompt. The cost is about 250 ms and one toast per load.
- The ownership check uses timestamps. If another plugin's compaction comes after the shake, the repair does not anchor. That boundary is then left without anchors, and a resume loads duplicates, as without this mod.
- Sessions shaken before round 2 have no `last-shake.json` record, so the repair reports `not ours` for them.

## Round 3: fixes from the second review

Source: `review2-gemini.md`, the items the coordinator verified, plus the coordinator's item 6. No `claude` prompt ran. No commit, no push.

### Changes

1. **[P1] Retries are bounded.** `settleRepair` in `hooks/register.ts` decides after each repair:
   - exit 0: the repair is done; the pending flag and the expectation are cleared;
   - exit 3 (refused), or a helper that throws or cannot start: the mod gives up at once;
   - exit 2 (timeout, or the file changed under the rewrite): one retry at the next idle prompt (`REPAIR_TIMEOUT_RETRIES = 1`), then the mod gives up.

   A give-up shows one toast: "shake: anchor repair gave up; a resume may load duplicates (see the debug log)". A new shake resets the retry count. `shake_io.py` now reports "session file changed under the repair" as exit 2 (class `Changed`), so that case gets its retry.
2. **[P2] A prompt waits for a bounded time.** Every repair run passes `--timeout 3` (`REPAIR_TIMEOUT_SECONDS`), the queued one included. A prompt that arrives during a repair still waits for the whole promise, so no turn starts while the rewrite or rename runs. The wait is at most about 3 s plus the rewrite.
3. **[P2] Writes are complete.** `write_all` loops on `os.write` until all bytes are written. Before the rename, `rewrite()` compares `os.fstat(fd).st_size` with the body plus the tail, and refuses on a mismatch.
4. **[P2] Backups are pruned.** After each successful rewrite, `prune_backups` keeps only the newest `<session>.jsonl.shake-bak.<ns>` and deletes the older ones.
5. **[P3] A bad shake record means no record.** `last_shake_since` returns `None` for a missing, empty or invalid JSON file, for a missing key, and for a `since` that is not a number. The repair then reports `not ours (no shake recorded)`.
6. **`shake-fork` cwd.** The printed `cd` uses the cwd of the first row that has one. If that cwd, with each character other than `[A-Za-z0-9]` replaced by `-`, is not the project directory name, the tool prints a warning. The rule comes from 2 observed project directory names; long-path truncation is not handled. The README says why the first cwd is used.
7. **README "Measured".** It holds the user's live result: 551k -> 202.7k after `/compact shake`, 217.7k on resume, the boundary anchored, and 0 duplicates in `shake-check`. Without anchors, the same file gives 81 duplicate `tool_use` ids (5 MiB or less) or 38 loaded rows (above 5 MiB). The known-limits line about an unmeasured repair now points to this section.

Files changed: `hooks/register.ts`, `bin/shake_io.py`, `bin/shake-fork`, `test/test_repair.py`, `README.md`, `.gitignore` (`.DS_Store`, which appeared in the repo during the round).

### New checks (`test/test_repair.py`)

- `test_old_backups_do_not_block_and_are_pruned`: with `.shake-bak.1` and `.shake-bak.2` present, the repair anchors and only `.shake-bak.2` stays.
- `test_bad_shake_record_is_no_record`: an empty record, invalid JSON, `{"since": "x"}` and `{}` each give exit 0 with `not ours (no shake recorded)`, and the file does not change.
- `test_partial_os_write_is_completed`: `os.write` is patched to write at most 4,096 bytes per call. The in-process repair gives the same bytes as a normal repair.
- `test_fork`: the output holds `cd <first row cwd> && claude`, and the warning for the temp project directory.
- Mutation checks, each file restored afterwards (`diff -q` printed `restored`):
  - without the record fix, the bad-record test failed (`'empty'`, refused, "session file has a line that is not JSON");
  - with a single `os.write`, the size check refused ("temp file size does not match what was written").
- Items 1 and 2 change hook state that the test kit cannot reach without `$.process.run`. They were checked by reading the code and by `tsc`, not by a test.

### Commands and output

```
$ claude plugin validate .
  ❯ ./register.ts hooks: session.start, command.run{command=shake-repair}, prompt.submit, turn.complete, session.compact
  ❯ ./register.ts answers its own command: command.run{command=shake-repair}
  ❯ ./register.ts gating hook without .catch: prompt.submit
  ❯ ./register.ts gating hook without .catch: session.compact
  ❯ ./register.ts calls: $.clock.now, $.command.register, $.command.run, $.process.run (via runHelper), $.session.compact, $.session.id (via runRepair, saveOriginals), $.session.usage, $.ui.log, $.ui.toast
✔ Validation passed                                   (exit 0)

$ tsc -p <scratchpad>/tsconfig.json                    (skill 2.1.293 types)    exit 0
$ tsc -p <scratchpad>/tsconfig-research.json           (research 2.1.293 types) exit 0

$ claude plugin test .
 6 pass
 0 fail

$ python3 test/test_repair.py
ok repair anchors, keeps other lines, idempotent; duplicates 3 -> 0
ok partial tail: timed out, file untouched
ok waits for the expected tool result rows and the new boundary
ok refuses a branched chain and a boundary that does not round-trip
ok anchors only the boundary of the recorded shake
ok kept backups do not block the next repair; only the newest stays
ok an empty or corrupt shake record counts as no record
ok short os.write calls still write the whole file
ok shake-check counts string message content as a text block
ok save: 600/700 modes, no overwrite, unsafe id skipped, shake recorded
ok fork: new id, bytes kept except sessionId, source unchanged
all checks passed; fixture unchanged                  (exit 0)

$ shasum -a 256 <e3 fixture>.jsonl.live
677131da9ced243362dd415975f5a56fba155a8fcb43df81daddca6b7ba845c0   (unchanged)
```

### Remaining risks after round 3

- A queued repair now has 3 s, not 10 s, to see the shake's rows. The live test anchored with the old 10 s limit; its actual wait was not recorded. A slow disk uses the one retry, then the mod gives up.
- After a give-up, that boundary stays without anchors until a manual `/shake-repair` (which runs without the old expectation and uses the shake record).
