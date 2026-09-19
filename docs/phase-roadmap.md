# Delivery roadmap

AgentScope is delivered in independently testable phases. Phases 1 through 10 are
complete. Phase 10 publishes the final research report and reproducible figures
without changing the frozen Phase 8 benchmark or rerunning the Phase 9 study.

1. **Foundation (complete):** repository skeleton, task schema/catalog,
   Docker/local workspaces, process runtime, mock coding agent.
2. **Single-agent harness (complete):** controlled tools, limits, lifecycle
   orchestration, structured trace events, and local artifact export.
3. **Verification and state (complete):** independent tests, telemetry aggregation, and
   PostgreSQL persistence.
4. **Backend API (complete):** typed FastAPI task/run/metric endpoints and bounded execution.
5. **Research dashboard (complete):** React, TypeScript, Vite, generated API types,
   live trajectory polling, independent verdicts, metrics, patches, and Vitest.
6. **Real providers (complete, revised scope):** isolated Codex and Claude Code,
   sanitized provider events, truthful usage and provenance, availability API/UI.
7. **Agent architectures (complete):** single, planner/implementer/reviewer with
   one correction, and two/three isolated parallel implementers; mixed providers,
   selected-only official verification, hierarchical traces/persistence,
   per-role and concurrency metrics, strategy API/UI, and live demonstrations.
8. **Benchmark interoperability (complete):** current Harbor task import and
   official verifier mapping, hidden solution isolation, ATIF export, strong
   provenance, AgentScope Benchmark v0.1, validation gate, catalog API/UI, and
   external Terminal-Bench 2.1 smoke execution.
9. **Controlled experiments (complete):** versioned specifications, seeded
   schedules, sequential resumable execution, validity/replacement ledger,
   task-cluster bootstrap intervals, paired comparisons, portable result exports,
   and minimal experiment inspection UI.
10. **Research release (complete):** compact systems report, seven offline-generated
    research figures, telemetry-completeness and trace audits, technical landing page,
    resume summary, and reproducibility checks against frozen exports.

Leaderboards, marketing claims, public release automation, cloud deployment,
distributed orchestration, and Kubernetes remain intentionally unimplemented.

Later phases must build on the Phase 3 verification contracts, Phase 7 strategy
hierarchy, and frozen Phase 8 provenance rather than putting provider or
orchestration behavior into workspace or deterministic evaluation code. See
[Phase 8](phase8.md), [Phase 9](phase9.md), and the
[final research report](research-report.md).
