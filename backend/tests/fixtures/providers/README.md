# Provider fixtures

`codex-0.154.0-success.jsonl` is a sanitized native stream from the real,
independently verified `phase6-codex-verified` run. Only session IDs were replaced.
The measured usage belongs to that recording; it is not a benchmark constant.
`scripts/export_provider_fixture.py` makes additional recordings reproducible.

`test_providers.py` also contains small **constructed contract fixtures** for
Claude's successful stream, missing usage, malformed events, and error handling.
They are deliberately distinguished from live recordings.
`claude-2.1.220-success.jsonl` is the sanitized native stream from real dashboard
run `9643e9d77c3c4f30a8856ecd940eae6c`, independently verified 3/3 after login renewal.
Session identifiers were replaced; measured usage is specific to that recording.

Normal tests never call a model. The opt-in container tests run a diagnostic
Python process inside the actual provider sandbox and perform real verification
and PostgreSQL persistence. Separate live tests require explicit paid-test flags.
