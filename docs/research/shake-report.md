# Offline shake of one session copy

Date: 2026-10-07. Window C (`766f1e04`, cut at turn 3). Replay model Sonnet 5.5, effort high. Same sandbox and guard as the cap pilot (`report.md`). Saved by the main session from the cap-benchmark agent's message.

## Verdict

- **The shake works.** The shaken fork resumed without errors. Its first request was 90,523 tokens against 108,566 for the plain fork (-18,043, -16.6%). [measured]
- **The chain stayed valid.** uuid and parentUuid identical; the 33 thinking blocks with signatures identical; 226 attachment rows in both forks; 56/56 tool_use and tool_result pairs; 0 dangling parents, before and after resume. [measured]
- **Claude kept working.** Both shaken replays finished all 3 messages with no refusals and no complaints about missing output. 0 recovery reads of the saved files. The judge found that the shaken runs differ from plain-a no more than plain-b does. [measured]
- **An Edit after a shaken Read worked without a new Read,** in the shaken fork and in the plain control. [measured]
- **Cost:** a shake on a cached session invalidates the cache. The next request wrote 73,124 tokens again (that turn cost 0.31 USD, against 0.05 USD in plain). [measured]

## Shake (`shake.py --keep-tokens 16000`)

- It replaced 20 results with 53,002 characters (estimated 22,261 tokens) and kept the newest results with about 16k estimated tokens. Directory mode 700, files 600. It wrote a backup first.
- `shake.py verify plain shaken`: only tool_result content and toolUseResult differ, in 20 rows. All other lines are byte for byte the same (sessionId aside). Exit 0.
- Selection uses file order, not the parent walk from the leaf, because parallel tool results sit off that walk. Results under 500 characters and non-text results (an image or a tool_reference) stay.

## Numbers [measured unless marked]

| Measure | plain | shaken |
|---|---|---|
| Probe "reply ok": request tokens | 108,566 | 90,523 |
| Probe: cache write / cost USD (cold) | 103,784 / 0.416 | 85,741 / 0.344 |
| Offline estimate of the shaken size [estimate] | | 86,305 (-22,261) |
| Start of turn 2, run a / run b | 148,678 / 149,049 | 130,869 / 130,909 |
| Start of turn 3, run a / run b | 183,406 / 213,750 | 182,649 / 153,867 |
| Request tokens over 3 turns, run a / b | 1,466,206 / 2,618,097 | 1,986,181 / 1,438,184 |
| Cost over 3 turns, run a (cold) / b (warm) | 1.169 / 1.307 | 1.279 / 0.722 |
| API calls per turn, run a ; run b | 1,6,2 ; 1,12,2 | 1,10,2 ; 1,4,5 |
| Recovery reads of saved files | n/a | 0 ; 0 |
| Tool errors, run a ; run b | 1 ; 2 | 1 ; 1 |
| Refusals | 0 | 0 |
| Edit with no new Read after a shaken Read | accepted | accepted |
| Edit turn after the shake: cache write / turn cost | 495 / 0.050 | 73,124 / 0.314 |

- All tool errors came from the sandbox (`prompt-audit.md` is outside the file-tool root), in both variants.
- Judge (Sonnet, prompt in `cases/shake/judge-prompt.txt`): every run is PARTIAL against the original. Shaken is no further from plain-a than plain-b is.
- Turn 3 sizes and the 3-turn totals follow run-to-run variance, not the shake.

## Problems and limits

1. The 0.42 tokens/character estimate was too high for this window: about 0.34 measured. A second shake (keep 0, 41,572 characters) saved 13.3k against an estimated 17.5k (92,352 to 79,074). The offline numbers in `report.md` may be about 20% high. [estimate]
2. Cache: the shake changes early messages, so the first request after it rewrites almost the whole history. It pays off only if the session goes on for many calls. Break-even in USD not computed. [unverified]
3. Separate `claude -p --resume` calls of an unshaken session also re-wrote about 85-104k cache tokens; only `--fork-session` from the same fork reused the cache. Cause unverified. The clean measure of the shake penalty is the Edit-turn pair above.
4. Edit test: window C had no earlier Read results (files were read with Bash `cat`). A Read was made in a new turn, then shaken with `--keep-tokens 0`. Plain also accepted the Edit without a new Read, so this test cannot show whether Claude Code restores read-state from the transcript.
5. toolUseResult replaced by a placeholder string loaded without error on resume. Interactive UI and `/rewind` not checked. [unverified]
6. Sample: n=2 per variant, one window, Sonnet replaying Opus; sandbox, no MCP or Agent tools; an appended note explains the placeholder in both variants.

## Cost and safety

- 6.50 USD measured (probes 0.76, replays 4.48, judge 0.09, Edit test 1.17).
- Source sha256 unchanged (da3ca48c...). Only fork copies were edited, each while no process had it open (lsof check). Backups in `cases/shake/backup/`. No settings change, no push, no plugin.
- Files: `benchmark/shake.py` (new), `benchmark/bench.py` (new `ask` subcommand, `BENCH_NOTE_EXTRA`).
- Scratch cases: `cap-bench/cases/plain` (fork acc1308d-8585-441d-8deb-1da8864c38eb) and `cap-bench/cases/shake` (fork 9fc07ce9-c278-4f4c-a60d-d44f7d62d486).
