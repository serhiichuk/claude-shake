# verify-mod-api.md: upstream mod API claims against Claude Code 2.1.292/2.1.293

Date: 2026-10-08. Read-only research. No `claude` run, no API spend. No edit except this file.

Tags:
- **[types]**: read in the generated mod types. 2.1.292: `micro-compaction-evidence/types-2.1.292.d.ts`. 2.1.293: `/private/tmp/claude-501/-Users-serhiichuk-Repos-agents/25250090-c99b-4ed8-800a-070cc842dc8f/scratchpad/live-shake/mod/.claude-plugin/types/claude-code/index.d.ts`. The 2.1.293 diff against 2.1.292 is 87 lines and touches only `tool.register` (`isDeferred`) and the test kit (`mock.session`). Nothing below changed between the two versions.
- **[code]**: read in the 2.1.293 binary strings (`.../live-shake/bin/strings.txt`, offsets given as `@N`), or in the upstream plugin diff.
- **[upstream-claim]**: stated in the upstream PR or issue text, not checked here.
- **[inference]**: my conclusion from the facts above, not observed.

Sources for the upstream items: `gh` has no login on this machine and the REST API returned HTTP 403 (rate limit). I read the public pages and `.diff` files from github.com instead (copies in this session's scratchpad `gh/`).
- PR #111: closed by its author on 2026-10-02 without merge.
- PR #112: open.
- Issue #107: open. Tested on Claude Code 2.1.282.

## Verdicts

| Claim | Verdict on 2.1.293 |
|---|---|
| 1a. `$.session.compact()` is refused in a headless (-p / SDK) session | CONFIRMED |
| 1b. `$.command.run` queues `/compact` to run after the turn | CONFIRMED |
| 2a. `session.compact` gets `trigger: 'precompute'` dispatches | CONFIRMED |
| 2b. `session.compact` gets subagent and fork transcripts (`agentId`) | CONFIRMED |
| 2c. `turn.complete` fires for subagent turns and non-answer turns | CONFIRMED |
| 2d. The guard set after `await $.session.usage()` can race | CONFIRMED (plugin bug, not an API fact) |
| Our report: "A mod cannot type it: no op runs a slash command" | REFUTED |
| Our report: "No mod API reloads history" | Still true for a direct op; a reload through `/resume` is possible in the TUI (see b) |

## (a) Does an op run a slash command?

Yes. `$.command.run` exists in 2.1.292 and 2.1.293.

- **Signature.** [types] `command.run: EventCalls['command']['run']`, with input `CommandRunArgs = { command: string; args?: string }` and result `Promise<CommandRunResult>` (`{ text?, context?, exitCode?, ref? }`). `command` is the name without the slash. PR #111 calls it as `$.command.run({ command: 'compact' })`, not with `'/compact'`.
- **Doc text.** [types] "Runs a slash command as if the person typed `/command args`: the event `command.run`, queued and run once the session is idle. It runs through every hook but the calling one with `e.origin` `{ kind: 'plugin', name }`, its lines in the transcript. Rejects an unknown name, and inside a hook the turn is waiting on."
- **Implementation.** [code] `WCo` @22648854:
  1. It rejects `"<plugin>: $.command.run: no command named /<name> in this session"` if the name is not in the host's `commands()` list and no plugin registered it.
  2. It builds the text `/<name> <args>` and logs `$.command.run (<plugin>): <n> chars queued`.
  3. It puts the text on the input queue: `Ik({agentId, mode:"prompt", value, uuid, priority:"later", origin:{kind:"plugin", name}})`.
  4. The promise settles when the queued command passes `command.run`. It fails with "the command was removed from the queue before it ran" or "the command left the queue as text for the model; it did not run" (@21350305).
- **Limit 1: refused inside a hook that holds the turn.** [code] The host check for `command.run` (@23166464) reads `turnHeld`. Inside a `prompt.submit` hook, `turnHeld` is `"prompt.submit"` (`K1e` → `eWo` → `Rpe`, @23157122 and @23172679). The call then fails with "called from a prompt.submit hook, it would wait on the turn this hook is holding; run it from a later event (turn.complete)". The same rule refuses it from `tool.call`, `agent.spawn`, `command.run` and the other events in `C9t`. It is allowed from `turn.complete`.
- **Limit 2: the same check refuses `$.session.compact()` from `prompt.submit`.** [code] The `session.compact` host check (@23163917) returns "called from a <event> hook, it would compact under the turn this hook is holding; call it from a later event (turn.complete)". ADR-0003 lists this case as untested. It is refused.
- **Limit 3: headless has a smaller command list.** [code] A headless session keeps only commands that pass `Pxe` (@21260926): `type === "prompt"` without `disableNonInteractive`, or `type === "local"` with `supportsNonInteractive`. No `local-jsx` command passes.

## (b) Can a mod run `/resume <same id>` to load the shaken file?

- **`/resume` is `local-jsx`.** [code] `{type:"local-jsx", name:"resume", aliases:["continue"], argumentHint:"[conversation id or search term]"}` @22014784. It has no `supportsNonInteractive`.
- **Headless (-p, stream-json): no.** [code]
  - `/resume` fails `Pxe`, so it is not in the headless command list. `$.command.run({ command: 'resume' })` rejects with "no command named /resume in this session". [inference from the filter; not run]
  - If the text arrives another way, `processSlashCommand` stops it: `if(n.type==="local-jsx"&&o.options.isNonInteractiveSession) return ... "cmd_local_jsx_headless"` @43038170.
- **TUI: the path exists end to end in the code.**
  1. `$.command.run({ command: 'resume', args: sessionId })` queues `/resume <id>` with priority `later`. [code]
  2. The REPL runs a queued `local-jsx` command through the same branch as a typed one. [code] @43038170. I found no check that refuses a plugin origin there. [inference: I searched for `origin.kind==="plugin"` guards and found 3 unrelated ones]
  3. The `/resume` `call` (@53698807) checks that the argument is a session UUID (`Xt(u)`). It finds the log in the project list, or loads it by id from disk (`nve`). Then it calls `F(id, log, "slash_command_session_id")`. [code]
  4. `F` first asks `y8` for a holder. `y8` (@27415091) ignores holders of kind `"interactive"`, so the current TUI process does not block its own id. A background-job holder makes `/resume` print a "running in the background" message instead. [code]
  5. `F` calls `context.resume(...)`, the REPL `resume` handler (@43524800). It replaces the transcript with the loaded messages. It has a same-id branch: `_o!==xo` skips only the read-file-cache reset, and `Co` skips the permission-mode restore. [code]
- **The refusal rule decides where the call goes.** [code] A `prompt.submit` hook cannot queue `/resume` (limit 1). `turn.complete` can.
- **Possible sequence (opinion, not tested):**
  1. The `prompt.submit` hook (no `e.turnId`) shakes the file at idle, as ADR-0003 recommends.
  2. That turn still runs on the unshaken history in memory.
  3. The `turn.complete` hook for the main loop (`!e.agentId && e.reason === 'answer'`) calls `void $.command.run({ command: 'resume', args: await $.session.id() })`.
  4. When the session is idle, `/resume` reloads the shaken file. The next prompt uses the smaller history.
- **Open risks.** [unverified]
  - The `/resume` read can run before the 100 ms write queue writes the last rows of the turn. I did not find a flush before the read.
  - A resume fires `session.end` with reason `resume` ([types] `ExitReason`) and the classic resume hooks (`uSt(L,"resume",…)`). Mods may reload.
  - The resume shows a notice in the transcript.
  - Nothing here was run. A TUI test in a trusted directory must confirm it.

## (c) Is `$.session.compact()` still refused in -p / SDK sessions in 2.1.293?

Yes. [code] The headless host object sets `compact:()=>Promise.reject(Error("not available in a headless (-p / SDK) session yet: compaction here runs inside a turn (a /compact prompt); catch it and carry on"))` @37944187. The types do not mention this refusal. [types]

How this fits the live-shake test, which ran `/compact shake` in `claude -p --input-format stream-json`:
- That test sent the slash command `/compact`, not the op `$.session.compact()`. [inference from live-shake.md]
- `/compact` is `{type:"local", supportsNonInteractive:true}` @21981575. It passes `Pxe` and runs in headless. [code]
- The command raises the `session.compact` event with trigger `manual`, so the mod's hook ran. This matches PR #111: a queued `/compact` "raises the same session.compact event". [code] [upstream-claim]
- The live-shake report says "`$.session.compact()` with a hook: works in process". That wording is inexact. The event worked; the op is refused in that mode. [inference]

## (d) Do `prompt.submit` events arrive for subagents, forks or precompute?

- **No `agentId` field.** [types] `PromptSubmitInput` has `text`, `attachments?`, `context?`, `turnId?`, `wait` and `origin`, and no `agentId`. The engine builds the payload as `{text, wait, attachments?, origin, turnId?}` @29061217. [code]
- **Precompute is a `session.compact` trigger only.** [types] `SessionCompactTrigger = 'manual' | 'auto' | 'plugin' | 'precompute'`. It does not touch `prompt.submit`.
- **Dispatch site.** [code] `prompt.submit` runs from the input pipeline `imn` (@29061975), the path a typed, queued or SDK prompt takes. A subagent or fork starts through `agent.spawn` and its loop raises `turn.step` and `turn.complete`, not `prompt.submit`. [inference] I did not check in-process teammates.
- **What the shake hook must filter instead.** [types] [inference]
  - `e.turnId` set: the prompt was typed over a running turn or delivered into one. Skip it.
  - `e.origin.kind`: `task-notification`, `peer`, `plugin`, `scheduled-trigger` and others also arrive at idle without `turnId`. They are still idle points. Shake on them only if that is intended.
  - A headless session fires it for stream-json user messages too ([measured] in live-shake.md).

## (e) Claim 2 on 2.1.293

- **2a precompute.** [types] The trigger exists, and "`precompute` is the one dispatch that installs nothing". [code] The precompute path dispatches `session.compact` with `trigger:"precompute"` and `agentId: w.agentId` @23419735.
- **2b subagent and fork transcripts.** [types] `SessionCompactInput.agentId`: "The id of the loop compacting, for a subagent's or a fork's own transcript; absent for the main conversation." [code] The precompute dispatch above passes it.
- **2c `turn.complete`.** [types]
  - `TurnCompleteFields.agentId`: "Every hook sees a subagent's turn".
  - `TurnCompleteReason = 'answer' | 'aborted' | 'refusal' | 'error'`.
- **2d race.** [code] In the upstream plugin before PR #112, `turn.complete` checks `compacting`, then awaits `$.session.usage()`, then sets `compacting = true`. Two dispatches that overlap across that `await` both pass the check. Its `finally` also clears a guard that another dispatch holds. This is a bug in the plugin, not an engine fact. Overlapping `turn.complete` dispatches (for example, a subagent and the main loop) are possible. [inference from 2c]
- **Not checked:** issue #107 item 4 (HTTP 400 on a modified thinking block, then a retry without thinking). [upstream-claim] It matches ADR-0003: a history edit loses thinking.

## Corrections for our documents (opinion)

- live-shake.md §3 and ADR-0003: replace "A mod cannot type it: no op runs a slash command" with: "`$.command.run` queues a slash command. It is refused inside `prompt.submit`. In the TUI it can queue `/resume <id>` from `turn.complete`. In -p, `/resume` is not available."
- ADR-0003: replace "`$.session.compact()` from inside `prompt.submit` was not tested" with "refused by the host check (`turnHeld`); call it from `turn.complete` (TUI only; headless refuses the op)".
- ADR-0003 open checks: the `/resume <same id>` TUI test can use a mod (`turn.complete` → `$.command.run`) instead of a person typing it. It still needs a trusted directory.
