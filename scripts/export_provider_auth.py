"""Explicit local provisioning, never imported by the API or run automatically.

Export only the selected provider credential to a NEW owner-only file outside the
repository. No credential values or account identifiers are printed.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("codex", "claude-code"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit("Credential files must be outside the repository")
    try:
        if args.provider == "codex":
            source = json.loads((Path.home() / ".codex" / "auth.json").read_text())
            data = {key: source[key] for key in ("auth_mode", "tokens", "last_refresh") if key in source}
        else:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, timeout=15, check=True,
            )
            source = json.loads(result.stdout)
            oauth = source["claudeAiOauth"]
            data = {"claudeAiOauth": {
                key: oauth[key] for key in ("accessToken", "refreshToken", "expiresAt", "scopes",
                                            "subscriptionType", "rateLimitTier") if key in oauth
            }}
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(data, handle)
        print(f"Exported minimum authentication to {args.output} (mode 0600)")
    except (OSError, KeyError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        raise SystemExit("Credential export failed; check login and use a new output path") from None


if __name__ == "__main__":
    main()
