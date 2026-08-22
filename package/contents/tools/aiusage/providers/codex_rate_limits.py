"""Drives `codex app-server --stdio` over JSON-RPC to read plan rate limits.

Popen with line-buffered stdin/stdout; a 5s read timeout per phase, and the child is always reaped.
"""

import json
import os
import selectors
import shutil
import subprocess

# Where the codex CLI lives when it is not on $PATH. Plasma widgets (and any
# other non-login parent) do not run the user's shell rc, so version managers
# that put the CLI on PATH only there — mise/asdf shims, cargo-installed
# binaries — are invisible to the backend even though `codex` works fine in a
# terminal. The mise shim is preferred over the versioned install dir because
# it survives toolchain updates.
_CODEX_FALLBACKS = (
    "~/.local/share/mise/shims/codex",
    "~/.local/bin/codex",
    "~/.cargo/bin/codex",
    "~/.npm-global/bin/codex",
    "/usr/local/bin/codex",
    "/usr/bin/codex",
)


def codex_binary():
    """Absolute path to the codex CLI, or None. $CODEX_BIN wins, then $PATH,
    then the usual non-login install spots."""
    override = os.environ.get("CODEX_BIN")
    if override:
        return override
    found = shutil.which("codex")
    if found:
        return found
    for candidate in _CODEX_FALLBACKS:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    return None


def _read_until_id(stream, want_id, timeout):
    sel = selectors.DefaultSelector()
    sel.register(stream, selectors.EVENT_READ)
    try:
        while True:
            if not sel.select(timeout):
                return None
            line = stream.readline()
            if line == "":
                return None
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("id") == want_id:
                return obj
    finally:
        sel.close()


def get_codex_rate_limits():
    binary = codex_binary()
    if binary is None:
        return {}

    try:
        proc = subprocess.Popen(
            [binary, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError:
        return {}

    # Popen fills both pipes because stdin/stdout are PIPE above, but they are
    # Optional on the type level — bind them once so the child is still reaped
    # if that ever fails rather than raising past the cleanup below.
    stdin, stdout = proc.stdin, proc.stdout

    result = {}
    try:
        if stdin is None or stdout is None:
            return {}

        initialize = json.dumps(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "kde-ai-usage", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            }
        )
        try:
            stdin.write(initialize + "\n")
            stdin.flush()
        except (BrokenPipeError, OSError):
            return {}

        if _read_until_id(stdout, 1, 5) is not None:
            read_limits = json.dumps({"id": 2, "method": "account/rateLimits/read", "params": None})
            try:
                stdin.write(read_limits + "\n")
                stdin.flush()
            except (BrokenPipeError, OSError):
                read_limits_reply = None
            else:
                read_limits_reply = _read_until_id(stdout, 2, 5)
            if read_limits_reply is not None:
                result = read_limits_reply.get("result") or {}
    finally:
        for stream in (stdin, stdout):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    return result
