# Phase 9 strategy study pilot v1

> Technical experiment output, not a leaderboard or overall ranking.

## Research question

Does the frozen strategy-study schedule, telemetry, isolation, persistence, and analysis pipeline operate correctly before the full matrix?

## Design

- Benchmark: AgentScope Benchmark v0.1
- Manifest SHA-256: `132a2070b12f143d889a2b88af200063800194162835bbdd3eea01aef8f38f80`
- Tasks: 2
- Configurations: 3
- Repetitions per task/configuration: 1
- Random schedule seed: 20260918
- Task-cluster bootstrap seed: 20260919
- Cross-run concurrency: 1; internal parallel strategy concurrency remains treatment.

## Completion

- Status: completed
- Valid runs: 6 / 6
- Invalid infrastructure attempts: 0

## Strategy summaries

| Configuration | Mean task success | Bootstrap 95% CI | Median wall ms | Median tokens |
| --- | ---: | --- | ---: | ---: |
| parallel2-codex | 1 | [1, 1] | 7.86e+04 | 2.185e+05 |
| single-codex | 1 | [1, 1] | 2.836e+04 | 6.716e+04 |
| staged-codex | 1 | [1, 1] | 6.295e+04 | 1.271e+05 |

Paired differences are in `pairwise_comparisons.json`; positive values mean the left-named configuration has the larger metric. Confidence intervals are descriptive task-cluster bootstrap intervals, not automatic significance claims.

## Integrity and limitations

Official independent verification is the binary correctness outcome. Repetitions are averaged within task × configuration before aggregation, so repeated runs are not treated as independent task samples. Resource summaries include all valid runs; successful-only summaries are separately labeled. Unselected parallel candidates were never officially verified.

This study has 12 project-authored tasks and three repetitions, heuristic difficulty labels, version-dependent provider behavior, and local-environment latency. It has no GPU telemetry and does not infer TTFT, ITL, or generation throughput when unavailable. Results do not generalize to all coding workloads.
