# AgentScope — resume summary

AgentScope is a reproducible coding-agent harness and research platform for studying
how orchestration architecture changes software-engineering correctness and
provider-process workload. No public GitHub URL is included because this workspace
has no verifiable Git remote.

- Built an isolated Python/FastAPI, PostgreSQL, Docker, and React coding-agent
  harness integrating Codex CLI and Claude Code, with controlled repository tools,
  independent hidden-test verification, credential separation, and Harbor 0.23.0 /
  Terminal-Bench 2.1 interoperability.
- Designed single-agent, planner–implementer–reviewer, and bounded parallel-subagent
  execution with independent candidate workspaces, pre-verification reviewer
  selection, hierarchical traces, per-role token/tool telemetry, resumable schedules,
  and queryable experiment provenance.
- Executed and analyzed a controlled 108-run Codex study over 12 frozen tasks using
  task-cluster bootstrap intervals: observed 21/36 official successes for single and
  15/36 for both staged and parallel-2, while transparently reporting increased
  latency/workload, incomplete failure-associated token telemetry, and limits on
  generalization rather than claiming an overall winner.
