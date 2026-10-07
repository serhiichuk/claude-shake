VERDICT: REQUEST_CHANGES
SNAPSHOT: /Users/serhiichuk/Repos/claude-shake tree-bd9f543489abc80c1630553afb4bd03dd2ebdf16b4b006e71df0afc1f4235a75

## Focus Area Assessment

### 1. Task compliance and admitted deviations
- Plugin name: the name `shake` complies with engine constraints. The engine reserves names that start with `claude-`.
- Floor fall-through: the implementation deviates from the brief. Below the floor, the hook returns `{ skip }` for `/compact shake` and for its own trigger. The brief requires falling through to native compaction with `next(e)`.
- Repair queue site: the repair queues from `session.compact` instead of `turn.complete`. This covers all three triggers, but `turn.complete` does not await or queue the repair directly.
- Manual trigger: `/compact shake` works in both the TUI and headless sessions.

### 2. Data safety of session-file rewrite
- Temp file and rename: `bin/shake_io.py` writes a `.shake-tmp` file in the same directory, copies appended lines, checks the inode and size, and executes `os.rename`.
- File synchronization: `fsync` runs on the temporary file and on the parent directory.
- File permissions: file mode 0600 and directory mode 0700 are preserved.
- Hard link backup: `os.link` creates a `.shake-bak` file before rename. If late bytes arrive, the script copies them and retains the backup. However, a retained backup causes future repairs to fail.
- Crash safety: a crash before rename leaves the original session file unchanged. A crash after rename leaves the rewritten file durable on disk.
- Write-queue race: the repair waits for file size stability over 250 ms (2.5 write queue intervals) before rewriting.

### 3. Correctness of anchor repair against loader facts
- Anchor shape: `preservedMessages` matches the shape that `g1r` requires (`{ anchorUuid, uuids }`).
- 5 MiB or less: `g1r` relinks listed rows in sequence and deletes unlisted rows before the boundary. In the e3 fixture, duplicate tool use and result counts drop from 3 to 0.
- Above 5 MiB: `nOn` checks `anchorUuid` and listed UUIDs. If a listed UUID points to an unlisted pre-boundary parent, `nOn` triggers a fallback scan. The fallback parses the file and lets `g1r` prune old rows in memory.
- Chain integrity: `shake_io.py` refuses to anchor if rows after the boundary do not form a single chain.

### 4. Shake selection
- Keep window: the newest 16,000 tokens of tool output remain untouched.
- Size limit: results with 2,000 characters or fewer remain untouched.
- Tombstone protection: content that starts with `[shaken:`, `<persisted-output>`, or `<truncated-output>` is never shaken again.
- Structure preservation: assistant messages and unchanged user messages keep their properties and engine handles.
- Surrogate safety: `preview()` steps back when a cut splits a UTF-16 surrogate pair.
- Output saving: original outputs write to disk with mode 0600 and directory mode 0700 without overwriting existing files.

### 5. Hook filters and concurrency guards
- Subagent isolation: hooks filter out events that contain `agentId`.
- Precompute: `session.compact` skips `trigger === 'precompute'`.
- Turn reason: `turn.complete` acts only on `e.reason === 'answer'`.
- Idle check: `prompt.submit` checks `!e.turnId`.
- Guard race: `turn.complete` awaits `next(e)` before setting `isCompacting`, which allows overlapping dispatches to enter.
- Turn isolation race: `prompt.submit` does not wait for a running background repair. A new turn can modify the session file while `shake_io.py` rewrites it.

### 6. Tools verification
- `bin/shake-fork`: the script opens the source file in read-only mode (`rb`), computes sha256 before and after, and creates a separate target file. The source session file cannot be modified.
- `bin/shake-check`: the tool mirrors `g1r` and `S1r` faithfully, including the 5 MiB cut, anchor relinking, pre-boundary deletion, parent walk, and split-row recovery.

---

## Blocking

- **[P1 / HIGH] Concurrency race allows a turn to start while the session file rewrite runs**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/register.ts:33`, `hooks/register.ts:40-46`, and `hooks/register.ts:61-64`.
  - **Location**: `hooks/register.ts:33` and `hooks/register.ts:62`
  - **Failure scenario**:
    1. A shake finishes and queues `shake-repair`.
    2. The engine executes `/shake-repair`. The hook calls `repair($)` and sets `repairing = runRepair($)`.
    3. `runRepair` sets `isRepairPending = false` on line 33 and awaits `runHelper` (which runs `python3 bin/shake_io.py repair`).
    4. While `shake_io.py` waits 250 ms for file size stability and prepares the rewrite, the user submits a prompt.
    5. `prompt.submit` runs. It evaluates `if (!e.turnId && isRepairPending)`. Because `isRepairPending` is already `false`, it does not await `repairing`.
    6. `prompt.submit` calls `return next(e)`. The engine starts the turn.
    7. The engine appends new turn records to the session file while `shake_io.py` rewrites the file.
    8. `shake_io.py` detects size or inode changes and aborts with `Refused("session file changed under the repair")`.
    9. The compaction boundary remains unanchored. The system violates the rule: "Never edit the file while a turn runs."
  - **Suggested fix**:
    In `prompt.submit`, wait if a repair is pending or actively running:
    ```ts
    on('prompt.submit', async ($, e, next) => {
      if (!e.turnId && (isRepairPending || repairing)) await repair($)
      return next(e)
    })
    ```
    In `runRepair`, keep `isRepairPending = true` until `runHelper` completes with exit code 0.

- **[P1 / HIGH] Clearing `isRepairPending` before helper completion prevents repair retry**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/register.ts:30-38` and `hooks/register.ts:61-64`.
  - **Location**: `hooks/register.ts:33-37`
  - **Failure scenario**:
    1. The queued command `/shake-repair` runs.
    2. `runRepair` sets `isRepairPending = false` on line 33 and clears `expectation` on line 34.
    3. `runHelper` fails or times out with exit code 2 (e.g. disk latency or write queue lag exceeding timeout).
    4. `runRepair` logs the failure and returns without resetting `isRepairPending`.
    5. The user sends the next prompt.
    6. `prompt.submit` checks `isRepairPending`. Because the flag is `false`, it does not run `repair($)`.
    7. The second repair trigger never fires. The boundary remains unanchored on disk.
    8. When the session resumes via `claude --resume`, `g1r` finds no anchors and the loader restores all pre-boundary duplicate rows.
  - **Suggested fix**:
    Clear `isRepairPending` and `expectation` only after `run.exitCode === 0`. If `run.exitCode !== 0`, leave `isRepairPending = true` so `prompt.submit` retries the repair.

- **[P1 / HIGH] `retryAboveTokens` is never reset to 0 after a successful compaction**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/register.ts:70-77`.
  - **Location**: `hooks/register.ts:75`
  - **Failure scenario**:
    1. A shake attempt frees less than the floor share.
    2. The hook returns `compacted.skip`.
    3. Line 75 sets `retryAboveTokens = tokens * (1 + CONFIG.floorShare)` (e.g. 138,000 tokens).
    4. In a subsequent turn, token usage reaches 140,000 tokens. The auto-shake triggers and succeeds.
    5. Context usage drops to 80,000 tokens. `retryAboveTokens` remains at 138,000 tokens.
    6. Over subsequent turns, conversation usage grows back to 125,000 tokens (above the 60% threshold of a 200k window).
    7. `turn.complete` fires. `context.percent >= CONFIG.thresholdPercent` is true, but `tokens < retryAboveTokens` (125,000 < 138,000) evaluates to true.
    8. Line 73 returns early. Auto-compaction stays suppressed until usage exceeds 138,000 tokens, ignoring `thresholdPercent`.
  - **Suggested fix**:
    Reset `retryAboveTokens = 0` when compaction succeeds:
    ```ts
    const compacted = await $.session.compact({ instructions: SHAKE_INSTRUCTIONS })
    if (compacted.skip !== undefined) retryAboveTokens = tokens * (1 + CONFIG.floorShare)
    else retryAboveTokens = 0
    ```

---

## Other findings

- **[P2 / MEDIUM] Kept `.shake-bak` file permanently blocks future session repairs**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `bin/shake_io.py:163-164` and `bin/shake_io.py:199-211`.
  - **Location**: `bin/shake_io.py:163-164` and `bin/shake_io.py:209-210`
  - **Failure scenario**:
    If lines are appended during the rename window (`late > 0`), line 209 returns `{"late_bytes_copied": len(extra), "backup_kept": backup}` without unlinking `backup`. On the next compaction cycle, line 163 encounters `os.path.lexists(backup)` and raises `Refused("a backup from an earlier repair is still there")`. All subsequent repairs in the session are refused.
  - **Suggested fix**:
    Use a timestamped backup name (for example, `<path>.shake-bak.<timestamp>`), or remove an existing backup before a new repair if verification shows the previous repair succeeded.

- **[P2 / MEDIUM] `isCompacting` guard is claimed after `await next(e)` in `turn.complete`**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/register.ts:66-69`.
  - **Location**: `hooks/register.ts:67-69`
  - **Failure scenario**:
    The brief states: "Guard against overlapping dispatches: claim the guard before any await (fast-jev #107 race)." Line 67 awaits `next(e)` before testing and claiming `isCompacting`. If overlapping `turn.complete` dispatches arrive, both yield during `await next(e)` before either claims the lock.
  - **Suggested fix**:
    Check eligibility and set `isCompacting = true` before calling or awaiting `next(e)`:
    ```ts
    on('turn.complete', async ($, e, next) => {
      if (e.agentId || e.reason !== 'answer' || isCompacting) return next(e)
      isCompacting = true
      const completed = await next(e)
      // run background compact logic
      return completed
    })
    ```

- **[P2 / MEDIUM] Floor fall-through returns `{ skip }` instead of native compaction**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/register.ts:91-94`.
  - **Location**: `hooks/register.ts:91-94`
  - **Failure scenario**:
    Brief §2 states: "If the shake frees less than a floor (config, default 15% of the usage), do not shake; fall through to native compaction (`next(e)` or whatever the API defines)." For `isOurs` (`/compact shake` and plugin trigger), line 93 returns `{ skip: ... }` rather than `next(e)`. The implementer reported this deviation intentionally, but it diverges from the specification.
  - **Suggested fix**:
    Return `next(e)` when freed tokens fall below the floor:
    ```ts
    if (freed < CONFIG.floorShare * used) return next(e)
    ```

- **[P3 / LOW] Already shaken results consume budget in keep window calculation**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/shake.ts:31-35`.
  - **Location**: `hooks/shake.ts:31-35`
  - **Failure scenario**:
    `selectOld` adds `result.text.length` to `newerChars` for all results before checking `!isShaken(result.text)`. Although previously shaken results are not re-shaken, their placeholder lengths (~800 characters) count toward `newerChars`, slightly shrinking the window of actual recent output preserved.
  - **Suggested fix**:
    Skip already shaken results before incrementing `newerChars`:
    ```ts
    for (const result of resultsOf(messages).reverse()) {
      if (isShaken(result.text)) continue
      const isInKeepWindow = newerChars < keepChars
      newerChars += result.text.length
      if (!isInKeepWindow && result.text.length > config.minResultChars) old.push(result)
    }
    ```

- **[P3 / LOW] `shake-check` ignores string content in assistant messages for duplicate checking**
  - **Confidence**: MEDIUM
  - **Verification**: verified by reading `bin/shake-check:31-34`.
  - **Location**: `bin/shake-check:31-34`
  - **Failure scenario**:
    `blocks(row)` returns an empty list if `message.content` is a string instead of a list of dictionary blocks. Assistant messages containing plain string content are not counted in `duplicate_message_blocks`.
  - **Suggested fix**:
    Handle string content by returning a synthetic block: `if isinstance(content, str): return [{"type": "text", "text": content}]`.

---

## Open questions

- None. All blocking findings are verified with high confidence against the implementation code, tests, and upstream binary specifications.
