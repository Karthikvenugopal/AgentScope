# Benchmark task format

Each benchmark is a UTF-8 YAML document named `task.yaml`. Unknown keys are
rejected so misspelled experimental settings cannot silently change a run.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | slug string | Stable task identity |
| `title` | string | Human-readable name |
| `description` | string | Agent-facing problem statement |
| `repository` | string or object | Versionable source repository |
| `setup_command` | string or null | Deterministic environment setup |
| `test_command` | string | Verification entry point |
| `timeout_seconds` | integer | Whole-task time budget |
| `expected_behavior` | string | Outcome used by evaluators/reviewers |
| `version` | string | Task definition revision; defaults to `1` |
| `tags` | string list | Optional selection metadata |
| `language` | string | Catalog/display language |
| `difficulty` | `easy`, `medium`, or `hard` | Rough task metadata, not a measured conclusion |
| `provenance` | object | Source/dataset/version and immutable content hashes |
| `environment` | object | Native or Harbor image/workdir/network mapping |
| `verification` | object | Official test source and verification time budget |

The object form of `repository` has `type` (`local` or `git`), `source`, and
optional `revision` and `subdirectory`. A string is normalized to a local source,
or a git source when it begins with `https://`, `ssh://`, or `git@`.

Execution resolves local repositories and confines them to the benchmark root.
Phase 8's Harbor adapter maps immutable local Harbor packages into this contract;
it does not give providers direct access to a Harbor package.

Official harness runs require `verification.source`, relative to the benchmark
root, and optionally `verification.timeout_seconds` (default 60). The catalog
requires disjoint source trees and rejects symlinks in both. The agent receives a
task view with `verification=None`; only the harness resolves the official source.
The task's original `test_command` remains the agent-visible test command.

```yaml
verification:
  source: verification/incorrect_api_response
  timeout_seconds: 30
  kind: pytest
```

For `kind: harbor`, `source` points only to the imported hidden `tests/` tree,
and `command` records the official Harbor verifier script. The agent-visible
fixture is separately materialized from `environment/`; `solution/`, `tests/`,
and the environment Dockerfile are excluded. See [Phase 8](phase8.md).

The frozen suite index is `benchmarks/manifest.json`. A catalog load recomputes
task, environment, and verifier hashes and fails closed on drift; use the explicit
`benchmark freeze` command only when intentionally publishing a new task version.
