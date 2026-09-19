// Test-only data. Demonstration screenshots use the real API, never these fixtures.
import type { components } from "../src/api/generated/schema";
import type { Metrics, Run, TraceEvent } from "../src/api/client";

export const task: components["schemas"]["TaskDetail"] = {
  id: "incorrect_api_response",
  title: "Fix the health response",
  description: "Correct the documented response.",
  version: "2",
  tags: ["api"],
  language: "Python",
  difficulty: "easy",
  source: "agentscope",
  dataset: "AgentScope Benchmark",
  dataset_version: "0.1",
  task_hash: "a".repeat(64),
  repository: {
    type: "local",
    source: "fixtures/incorrect_api_response",
    revision: null,
    subdirectory: null,
  },
  setup_command: null,
  test_command: "python -m pytest -q",
  timeout_seconds: 60,
  expected_behavior: "Return the documented health payload.",
};
export const metrics: Metrics = {
  total_wall_time_ms: 1250,
  agent_execution_time_ms: 380,
  verification_time_ms: 460,
  agent_turns: 3,
  tool_calls: 6,
  successful_tool_calls: 6,
  failed_tool_calls: 0,
  per_tool: { read_file: 1 },
  files_modified: 1,
  lines_added: 1,
  lines_removed: 1,
  patch_bytes: 230,
  commands_executed: 1,
  agent_test_runs: 1,
  agent_test_time_ms: 330,
  retries: 0,
  tool_failures: 0,
  timeouts: 0,
  output_truncations: 0,
  verification_passed: true,
  verification_duration_ms: 460,
  official_tests_passed: 3,
  official_tests_failed: 0,
  official_tests_total: 3,
  inference: {
    input_tokens: null,
    output_tokens: null,
    total_tokens: null,
    model_calls: null,
    mean_ttft_ms: null,
    mean_itl_ms: null,
    model_latency_ms: null,
    output_tokens_per_second: null,
  },
};
export const run: Run = {
  run_id: "test-run",
  task_id: task.id,
  agent: "mock",
  strategy: "single",
  status: "completed",
  started_at: "2026-09-17T12:00:00Z",
  finished_at: "2026-09-17T12:00:01.250Z",
  failure_reason: null,
  failure_code: null,
  verification: {
    passed: true,
    exit_code: 0,
    passed_tests: 3,
    failed_tests: 0,
    total_tests: 3,
    duration_ms: 460,
    timed_out: false,
  },
  metrics,
  artifacts: [{ type: "patch", size_bytes: 230, sha256: "a".repeat(64) }],
};
export const event = (
  sequence: number,
  event_type = "tool_call_started",
): TraceEvent => ({
  event_id: `test-run:${sequence}`,
  run_id: "test-run",
  sequence_number: sequence,
  timestamp: "2026-09-17T12:00:00Z",
  event_type,
  payload:
    event_type === "tool_call_started"
      ? { tool: "read_file", arguments: { path: "app.py" } }
      : {},
});
export const patch =
  'diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-return {"state": "healthy"}\n+return {"status": "ok"}\n';
