# Controlled orchestration strategy study v1

> Technical experiment output, not a leaderboard or overall ranking.

## Research question

How does coding-agent orchestration strategy affect correctness and inference workload when provider, benchmark, and environment are held constant?

## Design

- Benchmark: AgentScope Benchmark v0.1
- Manifest SHA-256: `132a2070b12f143d889a2b88af200063800194162835bbdd3eea01aef8f38f80`
- Tasks: 12
- Configurations: 3
- Repetitions per task/configuration: 3
- Random schedule seed: 20260918
- Task-cluster bootstrap seed: 20260919
- Cross-run concurrency: 1; internal parallel strategy concurrency remains treatment.
- Provider versions: `{"codex": {"available": true, "capabilities": {"model_request_boundaries": false, "model_selection": true, "per_request_usage": false, "session_continuation": true, "session_ids": true, "streaming_events": true, "structured_output": true, "token_stream_timestamps": false, "token_usage": true, "tool_events": true}, "id": "codex", "reason": null, "version": "codex-cli 0.154.0"}}`

## Completion

- Status: completed
- Valid runs: 108 / 108
- Invalid infrastructure attempts: 1
- Protocol-excluded replacement attempts: 2

## Strategy summaries

| Configuration | Successes | Mean task success | Bootstrap 95% CI | Median wall ms | Median tokens | Median tools | Median concurrency factor |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| parallel2-codex | 15/36 | 0.4167 | [0.1944, 0.6389] | 1.068e+05 | 2.305e+05 | 14.67 | 1.324 |
| single-codex | 21/36 | 0.5833 | [0.3333, 0.8333] | 4.967e+04 | 8.312e+04 | 5.667 | undefined |
| staged-codex | 15/36 | 0.4167 | [0.1944, 0.6389] | 1.081e+05 | 1.566e+05 | 9.5 | 0.9841 |

## Paired task differences

Positive values mean the left-named configuration has the larger metric.

| Pair | Metric | Mean difference | Median difference | Bootstrap 95% CI | Paired tasks |
| --- | --- | ---: | ---: | --- | ---: |
| parallel2-codex_minus_single-codex | official_success | -0.1667 | 0 | [-0.3056, -0.05556] | 12 |
| parallel2-codex_minus_single-codex | task_wall_time_ms | 5.631e+04 | 5.915e+04 | [4.278e+04, 7.151e+04] | 12 |
| parallel2-codex_minus_single-codex | total_tokens | 1.46e+05 | 1.484e+05 | [1.299e+05, 1.647e+05] | 11 |
| parallel2-codex_minus_single-codex | provider_tool_calls | 8.139 | 8.5 | [6.694, 9.5] | 12 |
| parallel2-codex_minus_staged-codex | official_success | -4.626e-18 | 0 | [-0.08333, 0.08333] | 12 |
| parallel2-codex_minus_staged-codex | task_wall_time_ms | 3401 | 661.3 | [-7411, 1.681e+04] | 12 |
| parallel2-codex_minus_staged-codex | total_tokens | 7.132e+04 | 6.743e+04 | [5.902e+04, 8.432e+04] | 11 |
| parallel2-codex_minus_staged-codex | provider_tool_calls | 4.833 | 4.667 | [3.361, 6.278] | 12 |
| single-codex_minus_staged-codex | official_success | 0.1667 | 0 | [0.02778, 0.3333] | 12 |
| single-codex_minus_staged-codex | task_wall_time_ms | -5.291e+04 | -5.651e+04 | [-6.1e+04, -4.38e+04] | 12 |
| single-codex_minus_staged-codex | total_tokens | -6.942e+04 | -7.318e+04 | [-8.254e+04, -5.497e+04] | 12 |
| single-codex_minus_staged-codex | provider_tool_calls | -3.306 | -3.5 | [-4.278, -2.278] | 12 |

Confidence intervals are descriptive task-cluster bootstrap intervals, not automatic significance claims.

## Corrections and parallel candidates

- Staged correction requests: 0.02778 of 36 eligible runs.
- Patch changed among corrections: 0.
- Visible-test improvement among corrections: 0.
- Pre-correction hidden verification: unavailable by design.
- Parallel runs: 36; mean completed candidate count: 1.722; candidate failures: 3.
- Selection distribution: `{"A": 18, "B": 6}`.
- Unselected candidates were never officially verified.

## Integrity and limitations

Official independent verification is the binary correctness outcome. Repetitions are averaged within task × configuration before aggregation, so repeated runs are not treated as independent task samples. Resource summaries include all valid runs; successful-only summaries are separately labeled. Unselected parallel candidates were never officially verified.

This study has 12 project-authored tasks and three repetitions, heuristic difficulty labels, version-dependent provider behavior, and local-environment latency. It has no GPU telemetry and does not infer TTFT, ITL, or generation throughput when unavailable. Results do not generalize to all coding workloads.
