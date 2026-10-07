VERDICT: REQUEST_CHANGES
SNAPSHOT: /Users/serhiichuk/Repos/claude-shake tree-dddd2c387861219a41ef52d97aa7231373662215498b73afc222d250ca2d119b

## Focus Area Assessment

### 1. Verification of Round 1 findings and Item 7
- Turn isolation race (`prompt.submit` waiting for repair): The hook now awaits `repair($)`. This prevents a new turn from modifying the session file during a rewrite. However, prompts can now wait up to 10 seconds behind an in-flight repair.
- Repair retry clearing: The code clears `isRepairPending` only on exit code 0. However, failed repairs (exit codes 2 and 3) now retry on every prompt without bound.
- Retry above tokens mark: Resetting `retryAboveTokens = 0` on successful compaction works correctly.
- Kept backup blocking: The timestamped backup name prevents older backups from blocking new repairs. However, old backups accumulate without bound.
- Keep window calculation: The loop skips already shaken results before it increments `newerChars`.
- String content in `shake-check`: `blocks()` wraps string message content in a synthetic text block.
- Extra item 7 (anchor only our boundary): `save` records the shake timestamp in `last-shake.json`. `repair` verifies that the boundary matches this timestamp and that no subsequent compaction occurred. Tests confirm that unrecorded, older, or superseded boundaries are left untouched.

### 2. New risks from fixes
- Prompts waiting up to 10 s on repair: An idle prompt submitted while `/shake-repair` runs waits for the in-flight repair helper. The helper can poll for up to 10 seconds for rows to arrive. This blocks user interaction.
- Retries at every idle prompt: On permanent refusal (exit 3) or repeated timeout (exit 2), `isRepairPending` remains set. Every subsequent idle prompt executes `bin/shake_io.py`, adding 250 ms to 2,000 ms of latency to every turn.
- The `last-shake.json` record: The file isolates shake boundaries cleanly. However, if the file is corrupted or empty, `shake_io.py` raises an unhandled `ValueError` that is misreported as a corrupted session file and enters the permanent retry loop.
- Unbounded backup accumulation: When late writes occur (`late > 0`), the backup file is kept. Because nothing deletes old backups, multi-megabyte backup files accumulate indefinitely in the project directory.

### 3. Data safety of session-file rewrite
- Atomic replacement and modes: The temp file uses mode 0600. `fsync` runs on the file and parent directory. `os.rename` provides atomic replacement.
- Low-level writes: `rewrite()` uses low-level `os.write()` without checking the returned byte count. A partial write on large buffers would produce an incomplete file.

---

## Blocking

- **[P1 / HIGH] Unbounded repair retries block every subsequent prompt indefinitely on failure or timeout**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/register.ts:37-52`, `hooks/register.ts:75-77`, and `bin/shake_io.py:255-275`.
  - **Location**: `hooks/register.ts:45-52` and `hooks/register.ts:75-77`
  - **Failure scenario**:
    1. A compaction triggers and queues `/shake-repair` with an expectation.
    2. The helper `bin/shake_io.py` fails with exit code 2 (e.g. expected tool rows never land on disk because of an upstream engine failure) or exit code 3 (permanent refusal, such as a branched chain after a rewind or a non-roundtrippable boundary line).
    3. Line 45 (`if (run.exitCode === 0)`) evaluates to false, so neither `isRepairPending` nor `expectation` is cleared.
    4. On the next user prompt, `prompt.submit` checks `isRepairPending || repairing`. Because `isRepairPending` is still true, it invokes `repair($, IDLE_REPAIR_TIMEOUT_SECONDS)`.
    5. If the previous failure was exit code 2 (missing rows), `shake_io.py` polls for the full 2.0-second timeout before exiting code 2 again. If it was exit code 3 (structural refusal), `shake_io.py` waits 250 ms for size stability and exits code 3 again.
    6. Because the exit code remains non-zero, `isRepairPending` and `expectation` remain set.
    7. Every subsequent idle prompt across the lifetime of the session triggers another repair run. Every turn suffers either a 2-second freeze or a 250 ms subprocess delay. There is no retry limit, exponential backoff, or permanent failure ejection.
  - **Fix**:
    Add a retry budget and clear pending state on non-recoverable errors. If `run.exitCode === 3`, immediately set `isRepairPending = false` and `expectation = undefined`. If `run.exitCode === 2`, increment a retry counter and clear pending state once attempts exceed a threshold (for example, after one retry).

---

## Other findings

- **[P2 / MEDIUM] Prompts wait up to 10 seconds behind an in-flight background repair**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `hooks/register.ts:54-59`, `hooks/register.ts:75-77`, and `bin/shake_io.py:255`.
  - **Location**: `hooks/register.ts:54-59` and `hooks/register.ts:75-77`
  - **Failure scenario**:
    1. `/shake-repair` runs with default timeout (10.0 seconds) and assigns `repairing`.
    2. While `shake_io.py` polls for tool rows or disk stability, the user enters an idle prompt.
    3. `prompt.submit` checks `repairing` and awaits `repair($, IDLE_REPAIR_TIMEOUT_SECONDS)`.
    4. Because `repairing ??= ...` returns the existing in-flight promise, `IDLE_REPAIR_TIMEOUT_SECONDS` (2 seconds) is ignored.
    5. If the engine is slow or rows never appear, the prompt remains blocked for up to 10 seconds before the turn can begin.
  - **Fix**:
    Use a shorter bounded timeout for the background repair (for example, 3 to 5 seconds), or ensure prompt submissions do not wait for the full 10-second background deadline.

- **[P2 / MEDIUM] Timestamped backups accumulate indefinitely without bound**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `bin/shake_io.py:200` and `bin/shake_io.py:245`.
  - **Location**: `bin/shake_io.py:200` and `bin/shake_io.py:245`
  - **Failure scenario**:
    1. Whenever bytes arrive during the rename window (`late > 0`) or if a process terminates between `os.link(path, backup)` and `os.unlink`, a backup named `<session>.jsonl.shake-bak.<timestamp>` remains on disk.
    2. The backup is a hard link holding the pre-rewrite file blocks.
    3. No logic in `shake_io.py`, `register.ts`, or test scripts ever inspects or removes existing `.shake-bak.*` files.
    4. Over multiple compaction cycles or across multiple sessions, large backup files accumulate indefinitely in the project directory, consuming disk storage.
  - **Fix**:
    Implement backup retention pruning in `bin/shake_io.py`. Keep only the latest backup for a given session and unlink older ones, or remove backups older than a retention threshold.

- **[P3 / LOW] Corrupted `last-shake.json` causes unhandled exception misreported as session file corruption**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `bin/shake_io.py:47-53` and `bin/shake_io.py:296-299`.
  - **Location**: `bin/shake_io.py:47-53` and `bin/shake_io.py:296-299`
  - **Failure scenario**:
    1. If `last-shake.json` is empty, truncated, or invalid JSON, `last_shake_since` only catches `FileNotFoundError`.
    2. `json.load(f)` raises `json.JSONDecodeError` (a subclass of `ValueError`).
    3. `main()` catches `ValueError` and outputs `{"status": "refused", "reason": "session file has a line that is not JSON"}` with exit code 3.
    4. This misreports internal metadata corruption as a session file error and triggers the permanent retry loop.
  - **Fix**:
    In `last_shake_since`, catch `(FileNotFoundError, json.JSONDecodeError, KeyError)` and return `None`.

- **[P3 / LOW] Unchecked low-level `os.write` calls risk partial writes**
  - **Confidence**: HIGH
  - **Verification**: verified by reading `bin/shake_io.py:205` and `bin/shake_io.py:215`.
  - **Location**: `bin/shake_io.py:205` and `bin/shake_io.py:215`
  - **Failure scenario**:
    `os.write(fd, buffer)` in POSIX can perform a partial write and return fewer bytes than the length of `buffer`. The return values on line 205 and line 215 are ignored. On large session files, a partial write would silently truncate the rewritten file or cause size assertion failures.
  - **Fix**:
    Use a loop to ensure all bytes are written, or use `os.fdopen(fd, 'wb')` with `f.write()`.

---

## Open questions

- None. All findings are verified with high confidence against the implementation code, tests, and loader specifications.
