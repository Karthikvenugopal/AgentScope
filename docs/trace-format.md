# Structured trace format

Every event has `event_id`, `run_id`, `sequence_number`, `timestamp`, and a typed
`event_type`. Event IDs use `<run-id>:<six-digit-sequence>`, and assignment is
protected by an asynchronous lock. Sequence number—not timestamp—is canonical.

Event types include:

- run: `run_started`, `run_completed`, `run_failed`, `run_timed_out`
- agent: `agent_started`, `agent_turn_started`, `agent_turn_completed`,
  `agent_completed`
- tools: `tool_call_started`, `tool_call_completed`, `tool_call_failed`
- effects: `file_modified`, `command_executed`, `test_executed`
- official verification: `verification_started`, `verification_completed`,
  `verification_failed`. Terminal verification events contain the typed result,
  JUnit counts (or null), exit code, elapsed time, timeout and truncation flags.

Tool inputs and structured outputs are recorded. Command output is bounded by the
run configuration, and `stdout_truncated`/`stderr_truncated` flags make any loss
explicit. No model calls or inference metrics are emitted by the mock agent.

Each run exports:

```text
artifacts/runs/<run-id>/
├── trace.json   # ordered events
├── patch.diff   # final Git-style patch
└── run.json     # terminal summary without duplicated trace/patch bodies
```
