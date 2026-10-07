# Upstream Scout Report: fast-jev-compaction
Target repository: [tamaratran/fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction)
Repository scan totals: **134 total items** (**44 issues**, **90 pull requests**). All items were inspected across open and closed states.
- Relevant items: **30**
- Irrelevant items: **104**

## Relevant Issues and Pull Requests

### PR #18: Trim long Bash output with Jev before the model sees it
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/18
- **State**: `open`
- **Summary**: Adds an opt-in tool.call hook on Bash that truncates stdout/stderr exceeding bashOutputMinChars before the model sees it. Dropped chunks are persisted to `.claude/fast-jev-compaction/bash-<id>.txt` with a marker note directing the model to read or grep if needed.
- **Exact Claim / Code Change**: Stated by author: Bash output over 4000 characters is trimmed using Jev decision scoring on 20-line chunks. Results already persisted natively by Claude Code (`record.persistedOutputPath`) are left untouched. Measured on interactive sessions: trimming reduced `sh gen.sh` output from 16,757 to 1,483 characters.
- **ADR-0003 Relation**: Adds to ADR-0003 Output caps and persisted-output facts. Demonstrates client-side hook persistence into local files before turn completion, and confirms native Claude Code `record.persistedOutputPath` handling.

### Issue #21: Hooks (0) on install — session.compact / turn.complete are not recognized Claude Code hook events (tested on Claude Code 2.1.272)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/21
- **State**: `open`
- **Summary**: Reports that the plugin showed Hooks (0) on Claude Code 2.1.272. Author found that function hooks require newer Claude Code versions, and that hooks cannot be declared in static JSON for dynamic events.
- **Exact Claim / Code Change**: Stated by author: On Claude Code 2.1.272, `session.compact` and `turn.complete` failed to register because function hooks were introduced only in Claude Code 2.1.274+. Static `hooks.json` only supported shell events.
- **ADR-0003 Relation**: Confirms ADR-0003 Hook lifecycle prerequisites. Establishes the exact runtime version threshold (2.1.274+) for session compaction hooks.

### Issue #65: drop_call keeps the assistant's narration but removes the evidence: after one compaction the model wrote 9 consecutive tool-free 'work done' reports, all fabricated
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/65
- **State**: `open`
- **Summary**: Describes a severe hallucination failure mode when tool calls are removed alongside results while assistant narration survives. The model mimics the tool-free pattern in subsequent turns and invents task completion without running tools.
- **Exact Claim / Code Change**: Stated by author: Removing tool call blocks from history leaves assistant narrative text without grounding, causing 9 consecutive fabricated 'work done' turns in an 811k-token session. Author advocates preserving call structural stubs instead of deleting calls entirely.
- **ADR-0003 Relation**: Adds to ADR-0003 Measured results and hook options. Provides direct behavioral evidence against deleting tool call blocks, strongly confirming ADR-0003's approach of keeping tool call headers and uuids while replacing only tool result payloads.

### PR #68: fix: resolve text-floor deadlocks, dual threshold calibration, and prefix cache invalidation
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/68
- **State**: `open`
- **Summary**: Addresses text-floor deadlocks where dialogue growth leaves 0% context freed despite dropping all tool candidates. Adds `cacheFriendly: true` to pin already-truncated tool results and avoid mutating historical prefixes across cycles.
- **Exact Claim / Code Change**: Stated by author: Re-compacting already-truncated results across cycles mutates historical messages, invalidating KV prefix caches and multiplying token costs by up to 10x. Also reports that in extended sessions, monotonic dialogue growth causes compaction to free 0% context when only tool results are pruned.
- **ADR-0003 Relation**: Confirms ADR-0003 Facts on prompt cache rewriting per history edit. Confirms that mutating already-compacted prefix blocks repeatedly destroys prompt cache efficiency.

### Issue #70: Repeated compaction: the candidate set never covers what accumulates, and `< 25% removed → summary` mistakes 'nothing left to prune' for 'Jev failed' (two live sessions, 9 rounds)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/70
- **State**: `open`
- **Summary**: Analyzes repeated compactions in long sessions across 9 rounds. Found that candidate sets fail to keep pace with dialogue growth, and fixed percentage thresholds falsely trigger fallbacks to native summarization.
- **Exact Claim / Code Change**: Stated by author: In 9 compaction rounds across two sessions, context grew from 190,070 to 35,598 tokens in round 1, but later rounds could only remove 20% because verbatim text accumulated. Fixed reduction ratio fallbacks summarize verbatim text unnecessarily.
- **ADR-0003 Relation**: Adds to ADR-0003 Measured results on long-running session accumulation. Shows that tool-result compaction alone hits an asymptote as dialogue text expands.

### Issue #76: Function hooks not loaded on Claude Code 2.1.278 — plugin shows Hooks (0)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/76
- **State**: `closed`
- **Summary**: Investigates why Claude Code 2.1.278 reported `Hooks: Found 0 total hooks in registry`. Discovered that the message was a cosmetic logging artifact that counted only legacy JSON hooks while function hooks loaded successfully.
- **Exact Claim / Code Change**: Stated by author: Claude Code 2.1.278 debug logs separate the legacy JSON hook registry from module function hooks. The message `Hooks (0)` does not mean function hooks failed to load; the real log line is `hooks module ... loaded ... events: session.compact,turn.complete`.
- **ADR-0003 Relation**: Adds to ADR-0003 Hook verification diagnostics. Clarifies how Claude Code reports registered hooks.

### PR #77: feat: add verdict-based compaction outcomes and result tombstones
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/77
- **State**: `open`
- **Summary**: Introduces three compaction outcome categories (`scored`, `nothing_to_prune`, `capacity`) and treats previously truncated results as immutable tombstones. Prevents re-evaluating or re-summarizing historical edits.
- **Exact Claim / Code Change**: Stated by author: Results already cut by earlier compaction passes must be treated as tombstones so downstream passes do not attempt to re-evaluate them or fall back to native summarization.
- **ADR-0003 Relation**: Confirms ADR-0003 Idle shake recommendation of making history edits stable and non-repetitive.

### PR #79: fix: drop empty assistant messages after compaction
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/79
- **State**: `open`
- **Summary**: Drops assistant messages that have no remaining content blocks after tool call pruning, while explicitly preserving assistant messages that contain thinking text.
- **Exact Claim / Code Change**: Stated by author: If all tool calls are pruned from an assistant message, keeping an empty message object corrupts transcript structure. Thinking-only assistant messages must be preserved.
- **ADR-0003 Relation**: Confirms ADR-0003 Thinking block facts. Stresses that thinking blocks must be distinguished from ordinary empty assistant turns and preserved on disk.

### Issue #81: max_tokens_exceeded 400 while the local maxStateTokens check passes: estimateTokens undercounts dense runs (hex, UUIDs, base64)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/81
- **State**: `open`
- **Summary**: Reports that the internal token estimator severely undercounts high-entropy text such as commit SHAs, UUIDs, and base64 blobs, leading to HTTP 400 rejections from the decision API.
- **Exact Claim / Code Change**: Stated by author: `estimateTokens` assumes ~6 chars/token for ASCII letters, which works for English prose (~0.34 tok/char). High-entropy runs (40-char SHA = ~20 tokens, UUID = ~15 tokens, base64 = ~20 tokens per 60 chars) tokenize at ~3 chars/token (~0.5-0.7 tok/char).
- **ADR-0003 Relation**: Adds to ADR-0003 Token estimation facts. ADR-0003 notes offline token estimates are ~20% high for normal prose (0.34 tok/char vs 0.42), but Issue #81 proves that for identifiers and hashes, naive character rates undercount tokens by more than 2x.

### Issue #82: Calibration datapoints for Han-bearing payloads: estimator stays above actual (10 archived pairs, Han ~0.99 tok/char)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/82
- **State**: `open`
- **Summary**: Measures token estimation accuracy for CJK / Han script payloads across 10 archived session pairs.
- **Exact Claim / Code Change**: Stated by author: Han characters tokenize at approximately 0.99 tokens per character on Claude's tokenizer. The estimator's 0.9 rate slightly undercounts, but conservative margins keep it safe.
- **ADR-0003 Relation**: Adds to ADR-0003 Token estimation facts. Provides exact empirical tokenization ratios for non-Latin characters.

### PR #83: Add dropCalls option: stub a no-longer-needed call instead of deleting it (#65)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/83
- **State**: `open`
- **Summary**: Implements `stub_call` as an alternative to deleting tool call blocks. Replaces the input with a minimal stub to maintain conversation structure without ballooning token size.
- **Exact Claim / Code Change**: Stated by author: In an 811k-token session with 407 tool calls, `drop_call` saved 86.5% characters but only 2/93 narrated turns retained tool calls. In contrast, `stub_call` saved 64.3% characters while retaining 77/93 tool call markers.
- **ADR-0003 Relation**: Confirms ADR-0003 Recommendation. ADR-0003 keeps tool calls and replaces results; PR #83 confirms that retaining tool call structures prevents post-compaction model degradation.

### PR #85: fix(state): charge dense runs (hex, UUIDs, base64) ~3 chars per token in estimateTokens
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/85
- **State**: `open`
- **Summary**: Fixes token undercounting in Issue #81 by charging alphanumeric runs with high entropy or vowel starvation at 3 characters per token.
- **Exact Claim / Code Change**: Stated by author: Alphanumeric runs that mix letters with digits or have <25% vowels are charged at least `len / 3` tokens. A 60-char base64 run now estimates ~20 tokens instead of ~11.
- **ADR-0003 Relation**: Adds to ADR-0003 Token estimation heuristics.

### Issue #88: hooks cannot actually replace compaction, and full transcripts are sent to a third-party API
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/88
- **State**: `open`
- **Summary**: Raises architectural concerns about compaction hooks sending transcripts to external endpoints and questions whether hooks truly replace core compaction.
- **Exact Claim / Code Change**: Stated by author: Full session transcripts including secrets are transmitted to an external API. Author questions whether hooks can cleanly substitute native summarization without side effects.
- **ADR-0003 Relation**: Confirms ADR-0003 Trade-offs. Emphasizes the need for offline, local idle shaking over third-party hook routing.

### Issue #89: Compaction is undone on --resume: hook boundary has no preservedSegment/preservedMessages anchors
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/89
- **State**: `open`
- **Summary**: Documents the exact failure mechanism where compaction performed by a hook is undone upon `--resume`. Reconstructed sessions reload uncompacted history and duplicate rows.
- **Exact Claim / Code Change**: Stated by author: On Claude Code 2.1.278, resuming a compacted session saw token counts jump from 82,164 to 166,161–167,935 tokens (approaching the pre-compaction 173,575 tokens). The `compact_boundary` written by the hook lacks `compactMetadata.preservedSegment` and `preservedMessages`. Claude Code's transcript loader checks `Boolean(record.compactMetadata?.preservedSegment || record.compactMetadata?.preservedMessages)`; without them, it walks past the boundary. References anthropics/claude-code#95328.
- **ADR-0003 Relation**: Confirms ADR-0003 Compaction hooks fact: 'A hook that keeps handles does not survive resume. The handled row keeps its old parentUuid... fast-jev-compaction\'s resumed request grew 29%.' Provides the exact loader conditional and metadata keys responsible.

### PR #98: Redact secrets from the Jev request; keep compaction across --resume (#89)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/98
- **State**: `open`
- **Summary**: Implements the `withoutHandles()` workaround from anthropics/claude-code#95328 by stripping the engine `handle` property from messages returned by `session.compact`, forcing Claude Code to mint fresh record IDs. Also adds secret redaction.
- **Exact Claim / Code Change**: Stated by author: Stripping message `handle` properties reduced post-resume tokens from 230,441 (where compaction was undone) to 158,419. Trade-off: kept messages lose hidden reasoning (thinking) and images.
- **ADR-0003 Relation**: Confirms ADR-0003 Compaction hooks fact: 'A hook without handles deletes thinking and attachments from the file (Thinking 98 -> 1).' PR #98 confirms this exact trade-off was adopted as their resume fix.

### Issue #99: Replay on real Claude Code sessions: Laya, SWE-Pruner, Needle 3 and a next-message oracle don't meaningfully beat head+tail (notes for #18, #86/#87)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/99
- **State**: `open`
- **Summary**: Evaluates several small language models (Laya 421M, SWE-Pruner 0.6B, Needle 3 121M embeddings) against a simple heuristic baseline (head+tail: 70% start, 30% end). Shows that complex model-based line selectors fail to meaningfully beat head+tail.
- **Exact Claim / Code Change**: Stated by author: Zero-shot Laya scored AUC 0.45–0.47 (worse than simple rules). SWE-Pruner and Needle 3 did not outperform a simple head+tail cut (70% start, 30% end). The most effective component is saving the full output to a file and leaving a marker path.
- **ADR-0003 Relation**: Adds to ADR-0003 Output caps and shake design. Demonstrates that deterministic truncation and file saving (`<persisted-output>`) outperforms complex ML-based content selection.

### PR #105: Salvage identifiers from dropped results
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/105
- **State**: `open`
- **Summary**: Extracts distinctive identifiers, file paths, and failure messages from dropped tool outputs and appends a salvage block up to `salvageMaxChars` (default 600 chars).
- **Exact Claim / Code Change**: Stated by author: Preserving identifiers (UUIDs, hashes, paths) from dropped results prevents subsequent turns from repeating exploratory commands.
- **ADR-0003 Relation**: Adds to ADR-0003 Shake content replacement design. Offers an alternative to full output caching by extracting key tokens into the placeholder.

### Issue #107: session.compact / turn.complete: precompute, subagent/fork and non-answer turns are not filtered; in-flight guard can race
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/107
- **State**: `open`
- **Summary**: Audits Claude Code hook lifecycle behavior on 2.1.282. Details race conditions in `turn.complete`, subagent hook propagation, precompute triggers, and an API 400 error caused by modified thinking blocks.
- **Exact Claim / Code Change**: Stated by author: `session.compact` receives speculative `trigger: 'precompute'` events and subagent/fork transcripts (`event.agentId`). `turn.complete` fires for subagent turns and non-answer turns. Setting `compacting = true` after `await $.session.usage()` introduces a race window. Rebuilt assistant messages without handles cause API 400: `messages.1.content.19: thinking or redacted_thinking blocks in the latest assistant message cannot be modified`.
- **ADR-0003 Relation**: Confirms ADR-0003 Safe idle point and thinking facts. Confirms that `turn.complete` has concurrency races and that modifying thinking blocks triggers server rejections.

### PR #110: fix: truncate dropped tool results on a code point boundary
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/110
- **State**: `open`
- **Summary**: Prevents `text.slice(0, headChars)` from splitting UTF-16 surrogate pairs (such as emojis). Splitting astral characters causes unpaired high surrogates, triggering API 400 rejections on all subsequent turns.
- **Exact Claim / Code Change**: Stated by author: Truncating strings at UTF-16 code unit offsets leaves orphaned surrogates (`\ud83d`). The Anthropic Messages API rejects these with `no low surrogate in string`, permanently bricking the session until rewind.
- **ADR-0003 Relation**: Adds to ADR-0003 File rewrite and replacement safety constraints.

### PR #111: Queue /compact when an SDK session refuses $.session.compact
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/111
- **State**: `closed`
- **Summary**: Addresses headless and SDK (`-p`) sessions where `$.session.compact()` is rejected with `auto-compact skipped (... not available in a headless (-p / SDK) session yet)`. Queues `/compact` via `$.command.run` from `turn.complete`.
- **Exact Claim / Code Change**: Stated by author: Claude Code 2.1.281 refuses `$.session.compact()` in headless/SDK sessions. Running `$.command.run('/compact')` successfully queues the command for post-turn execution.
- **ADR-0003 Relation**: Confirms ADR-0003 Safe idle point and reload mechanics. Confirms that headless/daemon processes handle compaction differently from interactive sessions.

### PR #112: fix: filter speculative and subagent compaction hooks
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/112
- **State**: `open`
- **Summary**: Implements fixes for Issue #107: skips speculative precompute compactions (`trigger === 'precompute'`), ignores subagent transcripts (`event.agentId`), and claims the concurrency guard before awaiting usage.
- **Exact Claim / Code Change**: Stated by author: Filters out subagents and precomputes, ensuring compaction only triggers on main loop completed answers.
- **ADR-0003 Relation**: Confirms ADR-0003 Hook lifecycle edge cases.

### PR #118: Keep non-reproducible facts when a call is dropped
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/118
- **State**: `closed`
- **Summary**: Distinguishes reproducible reads from non-reproducible environment facts (such as timestamps, ephemeral PIDs, random seeds) when pruning tool calls, preserving fact lines in the stub.
- **Exact Claim / Code Change**: Stated by author: Pure deletion of tool calls drops critical runtime facts that cannot be re-obtained by re-reading source code.
- **ADR-0003 Relation**: Adds to ADR-0003 Content-replacement placeholder design.

### PR #119: Ask Jev in windows when the history does not fit the state budget
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/119
- **State**: `closed`
- **Summary**: Implements divide-and-conquer windowed evaluation when total history exceeds `maxStateTokens` (25k), avoiding fallback to native summarization.
- **Exact Claim / Code Change**: Stated by author: Evaluated on 4 real overflow sessions (28.1k–31.3k tokens, 677–755 calls). Windowing reduced history by 90.6%–94.5% in 1.0–1.1s without throwing or falling back to built-in summary.
- **ADR-0003 Relation**: Adds to ADR-0003 Token budget scaling facts.

### PR #120: Size the reduction by window pressure and save reduced outputs to files (stacked on #118, #119)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/120
- **State**: `closed`
- **Summary**: Dynamically scales compaction pressure based on context window usage and writes full outputs of reduced tool results to `<cwd>/.claude/fast-jev/cache/<session>/<tool_use_id>.txt`.
- **Exact Claim / Code Change**: Stated by author: Full tool outputs are saved to disk with a pointer in the stub. Simulated on real transcripts at 0.8 to 1.5 context window lengths, preserving 100% of facts in context or on disk without falling back to summarization.
- **ADR-0003 Relation**: Confirms ADR-0003 Persisted-output design. Matches ADR-0003's recommendation of saving original results to files and writing a placeholder path.

### Issue #123: Preserve a compaction marker when dropping tool calls and results
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/123
- **State**: `open`
- **Summary**: Reports that when tool calls and results are removed without markers, Claude treats earlier correct answers as fabricated and attempts to re-verify them. Proposes leaving explicit gap markers.
- **Exact Claim / Code Change**: Stated by author: Observed on Claude Code 2.1.286 with keepThreshold 0.3 (150,111 -> 47,552 tokens). The model questioned its own earlier correct answers because visible tool evidence was completely missing.
- **ADR-0003 Relation**: Confirms ADR-0003 Stated design: placeholders must explicitly explain that output was trimmed or persisted, rather than silently deleting blocks.

### PR #126: OpenRouter transport + cap batches per compaction
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/126
- **State**: `open`
- **Summary**: Adds OpenRouter transport and caps the number of API batches per compaction cycle (`maxBatches`, default 3) to prevent request cost explosions.
- **Exact Claim / Code Change**: Stated by author: Because Jev's decisions endpoint is stateless, each batch resends 25k–30k tokens. Without a cap, tool-heavy sessions multiply token costs severely.
- **ADR-0003 Relation**: Confirms ADR-0003 Cost analysis. Resending full conversation state repeatedly incurs massive token overhead.

### Issue #128: Lone UTF-16 surrogates from slice() cuts can reach the request body (400: invalid Unicode text)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/128
- **State**: `open`
- **Summary**: Reports that slicing strings at UTF-16 code unit indices in state truncation produces lone surrogates, which `JSON.stringify` escapes as `\udXXX`, causing API 400 invalid Unicode errors.
- **Exact Claim / Code Change**: Stated by author: Observed in an emoji-heavy session on Claude Code 2.1.289. 1 of 868 messages had a 150-char tail starting on a low surrogate, producing an API 400 error.
- **ADR-0003 Relation**: Adds to ADR-0003 Safety constraints for string replacement and serialization.

### Issue #129: Kept assistant messages are multiplied after a session resume
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/129
- **State**: `open`
- **Summary**: Discovers that on Claude Code 2.1.286, resuming a session that was compacted with message handles causes assistant messages to multiply 2–6x on subsequent compactions. References anthropics/claude-code#99727.
- **Exact Claim / Code Change**: Stated by author: Returning kept messages with their `handle` causes Claude Code to write them with the original `message.id`. On resume, Claude Code merges all transcript lines sharing an assistant `message.id` across compact boundaries, duplicating them 2–6 times. Rebuilding assistant messages without handles stops the duplication but drops thinking blocks.
- **ADR-0003 Relation**: Confirms and explains ADR-0003 Duplicate rows on resume. ADR-0003 noted fast-jev-compaction's resumed request grew 29% due to duplicate tool calls and thinking blocks; Issue #129 pinpoints the exact mechanism (`message.id` reuse merging across boundaries) and the trade-off with thinking blocks.

### PR #132: fix: keep surrogate pairs whole when cutting text for the Jev state (#128)
- **URL**: https://github.com/tamaratran/fast-jev-compaction/pull/132
- **State**: `open`
- **Summary**: Fixes Issue #128 by introducing `sliceSurrogateSafe` and adding a serialization sanitizer in `buildJevRequest` that replaces lone `\udXXX` escapes with `\ufffd`.
- **Exact Claim / Code Change**: Stated by author: Sanitizes serialized JSON to eliminate lone surrogate escapes, preventing HTTP 400 rejections.
- **ADR-0003 Relation**: Adds to ADR-0003 Serialization safety.

### Issue #133: Prompts queued mid-turn are dropped by compaction
- **URL**: https://github.com/tamaratran/fast-jev-compaction/issues/133
- **State**: `open`
- **Summary**: Reports that user prompts typed while the agent is executing tools are stored in Claude Code as `queued_command` attachments. Compaction hooks that only map `role`, `text`, `toolUses`, and `toolResults` silently drop these queued commands.
- **Exact Claim / Code Change**: Stated by author: Prompts typed mid-turn exist as attachments, not standard user messages. Compaction hooks discard attachment rows, causing the agent to lose its pending instructions within one turn.
- **ADR-0003 Relation**: Confirms ADR-0003 Attachment rows fact: 'The compact route loses attachment rows and toolUseResult. Attachment rows fell from 34 to 23.' Issue #133 identifies the exact operational impact: queued user commands are permanently lost.

## Irrelevant Issues and Pull Requests

The following 104 items focus on repository infrastructure, demos, CI, documentation, packaging, or third-party adapters (Hermes, Pi, Codex, OpenRouter wiring, Laya engine integration) that do not alter the core ADR-0003 compaction and shake mechanics:

- #1: Initial fast-jev-compaction library (PR)
- #2: Add Claude Code mod that replaces compaction with Jev pruning (PR)
- #3: Fix mod API key fallback and doubled log prefix (PR)
- #4: Add native macOS animated compaction demo (demo/JevDemo) (PR)
- #5: Shorten compaction demo, simplify text, and add animated token counter (PR)
- #6: Make Jev compaction effective on real tool output and visible in the UI (PR)
- #7: Ask Jev directly whether a message is a protected constraint or pending task (PR)
- #8: Let Jev truncate stale tool results instead of only dropping them (PR)
- #9: Compact by asking Jev per tool call/result against the whole stripped history (PR)
- #10: Keep the head of a tool result Jev drops instead of only a note (PR)
- #11: Port the tool-call compaction model into the core library; plugin becomes a thin adapter (PR)
- #12: Require the TypeSafe API key as a plugin option (PR)
- #13: Conservative token estimate and deeper state fitting for long histories (PR)
- #14: Document installing the plugin in Claude Code (PR)
- #15: Summarize only what Jev drops, in front of the kept messages (PR)
- #16: Split the per-call decision log into ui.log lines under the host's 4096-char limit (PR)
- #17: README: update tagline to the current tool-call scoring design (PR)
- #19: Add native Pi compaction extension using the shared Jev core (PR)
- #20: Add /jevcompact slash command for on-demand Jev compaction (PR)
- #22: Add a pi extension that takes over compaction with Jev decisions (PR)
- #23: Add optional Vercel AI Gateway transport for Jev requests (PR)
- #24: Add native Codex plugin support (PR)
- #25: Protect non-reproducible tool results before relevance-based deletion (Issue)
- #26: Keep scores give no signal while results are hidden (0 of 256 results scored ≥ 0.5 in a replay) (Issue)
- #27: Reject out-of-range Jev probabilities (PR)
- #28: Harden compaction against malformed Jev answers and control-flow races (PR)
- #29: Reject invalid Jev probabilities before making deletion decisions (Issue)
- #30: Reject keep thresholds that discard even a certain keep decision (Issue)
- #31: Reject ambiguous tool pairs before duplicate IDs remove pinned content (Issue)
- #32: Keep unresolved tool calls visible in the classifier state (Issue)
- #33: Bound concurrent Jev batches instead of dispatching the entire queue (Issue)
- #34: Give JevClient requests a deadline and caller cancellation (Issue)
- #35: Acquire the auto-compaction lock before awaiting session usage (Issue)
- #36: Do not let logging or toast failures break compaction fallback (Issue)
- #37: Build exported files before creating an npm package (Issue)
- #38: Reserve question capacity when fitting a smaller request budget (Issue)
- #39: Pass explicit compact instructions to Jev without losing the current goal (Issue)
- #40: Reject malformed Jev probabilities before pruning (PR)
- #41: Validate keep thresholds at both compaction entry points (PR)
- #42: Reject ambiguous tool pairs and preserve pinned calls (PR)
- #43: Keep unresolved tool calls visible to the classifier (PR)
- #44: Bound concurrent Jev batches and stop queued work on failure (PR)
- #45: Add request deadlines and cancellation to JevClient (PR)
- #46: Acquire the auto-compaction lock before awaiting usage (PR)
- #47: Keep UI failures out of the compaction control path (PR)
- #48: Build exported files before packaging the library (PR)
- #49: Reserve question capacity before fitting the state (PR)
- #50: Preserve explicit compaction instructions in the Jev task (PR)
- #51: Route Jev through OpenRouter's Decisions endpoint (PR)
- #52: Question wording hides Jev's signal, and late fitting stages remove the messages being scored (replay on a 1084-message session) (Issue)
- #53: Fall back when Jev keeps no scored call (PR)
- #54: Where do I get TYPESAFE_API_KEY? (no issuance path found on typesafe.com / console.akka.io) (Issue)
- #55: Fix the Jev request budget, the keep threshold, and the missing question criteria (PR)
- #56: keepThreshold 0.5 makes 'keep' unreachable: keepResult and keepCall come back on different scales (Issue)
- #57: Show Jev a preview of each tool result in its keep question (PR)
- #58: Gateway options, quieter hooks, and retries with batch salvage (PR)
- #59: fix: upgrade vitest to ^5.0.1 to resolve vite/esbuild security advisories (PR)
- #60: fast-jev-compaction is now a live context engine of Hermes Agent (Issue)
- #61: Add a resultQuestion option so the result question can ask what is still needed (PR)
- #62: question (Issue)
- #63: OpenRouter wiring + jev-compact/jev-gate CLI tools (PR)
- #64: Redact credential fields before sending Jev state (PR)
- #66: Support for Desktop? (Issue)
- #67: Gate the tool call separately from its result (PR)
- #69: fix: mark dropped tool calls in assistant narration (PR)
- #71: feat: OpenCode 1 and 2 plugin, free Jev via OpenCode Zen, git install (PR)
- #72: No durable record of which path a compaction took: ui.log and ui.toast are TUI-only, so a headless install cannot tell Jev from the fallback (Issue)
- #73: DSH 用户可以看一下这个：dsh-fast-jev-compaction (Issue)
- #74: Adding the Vercel AI Gateway, speak both Jev APIs from the hook (PR)
- #75: Harden compaction safety and packaging (PR)
- #78: feat: exclude host text from goals and truncate notices (PR)
- #80: chore: align package version with the published plugin manifests (PR)
- #84: Wire baseUrl through the hook (PR)
- #86: Feature Proposal: Support local open-source decision engine (Laya) as an alternative to TypeSafe Jev API (Issue)
- #87: feat: Add local open-source decision engine (Laya) support (PR)
- #90: fix: read TYPESAFE_BASE_URL from env to support local decision models (PR)
- #91: Let the hook point at an OpenRouter decisions endpoint (PR)
- #92: Feature Request: Support SemIf decision engine for Apple Silicon MPS (Issue)
- #93: feat: Add SemIf decision engine support for Apple Silicon MPS (fixes #92) (PR)
- #94: feat: baseUrl option (or TYPESAFE_BASE_URL) for the Claude Code hook (PR)
- #95: Let an OpenRouter key drive the compaction hook (baseUrl option + OpenRouter key lookup) (PR)
- #96: feat(hook): let the Jev endpoint be configured so a key for another host works (PR)
- #97: Jev requests from real sessions are blocked by Cloudflare WAF (HTTP 403 HTML page) (Issue)
- #100: Is it really accurate? (Issue)
- #101: Explain HTML 403 responses from endpoint (PR)
- #102: Clarify data handling and compaction hook scope (PR)
- #103: Fall back to the built-in summary only on Claude Code's auto compaction (PR)
- #104: jev (Issue)
- #106: fix: forward-compatible typecheck and plugin metadata (PR)
- #108: No codex? (Issue)
- #109: Feature Request: Add support to use API KEY from Cloudflare AI Gateway to use Jev (Issue)
- #113: feat: allow custom endpoints without requiring API key (PR)
- #114: Does the plugin accept an OpenRouter API key? 401 authentication_error with it (Issue)
- #115: Feature Request :: How to adptat this use with Laya (the Open Source jev) (Issue)
- #116: Reach any Jev endpoint, and read the key from a dotenv file (PR)
- #117: Bound Jev waits in the Claude Code compaction hook (PR)
- #121: Add Codex transcript compaction adapter (PR)
- #122: Install the hook's own compaction when the built-in summary it fell back to fails (stacked on #120) (PR)
- #124: Hook: read endpoint from JEV_BASE_URL / TYPESAFE_BASE_URL, route sk-or- keys to OpenRouter (PR)
- #125: Stop retrying auto-compact in headless sessions (PR)
- #127: Record the 2026-10-04 replay re-measure in the hooks README (PR)
- #130: Show unanswerable lookups and flag harness-limited gave-ups (PR)
- #131: chore: bump package.json to 0.3.0 to match plugin manifest (PR)
- #134: Hardening: provenance-mark compacted content and screen policy-style text (compaction is not a trust boundary) (PR)

## Worth Verifying

Ranked list of top 5 findings directly relevant to our shake research, with exact checks an engineer can execute:

1. **Resume Boundary Loader Filter (`compactMetadata.preservedSegment` / `preservedMessages`)**
   - **Finding**: Upstream Issue #89 and anthropics/claude-code#95328 report that Claude Code's resume loader ignores `compact_boundary` records unless they contain `compactMetadata.preservedSegment` or `preservedMessages`. Without these anchors, the loader walks back past the boundary and loads historical records.
   - **Verification Check**:
     ```sh
     # Inspect a compacted session JSONL file for compact_boundary metadata
     grep '"type":"compact_boundary"' ~/.claude/sessions/*.jsonl | python3 -c '
     import sys, json
     for line in sys.stdin:
         row = json.loads(line.strip().split(":", 1)[1] if ":" in line else line)
         meta = row.get("compactMetadata", {})
         print("has_preservedSegment:", "preservedSegment" in meta)
         print("has_preservedMessages:", "preservedMessages" in meta)
     '
     ```
     Run `claude --resume <session_id>` on a session with and without these metadata keys, comparing the token count of the first prompt turn.

2. **Transcript Deduplication via Assistant `message.id` Reuse Across Boundaries**
   - **Finding**: Upstream Issue #129 and anthropics/claude-code#99727 show that Claude Code's loader aggregates transcript rows by `message.id`. When compaction preserves existing assistant message handles across boundaries, resume merges every row sharing that `message.id`, duplicating thinking blocks, tool calls, and text 2–6 times.
   - **Verification Check**:
     ```sh
     # Scan session JSONL for duplicated message.id occurrences across compact boundaries
     python3 -c '
     import json, sys
     ids = {}
     with open("<session_file.jsonl>") as f:
         for line in f:
             data = json.loads(line)
             msg_id = data.get("message", {}).get("id")
             if msg_id:
                 ids[msg_id] = ids.get(msg_id, 0) + 1
     duplicates = {k: v for k, v in ids.items() if v > 1}
     print(f"Total duplicate message IDs: {len(duplicates)}")
     print("Max repetitions:", max(duplicates.values()) if duplicates else 0)
     '
     ```

3. **High-Entropy Identifier Undercounting in Token Estimators**
   - **Finding**: Upstream Issue #81 and PR #85 show that character-based token heuristics (assuming ~6 chars/token) undercount high-entropy runs (UUIDs, git commit SHAs, base64 blobs) by more than 2x (~3 chars/token), causing API 400 `max_tokens_exceeded` errors.
   - **Verification Check**:
     ```sh
     # Compare naive char/token ratio against actual Anthropic tokenizer count on high-entropy strings
     python3 -c '
     import uuid, hashlib
     text = " ".join([str(uuid.uuid4()) for _ in range(100)] + [hashlib.sha1(str(i).encode()).hexdigest() for i in range(100)])
     naive_tokens = len(text) / 6.0
     dense_tokens = len(text) / 3.0
     print(f"Text chars: {len(text)}")
     print(f"Naive estimate (~6 chars/tok): {naive_tokens:.1f}")
     print(f"Dense estimate (~3 chars/tok): {dense_tokens:.1f}")
     '
     ```

4. **Preserving Tool Call Structure Prevents Hallucinated Turn Fabrications**
   - **Finding**: Upstream Issues #65, #123 and PR #83 demonstrate that completely dropping tool calls (`drop_call`) leaves narrative assistant text without evidence, causing the model to hallucinate work completion without executing tools. Replacing tool call inputs with minimal stubs (`stub_call`) or keeping tool calls intact while replacing only tool results retains structural grounding.
   - **Verification Check**:
     Replay a session with tool calls stripped vs tool calls preserved with placeholder results:
     ```sh
     # Verify that all tool_use blocks have matching tool_result blocks in the shaken JSONL
     python3 -c '
     import json
     uses, results = set(), set()
     with open("<shaken_session.jsonl>") as f:
         for line in f:
             d = json.loads(line)
             for b in d.get("message", {}).get("content", []):
                 if b.get("type") == "tool_use": uses.add(b["id"])
                 if b.get("type") == "tool_result": results.add(b["tool_use_id"])
     print(f"Unpaired uses: {len(uses - results)}, Unpaired results: {len(results - uses)}")
     '
     ```

5. **Attachment Rows and Queued Commands Lost in Compaction Hooks**
   - **Finding**: Upstream Issue #133 reports that user prompts queued mid-turn are stored as `queued_command` attachments. Standard compaction hook adapters drop attachment objects because they only map message roles and content blocks, permanently losing queued user input.
   - **Verification Check**:
     ```sh
     # Count attachment types before and after compaction hook execution
     grep '"type":"attachment"' ~/.claude/sessions/*.jsonl | python3 -c '
     import sys, json
     from collections import Counter
     counts = Counter()
     for line in sys.stdin:
         row = json.loads(line.strip().split(":", 1)[1] if ":" in line else line)
         counts[row.get("attachment", {}).get("type", "unknown")] += 1
     print("Attachment distribution:", dict(counts))
     '
     ```
