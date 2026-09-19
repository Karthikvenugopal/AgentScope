"""Container-only bootstrap. Secrets arrive on stdin, never Docker argv or environment metadata."""
import json
import os
import pathlib
import sys

request = json.loads(sys.stdin.buffer.readline(131072))
environment = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/home/agent",
    "CODEX_HOME": "/home/agent/.codex",
    "CLAUDE_CONFIG_DIR": "/home/agent/.claude",
    "LANG": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}
allowed = {"CODEX_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}
pathlib.Path(environment["CODEX_HOME"]).mkdir(mode=0o700, parents=True, exist_ok=True)
for key, value in request["credentials"]["environment"].items():
    if key not in allowed:
        raise SystemExit(64)
    environment[key] = value
auth = request["credentials"].get("codex_auth")
if auth:
    directory = pathlib.Path(environment["CODEX_HOME"])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    auth_path = directory / "auth.json"
    auth_path.write_text(json.dumps(auth))
    auth_path.chmod(0o600)
claude_auth = request["credentials"].get("claude_auth")
if claude_auth:
    directory = pathlib.Path(environment["CLAUDE_CONFIG_DIR"])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    auth_path = directory / ".credentials.json"
    auth_path.write_text(json.dumps(claude_auth))
    auth_path.chmod(0o600)
# The credential transport is not agent input. In particular Codex appends piped
# stdin to its prompt; give the CLI EOF without closing Docker's attach channel.
with open(os.devnull, "rb") as empty:
    os.dup2(empty.fileno(), 0)
os.execvpe(request["argv"][0], request["argv"], environment)
