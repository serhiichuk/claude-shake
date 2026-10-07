# Verify upstream risk claims for the idle file shake

Date: 2026-10-08. Read-only. No `claude` run, no API spend. Claude Code binary: 2.1.293 (`live-shake/bin/strings.txt`).

Tags:
- **[code]**: read in source (upstream diff, the 2.1.293 binary strings, or our shake scripts).
- **[measured]**: counted or run in this check, or in the saved runs.
- **[upstream-claim]**: stated by an upstream author. I did not reproduce it.
- **[inference]**: my reasoning from the facts above. Not tested.

Sources: `gh` was not logged in and the anonymous API limit was 0, so I read the github.com pages and `.diff` URLs with plain GET (`curl`). Copies are in the session scratchpad (`scratchpad/gh2/`). The scout summary misstates some items. The numbers below come from the pages, not from `scout.md`.

## Verdict

| # | Claim | Applies to the idle file shake |
|---|---|---|
| 1 | Edited history gives a 400 for the latest thinking | UNVERIFIABLE (one case not tested) |
| 2 | Re-truncation mutates the prefix each cycle | APPLIES to native `<persisted-output>` blocks only |
| 3 | Result-only compaction hits a floor | APPLIES |
| 4 | Deleted tool calls cause fabrication | DOES NOT APPLY |
| 5 | A UTF-16 cut leaves a lone surrogate, then every turn gets a 400 | DOES NOT APPLY to our scripts; APPLIES to a TS port and to a preview cut |

## Claim 1: the 400 "thinking blocks in the latest assistant message cannot be modified" (#107)

Upstream facts:
- [upstream-claim] Issue #107, item 4. Claude Code 2.1.282, fast-jev 0.3.0, a Haiku model with extended thinking. After a manual `/compact` that Jev handled ("kept 12/20 messages, no summary"), the first request failed with `invalid_request_error: messages.1.content.19: thinking or redacted_thinking blocks in the latest assistant message cannot be modified`.
- [upstream-claim] Claude Code then logged "server rejected a thinking block; stripping all thinking blocks and retrying", and the retry succeeded. The author only suspects the cause: "a rebuilt message (no `handle`) in the latest assistant turn". The scout's "rebuilt assistant messages cause the 400" is that suspicion, not a finding.

Binary facts (2.1.293):
- [code] The error has its own class. The classifier at offset ~21,771,281 returns `thinking_blocks_modified` for a 400 that matches ``/`?(thinking|redacted_thinking)`?\s+(or\s+`?redacted_thinking`?\s+)?blocks?\s+.{0,60}cannot be modified/i``.
- [code] The recovery matcher `P8r` (~20,109,319) is true for "thinking block" + "cannot be modified", "invalid signature", "signature in thinking block", and two more forms.
- [code] On a match, the retry loop (~23,650,919) strips all thinking blocks and retries once: `retry:thinking-signature-strip`, event `tengu_thinking_signature_strip_retry`. The retry runs only when `resumeIncompleteThinking` is not set. That flag belongs to the max-output-tokens continuation of a cut response, not to `--resume`. If the flag is set, the error goes to the user (`rejected_surfaced`).
- [code] The server reports a prefix mismatch in `input_transformations` as `thinking_dropped` with `reason: prefix_binding_mismatch` and a path `messages.N.content.M` (~23,495,335). Claude Code writes that as a `thinking_drop` attachment row.

Saved runs:
- [measured] The 6 saved streams (e1 to e4, plus 2 repair forks) have 0 failed `result` events, 0 retry or error `system` events, and 0 API-error assistant rows. The 4 `.stderr` files have no "stripping all thinking" line.
- [measured] Each post-shake request wrote one `thinking_drop` row with `reason: prefix_mismatch`, and no 400 occurred:
  - e1: 1 block dropped at message index 5;
  - e2: 2 blocks dropped, at message indexes 5 and 11 (index 11 is the thinking of turn 1's final answer, which follows both shaken results);
  - e3 and its forks: 2 blocks dropped, at message indexes 4 and 9.
- [measured] In every run, the latest assistant message of the post-shake request was a text-only reply (turns 2 and 3 said "ok"). So no run sent a request whose latest assistant message carried thinking after an edited result.

Can a shake of an older user-row tool_result trigger it?
- [measured] The shake does not modify a thinking block. It does not touch assistant rows. Thinking bytes and signatures stay identical (33 of 33 offline, all rows in e1 to e3).
- [inference] At the idle point, a finished turn ends in an assistant message. So every tool_result in the file comes before the latest assistant message. Any shake, of the oldest results or of the newest turn, changes the prefix of that message's thinking. Keeping the newest turn unshaken does not avoid this.
- [measured] For thinking that is not in the latest assistant message, the server drops it (`prefix_mismatch`) and returns 200.
- [unverified] For thinking in the latest assistant message after a changed prefix, the server response is not known. It can be a drop (as for index 11 in e2) or this 400. If it is the 400, 2.1.293 strips all thinking and retries once [code]. The cost is one extra request and the loss of all thinking on the wire, not a broken session.
- [code, ADR-0003] If `CLAUDE_CODE_POLISHED_DEWDROP=block`, Claude Code sends `prefix_mismatch_behavior: error`, and a mismatch returns a 400.
- [inference] If the latest assistant message comes before a shaken result, this happens only mid-turn (a tool loop) or in a session that stopped after a tool_result. A mid-turn shake is outside the design, and the live process does not read the file. In the stopped-session case, the latest thinking and its prefix are unchanged. Only content after the thinking changes, as in a normal tool loop.

Design rules:
1. Never edit an assistant row. Change only `tool_result.content` in user rows.
2. Shake only at the idle point (`prompt.submit` without `e.turnId`).
3. Do not set `CLAUDE_CODE_POLISHED_DEWDROP=block`.
4. Before adoption, run one copy test where the final answer of the last turn has a thinking block. Check the first resumed request for a `thinking_drop` row (pass) or "server rejected a thinking block" in the debug log (the strip-and-retry fallback). This test needs API spend and was not run.

## Claim 2: re-truncation mutates the prefix each cycle (PR #68, PR #77)

Upstream facts:
- [upstream-claim] PR #68 (open): "Re-compacting already-truncated tool results across turns mutates historical messages, invalidating KV prefix caches ... and multiplying token costs by up to 10x." The PR has no measurement for "10x". Its fix `cacheFriendly: true` pins a call when its result text contains `[fast-jev-compaction truncated` [code].
- [upstream-claim] PR #77 (open): treat a result that an earlier round cut as a tombstone. Do not ask Jev to keep it again, and show its original size. The code parses the note with a regex (`truncatedResult`) [code]. The PR cites `190,070 -> 35,598` tokens in 0.9 s from #70.
- [code] On upstream `main`, `truncatedResultText` returns the text unchanged when `text.length <= headChars + 120`, so a second `drop_result` on a cut result is a no-op. The mutation on a later round comes from `drop_call` of a cut pair, which removes the call and the result.

Our scripts:
- [code] `live-shake-src/shake.py` skips a result whose content starts with `[shaken:`, and skips it before the keep window is counted. So our own placeholders are never replaced again.
- [code] `benchmark/shake.py` skips results under 500 characters. Its placeholder (~80 characters plus the path) is under 500, so it is not shaken again. `--keep-tokens` counts only results of 500 characters or more.
- [code] Neither script detects the native `<persisted-output>` placeholder. Claude Code writes that placeholder with a 2,000-character preview (`Qve=2000`), so the block is longer than 500 characters and longer than our note. Both scripts would replace a native placeholder with a second placeholder, and would save a file that holds the placeholder text, not the original output.
- [measured] Native `<persisted-output>` blocks exist in real sessions: 2,084 to 9,101 characters per session in 4 of the 8 large sessions checked (25250090, b0aa92a1, f7e348f1, ac722baf).
- [inference] ADR-0003 recommends that our placeholder use the native `<persisted-output>` form. With that form and the `[shaken:` check, a later shake would re-shake its own placeholders. This is the exact pattern of claim 2.
- [inference] Cost with immutable placeholders: each shake rewrites the cache from its oldest newly shaken result to the end. With a rolling keep window, that is the previous keep window plus the growth since the previous shake, not the full history. ADR-0003 measured one such rewrite: 73,124 cache-write tokens, 0.314 USD against 0.050 USD.

Design rules:
1. A shaken result is a tombstone. Never change it again.
2. Detect both `[shaken:` and `<persisted-output>` (and `<truncated-output>`, which the binary also has), and skip them before the keep window is counted.
3. Never overwrite a saved file that already exists for a `tool_use_id`.
4. Shake rarely and in large batches (ADR-0003 rule 4). Each shake pays one cache rewrite.

## Claim 3: result-only compaction hits a floor (#70)

Upstream facts:
- [upstream-claim] Issue #70, 2 live sessions, Claude Code 2.1.275, 1M-window models, manual `/compact`.
  - Session 1, retained tokens after each Jev round: 36K, 52K, 59K, 74K, 87K.
  - Text share of the input by round: 8%, 10%, 25%, 33%, 44%, 27%. The "drop-all bound" (the most a round can free) fell from 92% to 56%.
  - Session 2, round 4: 82% text; dropping all 6 candidates freed 19.8%, under `minReductionRatio 0.25`. The fallback to the built-in summary turned 47.7K characters of verbatim text into a 10.7K-character paraphrase.
  - After round 6, 54% of the retained user text was machine-generated (`<task-notification>` 76K characters, `/compact` echoes, `<system-reminder>`). Human prompts were 11K.
- [upstream-claim] PR #68 cites hermes-agent PR #116246: freed share 89% to 55% over 32 cycles.
- The scout's "context grew from 190,070 to 35,598 tokens" is wrong. That pair is a reduction, and it is in PR #77, not in #70.

Our data:
- [measured] 8 large session files under `~/.claude/projects` (3.0 to 68.7 MB), with `share2.py` in the session scratchpad.
  - Method: user and assistant rows, not sidechain, deduplicated by uuid, characters of content.
  - Excluded: images, thinking (stored thinking text is near empty), attachment rows, the system prompt, and the tool list.
  - "Shake frees" uses the ADR-0003 rule: keep the newest 64,000 characters of results, shake text results of 500 characters or more, and count a 250-character placeholder.
- [inference] The two `-Users-serhiichuk-Repos-agents` sessions are orchestrator sessions, from their project directory. The role of the frontend sessions is not checked.

| Session | Scope | Chars | Result share | Shake frees | Tool_use input |
|---|---|---|---|---|---|
| agents/25250090 | whole file | 961,445 | 34% | 23% | 22% |
| agents/25250090 | after boundary | 494,261 | 26% | 10% | 22% |
| agents/b0aa92a1 | whole file | 756,546 | 50% | 35% | 20% |
| agents/b0aa92a1 | after boundary | 189,903 | 41% | 4% | 23% |
| next-main/ca6c7f92 | whole file | 3,924,916 | 37% | 31% | 16% |
| 126786/da273fbc | whole file | 2,434,606 | 36% | 28% | 20% |
| 122044/f7e348f1 | whole file | 2,177,098 | 26% | 20% | 12% |
| 125036/ac722baf | whole file | 474,812 | 61% | 38% | 35% |
| 125659/5b460379 | whole file | 1,432,123 | 28% | 17% | 25% |
| agent-usage/8bd8611a | whole file | 566,106 | 22% | 6% | 32% |

- [measured] Over the whole file, tool_result text is 22% to 61% of the characters (6 of 8 sessions are between 26% and 37%). One shake frees 6% to 38%. After the shake, 62% to 94% of the characters remain, and the shake cannot touch them.
- [measured] What remains: assistant text, `tool_use` input (12% to 35%, for example Write bodies and Bash heredocs), human prompts, and machine-generated user text. The machine-generated text (`<task-notification>`, `<system-reminder>`, command echoes) is up to 35% (f7e348f1: 761,546 of 2,177,098).
- [measured] The result share falls in later quarters of the file in 5 of 8 sessions, for example da273fbc 56%, 43%, 24%, 22% and 5b460379 45%, 23%, 23%, 19%. Later work is more dialogue-heavy.
- [inference] A second shake frees only the results that left the keep window since the first shake. The dialogue floor grows on each turn. So repeated shakes free less each round, as #70 reports.
- Token rate is not measured here. ADR-0003 measured about 0.34 tokens per character on one window.

Design rules:
1. The shake does not replace compaction. Keep native compaction (or the compact route) as the backstop when the floor is reached.
2. Shake only when the shakeable part is large, for example over 20% of the context (opinion: the number is not calibrated). Below that, the cache rewrite can cost more than the shake saves.
3. Do not shake assistant `tool_use` input to lower the floor. That edits assistant rows (claim 1).
4. Report the shakeable share before each shake. Never use "freed less than X%" as a failure signal (the #70 lesson).

## Claim 4: deleted tool calls cause fabrication or doubt (#65, #123, PR #83)

Upstream facts:
- [upstream-claim] Issue #65: plugin 0.2.0, Claude Code 2.1.275, `claude-opus-5`, a 2-day session. Compaction went from 333,671 to 47,797 tokens. After it, the model wrote 9 assistant turns in 22 minutes with 0 `tool_use` blocks, and all of them reported fabricated work. `drop_call` removed the `tool_use` and kept the narration with no marker. `drop_result` already left a note.
- [upstream-claim] Issue #123: `keepThreshold 0.3`, 150,111 to 47,552 tokens (kept 17/31 messages). The model treated an earlier correct answer as fabricated. With `keepThreshold 0.15` (150,570 to 68,410 tokens), no misattribution was reported. The issue states that this is not a controlled test, and that the effect of a marker is not verified.
- [upstream-claim] PR #83 measured the shape only, not the behavior:
  - 811k-token session, 407 calls: `drop_call` saved 86.5% of characters, and 2 of 93 narrated turns kept a tool call. `stub_call` saved 64.3%, and 77 of 93 kept one.
  - 256k-token session, 90 calls: 77.7% with 1 of 31, against 59.9% with 27 of 31.
  - The PR says: "Whether the preserved shape stops the fabricated reports is not measured here."

Our shake:
- [code] [measured] It keeps every `tool_use` byte for byte. It keeps the `tool_result` block, its `tool_use_id` and its `is_error`, and changes only `content`. 56 of 56 pairs stayed paired offline, and 0 calls were unpaired.
- [code] The placeholder says what happened and where the output is: `[shaken: original output saved at <path>. Read or Grep that file if you need it.]`. It does not state an outcome.
- [measured] Offline replay: 0 refusals, 0 complaints, and 0 reads of the saved files over 3 messages. The sample is n=2 on one session, so it cannot exclude a rare doubt or fabrication case.

Design rules:
1. Never remove a `tool_use` or a `tool_result` block. Replace only the result content.
2. The placeholder states that the shake removed the output and where the full output is. It must not imply that the call failed or did not happen, and must not certify the result.
3. Keep `is_error` as it is.

## Claim 5: a cut at a UTF-16 code unit leaves a lone surrogate (PR #110, #128)

Upstream facts:
- [upstream-claim] Issue #128: Claude Code 2.1.289, an emoji-heavy session. The 400 came from the Jev API (`Request contains invalid Unicode text`), not from the Anthropic Messages API. The plugin fell back to the built-in summary. The author could not reproduce it. 1 of 868 message texts had a 150-character tail that started on a low surrogate.
- [upstream-claim] PR #110 (merged): `truncatedResultText` cuts with `text.slice(0, headChars)`. The PR says the Messages API "can reject" a lone surrogate (`no low surrogate in string`), and then "the session fails on every turn". The PR gives a code repro of the cut, but no captured API 400. So "400 for every later turn" is a claim, not an observation.
- [code] PR #110 steps the cut back one unit when it splits a pair. PR #132 adds `sliceSurrogateSafe` and replaces escaped lone surrogates in the Jev request body with `�`.

Our scripts:
- [code] Neither script cuts text. Both write a fixed ASCII template plus a path, with no preview. The full original goes to the saved file.
- [code] [measured] Python `json.loads` joins an escaped pair (`😀`) into one code point (U+1F600). Python string slicing works on code points, so a Python cut cannot split a pair from valid JSON.
- [measured] Claude Code writes astral characters as raw 4-byte UTF-8: 225 of 592 session files have them, and 0 files have escaped pairs. 0 of 592 files have a true lone-surrogate escape (two false matches were a literal `\\uD800` in regex text).
- [code] [measured] If a row already holds a lone-surrogate escape, the scripts fail closed:
  - `live-shake-src/shake.py` decodes with strict UTF-8 and re-encodes changed rows (`ensure_ascii=False`, then `.encode("utf-8")`). A lone surrogate raises `UnicodeEncodeError: surrogates not allowed` before the rename. The session stays unchanged. A 0-byte `.shake.tmp` file and any saved files written before the error stay on disk.
  - `benchmark/shake.py` writes with the default UTF-8 encoding and fails the same way before `os.replace`. A partial `.shake-tmp` file stays.
- [code] The native preview is not surrogate-safe. `Qet` in 2.1.293 (~19,176,495) cuts the preview with `e.slice(0, 2000)` on UTF-16 units. It moves the cut back to the last newline only if that newline is past 1,000 units. So a native `<persisted-output>` preview can end on a lone high surrogate.
- [code] The research mod `register.ts` uses `r.text.length` (UTF-16 units) only to count the keep window, and does not cut.

Design rules:
1. If the placeholder has a preview, cut it in Python on code points, or in TS with a surrogate-safe cut (the PR #110 check, or `String.prototype.toWellFormed()`). Never copy the native `Qet` logic.
2. If a preview counts bytes, cut on a UTF-8 character boundary.
3. Fail closed on a lone surrogate. Remove the temp file and any saved files of the failed run on that path.
4. Keep `ensure_ascii=False` for changed rows. The live test measured byte-identical re-serialization with it (ADR-0003). Do not re-serialize unchanged rows.

## Limits

- I did not run Claude Code or the API. The claim 1 case (latest assistant message with thinking after a shaken result) stays untested.
- The scout listed #107's 400 as a fact about rebuilt messages. The issue author only suspects the cause.
- The floor numbers are characters, not tokens, and exclude the system prompt, tools, attachments and images.
- `share2.py`, `streams.py` and `drops.py` are in `/private/tmp/claude-501/-Users-serhiichuk-Repos-agents/160b5937-1b8c-43bc-b814-8a4277280147/scratchpad/tools/`. That directory is temporary.
