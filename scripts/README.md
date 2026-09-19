# Scripts

Experiment tooling is implemented by the installed Python CLI. The Phase 10
`generate_research_artifacts.py` command is deliberately offline: it recomputes
task-cluster summaries from frozen CSV exports, validates them against checked-in
JSON results, and regenerates the publication SVG figures without a database,
Docker, credentials, or provider invocation.

```bash
PYTHON=.venv/bin/python make research-artifacts
```
