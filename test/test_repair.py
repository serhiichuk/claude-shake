#!/usr/bin/env python3
"""Self-check of the file side: save, repair and shake-check on a hook-compacted fixture.

usage: python3 test/test_repair.py [FIXTURE.jsonl]

The fixture is a session file that a session.compact hook (handles kept) compacted
and that a later turn extended: the e3 run of the live-shake research. It is only
copied, never changed. Exits 0 when every check passes.
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
import uuid

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


def repair(path, *extra):
    code, out, _ = run(IO, "repair", path, *extra)
    return code, json.loads(out)


def lines(path):
    with open(path, "rb") as f:
        return f.read().split(b"\n")


def boundary_index(rows):
    return max(i for i, line in enumerate(rows) if b'"compact_boundary"' in line)


def leftovers(path):
    return glob.glob(glob.escape(path) + ".shake-*")


def record_shake(path, since):
    shake_dir = os.path.join(path[: -len(".jsonl")], "shake")
    os.makedirs(shake_dir, exist_ok=True)
    with open(os.path.join(shake_dir, "last-shake.json"), "w") as f:
        json.dump({"since": since}, f)


def fresh(work, fixture, name, since=0):
    project = os.path.join(work, "projects", name)
    os.makedirs(project)
    path = os.path.join(project, SESSION_ID + ".jsonl")
    shutil.copyfile(fixture, path)
    os.chmod(path, 0o600)
    if since is not None:
        record_shake(path, since)
    return path


def test_repair_anchors_and_is_idempotent(work, fixture):
    path = fresh(work, fixture, "anchors")
    before_rows = lines(path)
    before = check(path)
    assert before["loader"]["duplicate_tool_use_ids"] > 0, before
    code, report = repair(path)
    assert code == 0 and report["status"] == "anchored", report
    after_rows = lines(path)
    b = boundary_index(before_rows)
    assert len(after_rows) == len(before_rows)
    assert all(after_rows[i] == before_rows[i] for i in range(len(before_rows)) if i != b), "other lines changed"
    row = json.loads(after_rows[b])
    preserved = row["compactMetadata"].pop("preservedMessages")
    assert json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode() == before_rows[b], "boundary changed"
    expected = [json.loads(line)["uuid"] for line in before_rows[b + 1:] if line and b'"uuid"' in line
                and json.loads(line).get("uuid")]
    assert preserved == {"anchorUuid": row["uuid"], "uuids": expected}, preserved
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert not leftovers(path)
    after = check(path)
    loader = after["loader"]
    assert loader["relink"] == "anchors applied", loader
    assert loader["duplicate_tool_use_ids"] == loader["duplicate_tool_result_ids"] == 0, loader
    assert loader["duplicate_message_blocks"] == 0 and loader["dangling_parent_on_walk"] == 0, loader
    assert after["file"]["dangling_parents"] == 0
    digest = sha(path)
    code, report = repair(path)
    assert code == 0 and report["status"] == "already anchored", report
    assert sha(path) == digest
    print("ok repair anchors, keeps other lines, idempotent; duplicates", before["loader"]["duplicate_tool_use_ids"],
          "-> 0")


def test_refuses_partial_tail(work, fixture):
    path = fresh(work, fixture, "partial")
    with open(path, "ab") as f:
        f.write(b'{"parentUuid":"x","isSidechain":false,"type":"user"')
    digest = sha(path)
    code, report = repair(path, "--timeout", "0.6")
    assert code == 2 and report["waiting_for"] == "partial tail", report
    assert sha(path) == digest and not leftovers(path)
    print("ok partial tail: timed out, file untouched")


def test_waits_for_expected_rows(work, fixture):
    path = fresh(work, fixture, "expect")
    rows = lines(path)
    since = 0
    digest = sha(path)
    code, report = repair(path, "--expect", json.dumps({"since": since, "toolIds": ["toolu_late"]}), "--timeout", "0.6")
    assert code == 2 and report["waiting_for"] == "hook rows not on disk", report
    assert sha(path) == digest
    code, report = repair(path, "--expect", json.dumps({"since": 4102444800000, "toolIds": []}), "--timeout", "0.6")
    assert code == 2 and report["waiting_for"] == "no new boundary", report
    assert sha(path) == digest

    last = [json.loads(line) for line in rows if line and json.loads(line).get("uuid")][-1]
    late = {"parentUuid": last["uuid"], "isSidechain": False, "type": "user", "uuid": str(uuid.uuid4()),
            "timestamp": "2026-10-07T20:13:20.000Z",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_late",
                                                      "content": "late"}]}}
    late_line = json.dumps(late, separators=(",", ":")).encode() + b"\n"

    def append_later():
        time.sleep(0.4)
        with open(path, "ab") as f:
            f.write(late_line)

    writer = threading.Thread(target=append_later)
    writer.start()
    code, report = repair(path, "--expect", json.dumps({"since": since, "toolIds": ["toolu_late"]}), "--timeout", "5")
    writer.join()
    assert code == 0 and report["status"] == "anchored", report
    final = lines(path)
    assert final[-2] == late_line[:-1], "late row not kept"
    preserved = json.loads(final[boundary_index(final)])["compactMetadata"]["preservedMessages"]
    assert preserved["uuids"][-1] == late["uuid"], preserved["uuids"][-3:]
    print("ok waits for the expected tool result rows and the new boundary")


def test_refuses_branch_and_reformatted_boundary(work, fixture):
    path = fresh(work, fixture, "branch")
    rows = lines(path)
    b = boundary_index(rows)
    chain = [json.loads(line) for line in rows[b + 1:] if line and json.loads(line).get("uuid")]
    victim = chain[5]
    i = rows.index(next(line for line in rows if f'"uuid":"{victim["uuid"]}"'.encode() in line))
    rows[i] = rows[i].replace(f'"parentUuid":"{victim["parentUuid"]}"'.encode(),
                              f'"parentUuid":"{chain[1]["uuid"]}"'.encode(), 1)
    with open(path, "wb") as f:
        f.write(b"\n".join(rows))
    digest = sha(path)
    code, report = repair(path)
    assert code == 3 and report["reason"] == "rows after the boundary do not form one chain", report
    assert sha(path) == digest and not leftovers(path)

    path = fresh(work, fixture, "reformatted")
    rows = lines(path)
    b = boundary_index(rows)
    rows[b] = json.dumps(json.loads(rows[b]), ensure_ascii=False).encode()
    with open(path, "wb") as f:
        f.write(b"\n".join(rows))
    digest = sha(path)
    code, report = repair(path)
    assert code == 3 and report["reason"] == "boundary line does not round-trip byte for byte", report
    assert sha(path) == digest and not leftovers(path)
    print("ok refuses a branched chain and a boundary that does not round-trip")


def test_anchors_only_our_boundary(work, fixture):
    path = fresh(work, fixture, "unrecorded", since=None)
    digest = sha(path)
    code, report = repair(path)
    assert code == 0 and report["status"] == "not ours (no shake recorded)", report
    assert sha(path) == digest

    path = fresh(work, fixture, "older", since=4102444800000)
    code, report = repair(path)
    assert code == 0 and report["status"] == "not ours (older than the last shake)", report
    assert sha(path) == digest

    path = fresh(work, fixture, "followed")
    rows = lines(path)
    second = json.loads(rows[boundary_index(rows)])
    second.update(uuid=str(uuid.uuid4()), timestamp="2026-10-07T21:00:00.000Z")
    with open(path, "ab") as f:
        f.write(json.dumps(second, separators=(",", ":")).encode() + b"\n")
    digest = sha(path)
    code, report = repair(path)
    assert code == 0 and report["status"] == "not ours (another compaction followed the shake)", report
    assert sha(path) == digest
    print("ok anchors only the boundary of the recorded shake")


def test_old_backups_do_not_block_and_are_pruned(work, fixture):
    path = fresh(work, fixture, "oldbackup")
    for stamp in (1, 2):
        with open(f"{path}.shake-bak.{stamp}", "wb") as f:
            f.write(b"kept by an earlier repair\n")
    code, report = repair(path)
    assert code == 0 and report["status"] == "anchored", report
    assert leftovers(path) == [path + ".shake-bak.2"], leftovers(path)
    print("ok kept backups do not block the next repair; only the newest stays")


def test_bad_shake_record_is_no_record(work, fixture):
    for name, text in (("empty", ""), ("garbage", "{not json"), ("string", '{"since": "x"}'), ("nokey", "{}")):
        path = fresh(work, fixture, "record-" + name, since=None)
        record_shake(path, 0)
        with open(os.path.join(path[: -len(".jsonl")], "shake", "last-shake.json"), "w") as f:
            f.write(text)
        digest = sha(path)
        code, report = repair(path)
        assert code == 0 and report["status"] == "not ours (no shake recorded)", (name, report)
        assert sha(path) == digest
    print("ok an empty or corrupt shake record counts as no record")


def test_partial_os_write_is_completed(work, fixture):
    sys.path.insert(0, os.path.join(ROOT, "bin"))
    import shake_io

    path = fresh(work, fixture, "shortwrite")
    reference = fresh(work, fixture, "shortwrite-reference")
    assert repair(reference)[0] == 0
    real_write = os.write
    os.write = lambda fd, data: real_write(fd, bytes(data[:4096]))
    try:
        code, report = shake_io.repair(path)
    finally:
        os.write = real_write
    assert code == 0 and report["status"] == "anchored", report
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
    path = fresh(home, fixture, "save", since=None)
    env = {"CLAUDE_CONFIG_DIR": home}
    marker = os.path.join(os.path.dirname(path), SESSION_ID, "shake", "last-shake.json")
    code, out, _ = run(IO, "save", SESSION_ID, stdin=json.dumps({"since": 5, "items": [{"id": "../evil", "text": "x"}]}),
                       env=env)
    assert code == 0 and json.loads(out) == {} and not os.path.exists(marker), "no shake recorded without a save"
    items = [{"id": "toolu_a", "text": "alpha é"}, {"id": "../evil", "text": "x"}]
    code, out, err = run(IO, "save", SESSION_ID, stdin=json.dumps({"since": 7, "items": items}), env=env)
    assert code == 0, err
    saved = json.loads(out)
    target = os.path.join(os.path.dirname(path), SESSION_ID, "shake", "toolu_a.txt")
    assert saved == {"toolu_a": target}, saved
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert os.stat(os.path.dirname(target)).st_mode & 0o777 == 0o700
    with open(marker) as f:
        assert json.load(f) == {"since": 7}
    assert os.stat(marker).st_mode & 0o777 == 0o600
    code, out, _ = run(IO, "save", SESSION_ID, stdin=json.dumps({"since": 8, "items": [{"id": "toolu_a", "text": "alpha é"}]}), env=env)
    assert json.loads(out) == {"toolu_a": target}, "identical content is reused"
    code, out, _ = run(IO, "save", SESSION_ID, stdin=json.dumps({"since": 9, "items": [{"id": "toolu_a", "text": "other"}]}), env=env)
    assert json.loads(out) == {}, "different content must not overwrite"
    with open(target, encoding="utf-8") as f:
        assert f.read() == "alpha é"
    print("ok save: 600/700 modes, no overwrite, unsafe id skipped, shake recorded")


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


def main():
    fixture = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    if not os.path.isfile(fixture):
        sys.exit("fixture not found; pass a hook-compacted session file")
    fixture_digest = sha(fixture)
    work = tempfile.mkdtemp(prefix="shake-test-")
    try:
        test_repair_anchors_and_is_idempotent(work, fixture)
        test_refuses_partial_tail(work, fixture)
        test_waits_for_expected_rows(work, fixture)
        test_refuses_branch_and_reformatted_boundary(work, fixture)
        test_anchors_only_our_boundary(work, fixture)
        test_old_backups_do_not_block_and_are_pruned(work, fixture)
        test_bad_shake_record_is_no_record(work, fixture)
        test_partial_os_write_is_completed(work, fixture)
        test_check_counts_string_content(work, fixture)
        test_save(work, fixture)
        test_fork(work, fixture)
    finally:
        shutil.rmtree(work)
    assert sha(fixture) == fixture_digest, "fixture changed"
    print("all checks passed; fixture unchanged")


if __name__ == "__main__":
    main()
