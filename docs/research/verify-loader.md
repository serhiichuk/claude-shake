# verify-loader.md: upstream claims about the Claude Code transcript loader

Date: 2026-10-08. Binary: Claude Code 2.1.293 (`claude --version`, `~/.local/bin/claude` -> `versions/2.1.293`). The strings file has `VERSION:"2.1.293"`. No `claude` prompt ran. No API call was made.

Tags:
- **[code]**: read in the 2.1.293 minified code (strings file, byte offsets given as `@N`).
- **[disk]**: read in local session JSONL files (structure only).
- **[upstream-claim]**: stated in an upstream issue or PR, not checked in code.
- **[inference]**: my reasoning from code facts. Not measured.

Sources read:
- tamaratran/fast-jev-compaction #89, #129, PR #98 (page and `.diff`), anthropics/claude-code #95328 (body and 2 comments), #99727. `gh` is not authenticated and the REST API was rate-limited, so I read the github.com HTML pages with GET.
- Strings file: `/private/tmp/claude-501/-Users-serhiichuk-Repos-agents/25250090-c99b-4ed8-800a-070cc842dc8f/scratchpad/live-shake/bin/strings.txt`.

## Verdict

- **Claim 1 (anchors gate the boundary): REFUTED as worded. A true part remains.**
  - The expression exists verbatim, but in that function a boundary *without* anchors is a hard cut, not a pass-through. [code]
  - The real gate is in `g1r`: for files of 5 MiB or less, the loader deletes pre-boundary rows only if some boundary carries anchors. Without anchors, the old rows stay in the row map. The walk then reaches them through stale `parentUuid` links and through the `message.id` recovery. [code]
  - Above 5 MiB, a boundary without anchors drops every earlier row. [code]
- **Claim 2 (`message.id` gathering across boundaries): CONFIRMED.** `S1r` collects every assistant row in the whole map with the same `message.id`, and the tool_result rows under them. It has no boundary check. [code]
- **(c) Anchors for a handle-keeping hook:** a `session.compact` hook cannot write anchors. The hook path clears them on purpose. A file repair could add `preservedMessages` to the boundary row, and the loader code would then prune the originals in memory. That route is not measured. It does not get back the attachment rows that the hook route loses. [code] [inference]
- **(d) Cause 2:** yes. `S1r` explains it fully. [code]
- **(e) Idle file shake without a boundary:** not affected, if the shake keeps the byte form of each line and the session has no hook-kept copies. Four edge cases are listed below. [code] [inference]

## Claim 1 in detail

### The quoted expression

[code] `@14579702`, module that exports `F_e as SKIP_PRECOMPACT_THRESHOLD`:

```js
function ie(e){try{let n=JSON.parse(e);if(n.type!=="system"||n.subtype!=="compact_boundary")return null;
return{hasPreservedSegment:Boolean(n.compactMetadata?.preservedSegment||n.compactMetadata?.preservedMessages)}}catch{return null}}
```

Its user, in the byte pre-scan `V_o`:

```js
let p=ie(n.toString("utf-8",a,c));if(p?.hasPreservedSegment)e.hasPreservedSegment=!0;
else if(p)e.out.len=0,e.boundaryStartOffset=e.bufFileOff+a,e.hasPreservedSegment=!1,...
```

- If a boundary has no anchors, `e.out.len=0` discards all bytes before it. If it has anchors, the bytes are kept, because the preserved rows sit before the boundary. [code]
- In 2.1.293 the only caller of `V_o` is `Sno`, the PR-attribution prompt counter (`@21643333`). It is not the resume loader. [code]
- The issue cites 2.1.278. I could not read 2.1.278. [upstream-claim]

### The resume loader (`Pie`, alias `loadTranscriptFile`)

[code] `@25465439`. The resume path calls `Pie(...)` and then `MSt(map, leaf)` on the returned row map (`@25409000`, `@25433982`, `@25471254`).

1. **Size gate.** `let b=Le(process.env.CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP)` and `if(!b&&size>F_e)` with `F_e=5242880`. Above 5 MiB the loader uses the byte scanner `nOn`. Otherwise it parses every line into one map. [code]
2. **Above 5 MiB (`nOn`, `@25440213`).** On a boundary without anchors it clears all buffered slots (`no.add(ur),Qe.length=0,...`). In pass 2, `if(no.has(Pi))r()` calls `dropPreBoundaryEntries:()=>{n.clear(),Gt.clear(),Vt.clear(),oo.clear()}`. The cut is hard. [code]
3. **5 MiB or less.** Every row goes into the map. Then `finish` runs `g1r` (`@25395777`):

```js
function g1r(e){...for(let he of e.values()){...if(Rs(he)){s=h;let _e=he.compactMetadata;
if(_e?.preservedMessages||_e?.preservedSegment)n=_e,r=h}h++}if(!n)return; ...
let Y=[];for(let[he]of e){let _e=g.get(he);if(_e!==void 0&&_e<s&&!q.has(he))Y.push(he)}for(let he of Y)e.delete(he); ...
```

   - `if(!n)return`: if no boundary in the file has anchors, nothing is deleted. [code]
   - If the last boundary has anchors, `g1r` relinks the listed rows from `anchorUuid`, zeroes their `usage`, and deletes every unlisted row before the last boundary. [code]
   - If an earlier boundary has anchors but the last one does not, `g1r` deletes every row before the last boundary and relinks nothing. [code]
4. **Chain walk (`MSt`, `@25397619`).** It walks `parentUuid` from the leaf. It stops at a row with `parentUuid` null. If a parent is missing, `k1r` picks the newest row up to 5 s older (`tengu_chain_timestamp_fallback`). Then it calls `S1r` (recovery by `message.id`) and `y1r` (children that are not user or assistant rows). [code]
5. **Boundary rows have `parentUuid` null** and a `logicalParentUuid`. This holds for both native and hook boundaries in `-Users-serhiichuk-Repos-agents-tmp-shake-sandbox-cwd/822f8ec0…jsonl`. [disk]

Result: for files of 5 MiB or less, a boundary without anchors stops the walk only by its null parent. One stale `parentUuid` (Cause 1) or one shared `message.id` (Cause 2) brings the old rows back. anthropics/claude-code#95328 describes exactly this, and it matches the code. The one-line summary in #89 does not. [code] [upstream-claim]

## Claim 2 in detail

[code] `S1r`, `@25400572`:

```js
for(let Ft of e.values())if(Ft.type==="assistant"&&Ft.message.id){let Ut=h.get(Ft.message.id);if(Ut)Ut.push(Ft);else h.set(Ft.message.id,[Ft])}
else if(Ft.type==="user"&&hM(Ft.message?.content,"tool_result"))w.push(Ft);
...
for(let Ft of s){let Ut=Ft.message.id;...let Ht=h.get(Ut)??[Ft],...Vt=Ht.filter((Xn)=>!r.has(Xn.uuid)),...
for(let Xn of Ht)for(let no of b.get(Xn.uuid)??[]){...nn.push(no)...}
```

- `e` is the whole loaded map, not the chain. `h` groups all assistant rows by `message.id`. For each assistant row on the chain, every same-id row not on the chain is recovered (`Vt`), with the tool_result rows whose parent is one of them (`b`). [code]
- There is no `compact_boundary` test in `S1r`. Only rows that `g1r` or `nOn` removed from the map are out of reach. [code]
- A second path recovers tool_result rows by `tool_use_id` (map `he`, event `tengu_chain_tool_result_recovered_by_call_id`). The flag `tengu_foamy_spring` gates it, and `Np()` returns `true` when the flag is unread or unset. [code]
- The telemetry name is `tengu_chain_parallel_tr_recovered`, so the purpose is to recover parallel tool calls split over rows. [code]
- The 2-6x factor follows from one extra row per kept message per compaction. I did not find the step that merges same-id rows into one API message. [inference] [upstream-claim]

## (b) Anchor shape and native writers

- **Shape.** [code] Zod schema `Sa` (`@37250818` area): `{anchorUuid: string, uuids: string[], allUuids?: string[]}`. The writer `hqe` (`@23371930`):

```js
function hqe(e,n,r,s=r){let g=r.map((b)=>b.uuid),h=KQe([...r],s).map((b)=>b.uuid);if(g.length===0)return e;
return{...e,compactMetadata:{...e.compactMetadata,...h.length>0&&{preservedSegment:{headUuid:h[0],anchorUuid:n,tailUuid:h.at(-1)}},
preservedMessages:{anchorUuid:n,uuids:h,allUuids:g}}}}
```

- **The SDK form** uses snake case: `preserved_segment {head_uuid, anchor_uuid, tail_uuid}` and `preserved_messages {anchor_uuid, uuids, all_uuids}` (`@28543234`). [code]
- **Native writers.** [code]
  - The reactive/auto compaction path calls `hqe(Ie, n.summaryMessages.at(-1).uuid, Ne, r)` (`@23336203`). The anchor is the last summary message.
  - Partial compaction calls `hqe(zn, mo, Ie, e)` (`@23383122`). The anchor is the last summary message for `up_to`, else the boundary row itself.
  - `hqe` returns the boundary unchanged when nothing is kept.
- **The hook path removes anchors.** [code] `zKr` (`tengu_compact_replaced_by_hook`, `@23339012`):

```js
let he=w!==void 0&&Rs(w)?{...w,compactMetadata:{...w.compactMetadata,preservedSegment:void 0,preservedMessages:void 0,preCompactArtifactReadVersions:void 0}}:vW(h,Y,r.at(-1)?.uuid);
... let Se={boundaryMarker:he,summaryMessages:[],replacement:n,messagesToKeep:[],...}
```

- **On disk, native `uuids` name the original rows before the boundary, in place.** They are not re-written. [disk]
  - `822f8ec0…` boundary at line 2412: 6 uuids at lines 2392-2397 (assistant, assistant, attachment, attachment, system, system). The anchor is the summary row at line 2413.
  - A partial compaction in another project: 1,189 uuids from line 3 on. The anchor is the boundary itself.
  - Each listed uuid occurs once in the file.

## (c) Can a hook or a file repair write anchors?

**A `session.compact` hook: no.** [code]
- `SessionCompactResult` in the 2.1.292 mod types has no `compactMetadata` field. A search for `preserved` and `compactMetadata` in `types-2.1.292.d.ts` found nothing.
- `zKr` clears both anchors even when core compaction ran first.

**A file repair: possible, not measured.** One way, from the code:
1. Edit the hook's boundary row (the last boundary). Add `compactMetadata.preservedMessages = {anchorUuid: <boundary uuid>, uuids: [<post-boundary rows in order>]}`.
2. On load, `g1r` relinks the listed rows from the anchor. It deletes every unlisted row before the boundary from the map. [code]
3. `S1r` then cannot find the originals, so no duplicates load. [inference]

What this keeps and loses:
- **Thinking: kept.** The copies that the hook wrote with handles keep their thinking blocks (live-shake e3: thinking rows on disk 2 of 2). [inference from measured]
- **Attachments: not restored.** The hook copies lack the attachment rows (measured 34 -> 23). `g1r` deletes the pre-boundary attachment rows from the map unless they are listed. Listing them would place them in the chain in list order. That is untested. [code] [inference]
- **No physical deletion below 5 MiB.** The originals stay in the file, unlike the measured repair. At 5 MiB or more, the engine GC `performCompactTranscript` (`F5o=5242880`) and `NXe` delete unlisted pre-boundary rows from the file, as for a native compaction. [code]

Failure modes. Each one loads the full old history again: [code]
- A listed uuid is missing from the map: `tengu_relink_walk_broken`, and `return` comes before the delete.
- The anchored boundary is not the last boundary: no relink, and all earlier rows are deleted.
- Above 5 MiB: a duplicate uuid line (`En`), or an anchor before the boundary that is not listed, gives `tengu_transcript_preserved_dispatch` `fallback_all`.
- `oAo` (interrupted-turn resume) checks that `anchorUuid` is the compact summary row. A hook boundary has no summary row, so that feature returns `kept_rows_not_listed`. The effect is a missed resume prefill, not data loss. [code] [inference]

Opinion: compared with the measured repair (relink, then drop the pre-boundary rows), anchors give the same loaded result and keep the rows on disk for rewind and fork. Neither fixes the attachment loss of the compact route.

## (d) Does claim 2 explain Cause 2?

Yes. [code] [inference]
- In e3, the hook wrote copies with the original `message.id`. After the relink fixed Cause 1, the chain held only the copies.
- `S1r` grouped each copy with its pre-boundary original by `message.id`. It recovered the original and, through `b`, the original tool_result rows.
- `g1r` deleted nothing, because the hook boundary had no anchors. The e3 file is far below 5 MiB, so `nOn` did not cut either.
- That gives "loaded twice". The `tool_use_id` part of the observation matches the second recovery path (`he`).

## (e) Effect on an idle file shake that adds no boundary

No boundary means no new input to `g1r`, `nOn` or the GC. The shake changes no `uuid`, `parentUuid`, `message.id` or `tool_use_id`, so `MSt` and `S1r` select the same rows as before. Only the tool_result `content` differs. This matches e1/e2: 0 duplicates. [code] [inference]

Edge cases: [code] [inference]
1. **Byte form.** Above 5 MiB, `nOn` and `pMn` match raw bytes:
   - a line that starts with `{"parentUuid":`
   - `"uuid":"` + 36 characters + `","timestamp":"`
   - `"compact_boundary"` near the line start
   - `"isSidechain":true`

   The shake must keep key order and compact separators. e1 measured a byte-identical re-serialization, which satisfies this.
2. **Crossing 5 MiB downward.** Suppose the file has a boundary without anchors and hook-kept copies. Above 5 MiB, `nOn` cut the old rows. If the shake brings the file to 5 MiB or less, the full-parse path keeps them, and Cause 1/2 duplicates come back. A native full-compaction boundary is safe: it has fresh summary rows and a null parent.
3. **Hook-kept copies.** If the file holds both an original and a hook copy of a result, shake both. `S1r` reloads the unshaken original.
4. **`CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP`** turns off the 5 MiB skip, with the same effect as case 2.
