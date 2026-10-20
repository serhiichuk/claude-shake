#!/usr/bin/env python3
"""File side of the claude-shake mod.

  shake_io.py save SESSION     stdin: {"items": [{"id", "text"}]}; stdout: {"<id>": "<path>"}
  shake_io.py shake SESSION [--timeout S]
                               stdin: {"<tool_use_id>": "<placeholder>"}; stdout: {"replaced": [ids]}
  shake_io.py cache SESSION    stdout: {"lastRequestMs": ms|null, "ttlMinutes": 60|5|null}

SESSION is a session id or a path to a session .jsonl file.
shake replaces the content of each named tool_result block in the file and changes no
other line. A block that is already shaken stays. shake exit codes: 0 done or nothing
to do, 2 timed out or the file changed under the rewrite, 3 refused.
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


def save(session, items):
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


def rewrite(path, snapshot, body):
    tmp, backup = path + ".shake-tmp", f"{path}.shake-bak.{time.time_ns()}"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, snapshot.st_mode & 0o777)
    try:
        write_all(fd, body)
        now = os.stat(path)
        if now.st_ino != snapshot.st_ino or now.st_size < snapshot.st_size:
            raise Changed("session file changed under the rewrite")
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
        raise Changed("session file changed under the rewrite")
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


SHAKEN_PREFIXES = ("[shaken:", "<persisted-output>", "<truncated-output>")


def shaken_line(line, replacements):
    """Return (new line, replaced ids), or (None, []) when no block of the line changes."""
    if b'"tool_result"' not in line:
        return None, []
    row = json.loads(line)
    content = (row.get("message") or {}).get("content") if row.get("type") == "user" else None
    if not isinstance(content, list):
        return None, []
    replaced = []
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "tool_result"):
            continue
        new = replacements.get(block.get("tool_use_id"))
        old = block.get("content")
        if new is None or (isinstance(old, str) and old.lstrip().startswith(SHAKEN_PREFIXES)):
            continue
        block["content"] = new
        replaced.append(block["tool_use_id"])
    if not replaced:
        return None, []
    try:
        return dumps(row).encode("utf-8"), replaced
    except UnicodeEncodeError:  # a lone surrogate: leave the row as it is
        return None, []


def shake(session, replacements, timeout=3.0):
    """Wait until the file is stable, then replace the named tool results in place."""
    path = session_path(session)
    deadline = time.monotonic() + timeout
    stable_size, stable_since = None, None
    while True:
        snapshot = os.stat(path)
        now = time.monotonic()
        if snapshot.st_size != stable_size:
            stable_size, stable_since = snapshot.st_size, now
        elif now - stable_since >= STABLE_S:
            with open(path, "rb") as f:
                data = f.read(snapshot.st_size)
            if not data or data.endswith(b"\n"):
                break
        if now >= deadline:
            return 2, {"status": "timeout", "waiting_for": "a stable file"}
        time.sleep(POLL_S)
    parts, replaced, done = [], [], 0
    for start, end in split_lines(data):
        new_line, ids = shaken_line(data[start:end], replacements)
        if new_line is not None:
            parts += [data[done:start], new_line]
            done = end
            replaced += ids
    if not replaced:
        return 0, {"status": "nothing to replace", "replaced": []}
    parts.append(data[done:])
    extra = rewrite(path, snapshot, b"".join(parts))
    return 0, {"status": "shaken", "replaced": replaced, **extra}


def cache(session):
    """Time of the last main-loop request, and the cache TTL its newest cache write used."""
    with open(session_path(session), "rb") as f:
        data = f.read()
    last_ms = ttl = None
    for start, end in reversed(split_lines(data)):
        line = data[start:end]
        if b'"usage"' not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message")
        if (row.get("type") != "assistant" or row.get("isSidechain") or not isinstance(message, dict)
                or message.get("model") == "<synthetic>"):
            continue
        last_ms = last_ms or parse_ms(row["timestamp"])
        written = (message.get("usage") or {}).get("cache_creation") or {}
        if written.get("ephemeral_1h_input_tokens"):
            ttl = 60
        elif written.get("ephemeral_5m_input_tokens"):
            ttl = 5
        if ttl:
            break
    return {"lastRequestMs": last_ms, "ttlMinutes": ttl}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["save", "shake", "cache"])
    parser.add_argument("session")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    try:
        if args.action == "cache":
            print(json.dumps(cache(args.session)))
            return 0
        request = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if args.action == "save":
            print(json.dumps(save(args.session, request["items"])))
            return 0
        code, report = shake(args.session, request, args.timeout)
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
