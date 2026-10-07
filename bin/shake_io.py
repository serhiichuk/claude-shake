#!/usr/bin/env python3
"""File side of the claude-shake mod.

  shake_io.py save SESSION     stdin: {"since": ms, "items": [{"id", "text"}]}; stdout: {"<id>": "<path>"}
  shake_io.py repair SESSION [--expect JSON] [--timeout S]

SESSION is a session id or a path to a session .jsonl file.
save records the shake time in <session dir>/shake/last-shake.json. repair anchors
only the boundary of that shake: the one boundary at or after that time.
repair exit codes: 0 done or nothing to do, 2 timed out or the file changed under
the rewrite (worth one retry), 3 refused.
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime

QUEUE_INTERVAL_S = 0.1
STABLE_S = 2.5 * QUEUE_INTERVAL_S
POLL_S = 0.05
TOOL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class Refused(Exception):
    exit_code = 3

    def __init__(self, message, **cause):
        super().__init__(message)
        self.cause = cause


class Changed(Refused):
    exit_code = 2


def session_path(session):
    if session.endswith(".jsonl") and os.path.isfile(session):
        return session
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    found = glob.glob(os.path.join(glob.escape(home), "projects", "*", glob.escape(session) + ".jsonl"))
    if len(found) != 1:
        raise Refused("session file not found or ambiguous", session=session, found=found)
    return found[0]


def shake_dir(path):
    return os.path.join(path[: -len(".jsonl")], "shake")


def last_shake_since(path):
    try:
        with open(os.path.join(shake_dir(path), "last-shake.json"), encoding="utf-8") as f:
            since = json.load(f)["since"]
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None
    return since if isinstance(since, (int, float)) and not isinstance(since, bool) else None


def record_shake(out_dir, since):
    tmp = os.path.join(out_dir, "last-shake.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"since": since}, f)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, os.path.join(out_dir, "last-shake.json"))


def save(session, since, items):
    path = session_path(session)
    os.makedirs(os.path.dirname(shake_dir(path)), mode=0o700, exist_ok=True)
    out_dir = shake_dir(path)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    saved = {}
    for item in items:
        if not TOOL_ID.match(item["id"]):
            continue
        target = os.path.join(out_dir, item["id"] + ".txt")
        data = item["text"].encode("utf-8", "replace")
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            with open(target, "rb") as f:
                if f.read() == data:
                    saved[item["id"]] = target
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        saved[item["id"]] = target
    if saved:
        record_shake(out_dir, since)
    return saved


def dumps(row):
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def parse_ms(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000


def split_lines(data):
    """Return [(start, end)] byte spans of the whole lines in data, newline excluded."""
    spans, start = [], 0
    while True:
        end = data.find(b"\n", start)
        if end < 0:
            return spans
        spans.append((start, end))
        start = end + 1


def last_boundary(data, spans):
    for i in range(len(spans) - 1, -1, -1):
        line = data[spans[i][0]:spans[i][1]]
        if b'"compact_boundary"' not in line:
            continue
        row = json.loads(line)
        if row.get("type") == "system" and row.get("subtype") == "compact_boundary":
            return i, row
    return None, None


def tool_result_ids(row):
    content = row.get("message", {}).get("content") if row.get("type") == "user" else None
    if not isinstance(content, list):
        return []
    return [b.get("tool_use_id") for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def boundaries_since(data, spans, since):
    count = 0
    for start, end in spans:
        line = data[start:end]
        if b'"compact_boundary"' in line:
            row = json.loads(line)
            count += row.get("subtype") == "compact_boundary" and parse_ms(row["timestamp"]) >= since
    return count


def inspect(data, expect, since):
    """Return (state, plan). state is 'done:<why>', 'wait:<why>' or 'ready'."""
    if since is None:
        return "done:not ours (no shake recorded)", None
    if not data.endswith(b"\n") and data:
        return "wait:partial tail", None
    spans = split_lines(data)
    index, boundary = last_boundary(data, spans)
    if boundary is None:
        return ("wait:no boundary" if expect else "done:no boundary"), None
    if parse_ms(boundary["timestamp"]) < since:
        return ("wait:no new boundary" if expect else "done:not ours (older than the last shake)"), None
    if boundaries_since(data, spans, since) > 1:
        return "done:not ours (another compaction followed the shake)", None
    meta = boundary.get("compactMetadata") or {}
    if meta.get("preservedMessages") or meta.get("preservedSegment"):
        return "done:already anchored", None
    after = [json.loads(data[s:e]) for s, e in spans[index + 1:]]
    if any(r.get("type") == "user" and r.get("isCompactSummary") for r in after):
        return "done:native boundary", None
    if expect:
        written = {i for r in after for i in tool_result_ids(r)}
        if not set(expect["toolIds"]) <= written:
            return "wait:hook rows not on disk", None
    return "ready", (spans, index, boundary, after)


def anchored_line(data, spans, index, boundary, after):
    start, end = spans[index]
    line = data[start:end]
    if dumps(boundary).encode("utf-8") != line:
        raise Refused("boundary line does not round-trip byte for byte", line=index + 1)
    before = set()
    for s, e in spans[:index]:
        uid = json.loads(data[s:e]).get("uuid")
        if uid:
            before.add(uid)
    uuids, previous = [], boundary["uuid"]
    for row in after:
        uid = row.get("uuid")
        if not uid or row.get("isSidechain"):
            continue
        parent = row.get("parentUuid")
        if uid in before or uid in uuids:
            raise Refused("duplicate uuid after the boundary", uuid=uid)
        if parent != previous and parent not in before:
            raise Refused("rows after the boundary do not form one chain", uuid=uid, parent=parent)
        uuids.append(uid)
        previous = uid
    if not uuids:
        raise Refused("no rows after the boundary")
    boundary = dict(boundary)
    boundary["compactMetadata"] = {
        **(boundary.get("compactMetadata") or {}),
        "preservedMessages": {"anchorUuid": boundary["uuid"], "uuids": uuids},
    }
    return start, end, dumps(boundary).encode("utf-8"), len(uuids)


def write_all(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def prune_backups(path):
    def stamp(backup):
        suffix = backup.rsplit(".", 1)[1]
        return int(suffix) if suffix.isdigit() else -1

    for old in sorted(glob.glob(glob.escape(path) + ".shake-bak.*"), key=stamp)[:-1]:
        os.unlink(old)


def rewrite(path, snapshot, data, start, end, new_line):
    tmp, backup = path + ".shake-tmp", f"{path}.shake-bak.{time.time_ns()}"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, snapshot.st_mode & 0o777)
    try:
        body = data[:start] + new_line + data[end:]
        write_all(fd, body)
        now = os.stat(path)
        if now.st_ino != snapshot.st_ino or now.st_size < snapshot.st_size:
            raise Changed("session file changed under the repair")
        tail = b""
        if now.st_size > snapshot.st_size:
            with open(path, "rb") as f:
                f.seek(snapshot.st_size)
                tail = f.read(now.st_size - snapshot.st_size)
            tail = tail[: tail.rfind(b"\n") + 1]
            write_all(fd, tail)
        os.fsync(fd)
        if os.fstat(fd).st_size != len(body) + len(tail):
            raise Refused("temp file size does not match what was written")
    except BaseException:
        os.close(fd)
        os.unlink(tmp)
        raise
    os.close(fd)
    copied = snapshot.st_size + len(tail)
    os.link(path, backup)
    final = os.stat(path)
    if final.st_ino != snapshot.st_ino or final.st_size != copied:
        os.unlink(tmp)
        os.unlink(backup)
        raise Changed("session file changed under the repair")
    os.rename(tmp, path)
    dir_fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    late = os.stat(backup).st_size - copied
    if late > 0:
        with open(backup, "rb") as f:
            f.seek(copied)
            extra = f.read()
        extra = extra[: extra.rfind(b"\n") + 1]
        with open(path, "ab") as f:
            f.write(extra)
            f.flush()
            os.fsync(f.fileno())
        prune_backups(path)
        return {"late_bytes_copied": len(extra), "backup_kept": backup}
    os.unlink(backup)
    prune_backups(path)
    return {}


def repair(session, expect=None, timeout=None):
    try:
        path = session_path(session)
    except Refused:
        return 0, {"status": "no session file"}
    timeout = timeout if timeout is not None else (10.0 if expect else 2.0)
    since = expect["since"] if expect else last_shake_since(path)
    deadline = time.monotonic() + timeout
    stable_size, stable_since = None, None
    while True:
        snapshot = os.stat(path)
        with open(path, "rb") as f:
            data = f.read(snapshot.st_size)
        state, plan = inspect(data, expect, since)
        if state.startswith("done:"):
            return 0, {"status": state[5:]}
        now = time.monotonic()
        if snapshot.st_size != stable_size:
            stable_size, stable_since = snapshot.st_size, now
        if state == "ready" and now - stable_since >= STABLE_S:
            start, end, new_line, listed = anchored_line(data, *plan)
            extra = rewrite(path, snapshot, data, start, end, new_line)
            return 0, {"status": "anchored", "uuids": listed, **extra}
        if now >= deadline:
            return 2, {"status": "timeout", "waiting_for": state.split(":", 1)[-1]}
        time.sleep(POLL_S)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["save", "repair"])
    parser.add_argument("session")
    parser.add_argument("--expect", type=json.loads)
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args()
    try:
        if args.action == "save":
            request = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
            print(json.dumps(save(args.session, request["since"], request["items"])))
            return 0
        code, report = repair(args.session, args.expect, args.timeout)
        print(json.dumps(report))
        return code
    except Refused as refused:
        print(json.dumps({"status": "refused", "reason": str(refused), "cause": refused.cause}, default=str))
        return refused.exit_code
    except ValueError as error:
        print(json.dumps({"status": "refused", "reason": "session file has a line that is not JSON",
                          "cause": str(error)}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
