"""Export already-sanitized native records from a real run for offline regression."""

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("trace", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
events = json.loads(args.trace.read_text())["events"]
records = []
for event in events:
    if not event["event_type"].startswith("provider_"):
        continue
    native = event.get("payload", {}).get("native")
    if isinstance(native, dict):
        if native.get("type") in ("tool_use", "tool_result"):
            continue  # Nested blocks, not top-level CLI records.
        # Session identifiers are not credentials, but unnecessary in CI fixtures.
        for key in ("thread_id", "session_id"):
            if key in native:
                native[key] = "recorded-session"
        records.append(native)
args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("x") as handle:
    for record in records:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
print(f"Exported {len(records)} sanitized native events")
