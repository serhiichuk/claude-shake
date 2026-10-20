#!/usr/bin/env python3
"""Self-check of the file side: save, shake, cache, shake-check and shake-fork.

usage: python3 test/test_io.py [FIXTURE.jsonl]

The fixture is any session file with large tool results. The default is the e3 run
of the live-shake research. It is only copied, never changed. Exits 0 when every
check passes.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import glob
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
IO = os.path.join(ROOT, "bin", "shake_io.py")
CHECK = os.path.join(ROOT, "bin", "shake-check")
FORK = os.path.join(ROOT, "bin", "shake-fork")
DEFAULT_FIXTURE = (
    "/Users/serhiichuk/.claude/projects/-private-tmp-claude-501--Users-serhiichuk-Repos-agents-"
    "25250090-c99b-4ed8-800a-070cc842dc8f-scratchpad-live-shake-work-e3-compact/"
    "01548c3e-2358-4b76-9097-93997239dc25.jsonl.live"
)
SESSION_ID = "01548c3e-2358-4b76-9097-93997239dc25"


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(*argv, stdin=None, env=None):
    done = subprocess.run([sys.executable, *argv], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def check(path):
    code, out, err = run(CHECK, path)
    assert code == 0, err
    return json.loads(out)


def shake(path, replacements, *extra):
    code, out, _ = run(IO, "shake", path, *extra, stdin=json.dumps(replacements))
    return code, json.loads(out)


def lines(path):
    with open(path, "rb") as f:
        return f.read().split(b"\n")


def leftovers(path):
    return glob.glob(glob.escape(path) + ".shake-*")


def fresh(work, fixture, name):
    project = os.path.join(work, "projects", name)
    os.makedirs(project)
    path = os.path.join(project, SESSION_ID + ".jsonl")
    shutil.copyfile(fixture, path)
    os.chmod(path, 0o600)
    return path


def tool_results(path):
    """[(line index, block)] of every tool_result block in user rows."""
    found = []
    for i, line in enumerate(lines(path)):
        if not line:
            continue
        row = json.loads(line)
        content = (row.get("message") or {}).get("content") if row.get("type") == "user" else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append((i, block))
    return found


def large_ids(path, count=2):
    sizes = {}
    for _, block in tool_results(path):
        content = block.get("content")
        if isinstance(content, str) and content.lstrip().startswith(("[shaken:", "<persisted-output>", "<truncated-output>")):
            continue
        sizes[block["tool_use_id"]] = max(sizes.get(block["tool_use_id"], 0), len(json.dumps(content)))
    return sorted(sizes, key=sizes.get, reverse=True)[:count]


def stub(tool_id):
    return f"<persisted-output>\nOutput too large. Full output saved to: /saved/{tool_id}.txt\n</persisted-output>"


def test_shake_replaces_only_named_blocks(work, fixture):
    path = fresh(work, fixture, "shake")
    ids = large_ids(path)
    before_rows = lines(path)
    before = check(path)
    code, report = shake(path, {i: stub(i) for i in ids})
    assert code == 0 and report["status"] == "shaken" and set(report["replaced"]) == set(ids), report
    after_rows = lines(path)
    assert len(after_rows) == len(before_rows)
    changed = 0
    for old, new in zip(before_rows, after_rows):
        if not any(i.encode() in old for i in ids):
            assert old == new, "a line without a named result changed"
            continue
        if old == new:
            continue
        changed += 1
        old_row, new_row = json.loads(old), json.loads(new)
        for a, b in zip(old_row["message"]["content"], new_row["message"]["content"]):
            if b.get("type") == "tool_result" and b["tool_use_id"] in ids:
                assert b["content"] == stub(b["tool_use_id"]) and b.get("is_error") == a.get("is_error"), b
                a = {**a, "content": b["content"]}
            assert a == b, "another block changed"
        new_row["message"]["content"] = old_row["message"]["content"]
        assert old_row == new_row, "another field changed"
    assert changed >= len(ids)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert not leftovers(path)
    after = check(path)
    assert after["file"]["dangling_parents"] == before["file"]["dangling_parents"], after["file"]
    digest = sha(path)
    code, report = shake(path, {i: "other" for i in ids + ["toolu_unknown"]})
    assert code == 0 and report["replaced"] == [], report
    assert sha(path) == digest, "a shaken result changed again"
    print("ok shake replaces only the named blocks, keeps is_error, never re-shakes;", changed, "lines changed")


def test_shake_waits_for_partial_tail(work, fixture):
    path = fresh(work, fixture, "partial")
    replacements = {i: stub(i) for i in large_ids(path)}
    with open(path, "ab") as f:
        f.write(b'{"parentUuid":"x","isSidechain":false,"type":"user"')
    digest = sha(path)
    code, report = shake(path, replacements, "--timeout", "0.6")
    assert code == 2 and report["status"] == "timeout", report
    assert sha(path) == digest and not leftovers(path)
    print("ok partial tail: timed out, file untouched")


def test_shake_keeps_rows_appended_meanwhile(work, fixture):
    path = fresh(work, fixture, "late")
    late_line = json.dumps({"type": "last-prompt", "lastPrompt": "late", "sessionId": SESSION_ID}).encode() + b"\n"

    def append_later():
        time.sleep(0.1)
        with open(path, "ab") as f:
            f.write(late_line)

    writer = threading.Thread(target=append_later)
    writer.start()
    code, report = shake(path, {i: stub(i) for i in large_ids(path)}, "--timeout", "5")
    writer.join()
    assert code == 0 and report["status"] == "shaken", report
    assert lines(path)[-2] == late_line[:-1], "late row not kept"
    print("ok shake waits for a stable file and keeps the rows appended before it")


def test_old_backups_do_not_block_and_are_pruned(work, fixture):
    path = fresh(work, fixture, "oldbackup")
    for stamp in (1, 2):
        with open(f"{path}.shake-bak.{stamp}", "wb") as f:
            f.write(b"kept by an earlier rewrite\n")
    code, report = shake(path, {i: stub(i) for i in large_ids(path)})
    assert code == 0 and report["status"] == "shaken", report
    assert leftovers(path) == [path + ".shake-bak.2"], leftovers(path)
    print("ok kept backups do not block the next rewrite; only the newest stays")


def test_partial_os_write_is_completed(work, fixture):
    sys.path.insert(0, os.path.join(ROOT, "bin"))
    import shake_io

    path = fresh(work, fixture, "shortwrite")
    reference = fresh(work, fixture, "shortwrite-reference")
    replacements = {i: stub(i) for i in large_ids(path)}
    assert shake(reference, replacements)[0] == 0
    real_write = os.write
    os.write = lambda fd, data: real_write(fd, bytes(data[:4096]))
    try:
        code, report = shake_io.shake(path, replacements)
    finally:
        os.write = real_write
    assert code == 0 and report["status"] == "shaken", report
    with open(path, "rb") as a, open(reference, "rb") as b:
        assert a.read() == b.read(), "short writes changed the result"
    print("ok short os.write calls still write the whole file")




def test_check_counts_string_content(work, fixture):
    path = os.path.join(work, "string-content.jsonl")
    user = {"type": "user", "uuid": "u1", "parentUuid": None, "message": {"role": "user", "content": "hello"}}
    reply = {"role": "assistant", "id": "msg_1", "content": "hi"}
    off_chain = {"type": "assistant", "uuid": "a2", "parentUuid": "u1", "message": reply}
    on_chain = {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "message": reply}
    with open(path, "w") as f:
        f.write("".join(json.dumps(r) + "\n" for r in (user, off_chain, on_chain)))
    loader = check(path)["loader"]
    assert loader["recovered_rows"] == 1 and loader["duplicate_message_blocks"] == 1, loader
    print("ok shake-check counts string message content as a text block")


def test_save(work, fixture):
    home = os.path.join(work, "home")
    path = fresh(home, fixture, "save")
    env = {"CLAUDE_CONFIG_DIR": home}
    items = [{"id": "toolu_a", "text": "alpha é"}, {"id": "../evil", "text": "x"}]
    code, out, err = run(IO, "save", SESSION_ID, stdin=json.dumps({"items": items}), env=env)
    assert code == 0, err
    saved = json.loads(out)
    target = os.path.join(os.path.dirname(path), SESSION_ID, "shake", "toolu_a.txt")
    assert saved == {"toolu_a": target}, saved
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert os.stat(os.path.dirname(target)).st_mode & 0o777 == 0o700
    code, out, _ = run(IO, "save", SESSION_ID, stdin=json.dumps({"items": [{"id": "toolu_a", "text": "alpha é"}]}), env=env)
    assert json.loads(out) == {"toolu_a": target}, "identical content is reused"
    code, out, _ = run(IO, "save", SESSION_ID, stdin=json.dumps({"items": [{"id": "toolu_a", "text": "other"}]}), env=env)
    assert json.loads(out) == {}, "different content must not overwrite"
    with open(target, encoding="utf-8") as f:
        assert f.read() == "alpha é"
    print("ok save: 600/700 modes, no overwrite, unsafe id skipped")


def test_fork(work, fixture):
    home = os.path.join(work, "forkhome")
    path = fresh(home, fixture, "fork")
    digest = sha(path)
    code, out, err = run(FORK, SESSION_ID, env={"CLAUDE_CONFIG_DIR": home})
    assert code == 0, err
    assert sha(path) == digest
    target = next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("fork: "))
    new_id = os.path.basename(target)[: -len(".jsonl")]
    source_rows = [line for line in lines(path) if line and json.loads(line).get("type") != "cost-state"]
    fork_rows = [line for line in lines(target) if line]
    assert len(source_rows) == len(fork_rows)
    assert all(a.replace(SESSION_ID.encode(), new_id.encode()) == b for a, b in zip(source_rows, fork_rows))
    assert f"claude --resume {new_id} --plugin-dir" in out
    first_cwd = next(json.loads(line)["cwd"] for line in lines(path) if line and "cwd" in json.loads(line))
    assert f"cd {first_cwd} && claude" in out, out
    assert "warning: the first cwd does not map to this project directory" in out, out
    print("ok fork: new id, bytes kept except sessionId, source unchanged")


def test_cache(work, fixture):
    path = os.path.join(work, "cache.jsonl")
    def reply(ts, written, sidechain=False, model="claude-opus-5-5"):
        usage = {"cache_creation": {"ephemeral_1h_input_tokens": written[0], "ephemeral_5m_input_tokens": written[1]}}
        return {"type": "assistant", "timestamp": ts, "isSidechain": sidechain,
                "message": {"model": model, "usage": usage}}
    rows = [reply("2026-10-12T10:00:00.000Z", (0, 900)), reply("2026-10-12T10:01:00.000Z", (0, 0)),
            reply("2026-10-12T10:02:00.000Z", (0, 0), model="<synthetic>"),
            reply("2026-10-12T10:03:00.000Z", (500, 0), sidechain=True)]
    with open(path, "w") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    code, out, err = run(IO, "cache", path)
    assert code == 0, err
    assert json.loads(out) == {"lastRequestMs": 1791799260000.0, "ttlMinutes": 5}, out
    print("ok cache: last main request time, TTL from the newest cache write")


def main():
    fixture = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    if not os.path.isfile(fixture):
        sys.exit("fixture not found; pass a session file with large tool results")
    fixture_digest = sha(fixture)
    work = tempfile.mkdtemp(prefix="shake-test-")
    try:
        test_shake_replaces_only_named_blocks(work, fixture)
        test_shake_waits_for_partial_tail(work, fixture)
        test_shake_keeps_rows_appended_meanwhile(work, fixture)
        test_old_backups_do_not_block_and_are_pruned(work, fixture)
        test_partial_os_write_is_completed(work, fixture)
        test_check_counts_string_content(work, fixture)
        test_save(work, fixture)
        test_fork(work, fixture)
        test_cache(work, fixture)
    finally:
        shutil.rmtree(work)
    assert sha(fixture) == fixture_digest, "fixture changed"
    print("all checks passed; fixture unchanged")


if __name__ == "__main__":
    main()
