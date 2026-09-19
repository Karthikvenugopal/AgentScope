import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../src/api/client";
import { AppRoutes } from "../src/router/routes";
import { mount } from "./helpers";
import { event, metrics, patch, run, task } from "./fixtures";
import { MetricsPanel } from "../src/features/metrics/MetricsPanel";
import { TraceViewer } from "../src/features/trace/TraceViewer";

beforeEach(() => {
  vi.spyOn(api, "strategies").mockResolvedValue([
    {
      id: "single",
      name: "Single Agent",
      supported_roles: ["implementer"],
      worker_counts: [1],
      available: true,
    },
    {
      id: "planner_implementer_reviewer",
      name: "Planner → Implementer → Reviewer",
      supported_roles: ["planner", "implementer", "reviewer"],
      worker_counts: [1],
      available: true,
    },
    {
      id: "parallel_implementers",
      name: "Parallel Implementers",
      supported_roles: ["planner", "implementers", "reviewer"],
      worker_counts: [2, 3],
      available: true,
    },
  ]);
  vi.spyOn(api, "agents").mockResolvedValue([{ id: "mock", available: true }]);
  vi.spyOn(api, "ready").mockResolvedValue({
    status: "ready",
    database: "healthy",
  });
  vi.spyOn(api, "tasks").mockResolvedValue([task]);
  vi.spyOn(api, "task").mockResolvedValue(task);
  vi.spyOn(api, "runs").mockResolvedValue({
    items: [run],
    limit: 20,
    offset: 0,
  });
  vi.spyOn(api, "run").mockResolvedValue(run);
  vi.spyOn(api, "trace").mockResolvedValue({
    events: [event(1, "run_started"), event(2, "run_completed")],
    next_after_sequence: 2,
  });
  vi.spyOn(api, "patch").mockResolvedValue(patch);
  const progress = {
    planned: 6,
    completed: 6,
    benchmark_successes: 5,
    benchmark_failures: 1,
    infrastructure_failures: 0,
    protocol_exclusions: 0,
    pending: 0,
    running: 0,
  };
  vi.spyOn(api, "experiments").mockResolvedValue([
    {
      experiment_id: "strategy-study-pilot-v1",
      name: "Strategy pilot",
      status: "completed",
      benchmark_name: "AgentScope Benchmark",
      benchmark_version: "0.1",
      spec_hash: "a".repeat(64),
      created_at: "2026-09-18T12:00:00Z",
      progress,
    },
  ]);
  vi.spyOn(api, "experiment").mockResolvedValue({
    experiment_id: "strategy-study-pilot-v1",
    name: "Strategy pilot",
    status: "completed",
    benchmark_name: "AgentScope Benchmark",
    benchmark_version: "0.1",
    benchmark_manifest_hash: "b".repeat(64),
    spec_hash: "a".repeat(64),
    created_at: "2026-09-18T12:00:00Z",
    progress,
    research_question: "How does orchestration affect measured outcomes?",
    pause_reason: null,
    configurations: [
      { configuration_id: "single-codex", strategy: "single", provider: "codex" },
      { configuration_id: "staged-codex", strategy: "planner_implementer_reviewer", provider: "codex" },
    ],
    schedule: [
      { scheduled_order: 1, configuration_id: "single-codex", task_id: task.id, repetition: 1, status: "completed", valid_run_id: run.run_id },
      { scheduled_order: 2, configuration_id: "staged-codex", task_id: task.id, repetition: 1, status: "completed", valid_run_id: "staged-run" },
    ],
    analysis: {
      valid_runs: 2,
      invalid_attempts: 0,
      task_aggregates: [
        { task_id: task.id, configuration_id: "single-codex", valid_repetitions: 1, successes: 1, success_probability: 1, task_wall_time_ms: 1000, total_tokens: 100 },
        { task_id: task.id, configuration_id: "staged-codex", valid_repetitions: 1, successes: 0, success_probability: 0, task_wall_time_ms: 2000, total_tokens: 300 },
      ],
      strategy_summary: {
        "single-codex": { mean_task_success_probability: 1, success_bootstrap_95_ci: [1, 1], all_runs: { task_wall_time_ms: { mean: 1000, median: 1000, p25: 1000, p75: 1000 }, total_tokens: { mean: 100, median: 100, p25: 100, p75: 100 } } },
        "staged-codex": { mean_task_success_probability: 0, success_bootstrap_95_ci: [0, 0], all_runs: { task_wall_time_ms: { mean: 2000, median: 2000, p25: 2000, p75: 2000 }, total_tokens: { mean: 300, median: 300, p25: 300, p75: 300 } } },
      },
    },
  });
});

it("submits bounded parallel role configuration", async () => {
  const create = vi
    .spyOn(api, "create")
    .mockResolvedValue({ run_id: run.run_id, status: "queued" });
  const user = userEvent.setup();
  mount(<AppRoutes />, "/runs/new");
  await screen.findByRole("option", { name: "Parallel Implementers" });
  await user.selectOptions(
    screen.getByLabelText("Execution strategy"),
    "parallel_implementers",
  );
  expect(screen.getByLabelText("Planner")).toBeEnabled();
  await user.selectOptions(screen.getByLabelText("Parallel implementers"), "2");
  await user.click(screen.getByRole("button", { name: /Run Agent/ }));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        strategy: "parallel_implementers",
        configuration: {
          planner: { agent: "mock" },
          implementers: { agent: "mock", count: 2 },
          reviewer: { agent: "mock" },
        },
      }),
    ),
  );
});

it("offers only available providers and submits a bounded model configuration", async () => {
  vi.mocked(api.agents).mockResolvedValue([
    { id: "mock", available: true },
    { id: "codex", available: true, version: "codex-cli 0.154.0" },
    { id: "claude-code", available: false, reason: "authentication_expired" },
  ]);
  const create = vi
    .spyOn(api, "create")
    .mockResolvedValue({ run_id: run.run_id, status: "queued" });
  mount(<AppRoutes />, "/runs/new");
  const user = userEvent.setup();
  await screen.findByRole("option", { name: "codex" });
  expect(screen.getByRole("option", { name: /claude-code/ })).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Agent"), "codex");
  await user.type(screen.getByLabelText("Model (optional)"), "test-model");
  await user.click(screen.getByRole("button", { name: /Run Agent/ }));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith({
      task_id: task.id,
      agent: "codex",
      strategy: "single",
      configuration: { model: "test-model" },
    }),
  );
});

describe("new run workflow", () => {
  it("loads task metadata, prevents duplicate POSTs, and navigates to the created run", async () => {
    let release!: (value: { run_id: string; status: "queued" }) => void;
    const create = vi.spyOn(api, "create").mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const user = userEvent.setup();
    mount(<AppRoutes />, "/runs/new");
    expect(
      await screen.findByRole("heading", { name: task.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(task.repository.source)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /Run Agent/ });
    await user.dblClick(button);
    expect(create).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Submitting/ })).toBeDisabled();
    release({ run_id: run.run_id, status: "queued" });
    expect(await screen.findByText(run.run_id)).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Verification passed" }),
    ).toBeInTheDocument();
  });
  it("explains task/request failures and does not render an empty form", async () => {
    vi.mocked(api.tasks).mockRejectedValue(
      new ApiError("service_unavailable", "unavailable", 503),
    );
    mount(<AppRoutes />, "/runs/new");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "backend is unavailable",
    );
    expect(
      screen.queryByRole("button", { name: /Run Agent/ }),
    ).not.toBeInTheDocument();
  });
});

describe("run records", () => {
  it.each([
    "queued",
    "running",
    "verifying",
    "completed",
    "verification_failed",
    "failed",
    "timed_out",
  ] as const)(
    "renders %s without hiding execution evidence",
    async (status) => {
      const live = ["queued", "running", "verifying"].includes(status);
      const failure = ["failed", "verification_failed", "timed_out"].includes(
        status,
      );
      vi.mocked(api.run).mockResolvedValue({
        ...run,
        status,
        verification: live
          ? null
          : failure
            ? {
                ...run.verification!,
                passed: false,
                passed_tests: 0,
                failed_tests: 3,
              }
            : run.verification,
        metrics: live ? null : metrics,
        failure_reason: failure ? "Run did not complete successfully" : null,
      });
      mount(<AppRoutes />, `/runs/${run.run_id}`);
      expect(await screen.findByText(run.run_id)).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Agent trajectory" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Resulting patch" }),
      ).toBeInTheDocument();
      if (failure)
        expect(screen.getByRole("alert")).toHaveTextContent(
          "Available execution evidence",
        );
      if (live)
        expect(
          screen.getByText("Live · updating every second"),
        ).toBeInTheDocument();
    },
  );
  it("renders independent verification, metrics, readable diff, and artifact hashes", async () => {
    mount(<AppRoutes />, `/runs/${run.run_id}`);
    expect(await screen.findByText("3 / 3 passed")).toBeInTheDocument();
    expect(
      screen.getByText(/Tests invoked by the agent do not determine/),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Unified diff")).toHaveTextContent(
      '+return {"status": "ok"}',
    );
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  });
  it("handles missing runs and missing patches distinctly", async () => {
    vi.mocked(api.run).mockRejectedValue(
      new ApiError("run_not_found", "missing", 404),
    );
    const view = mount(<AppRoutes />, "/runs/missing");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "run could not be found",
    );
    view.unmount();
    vi.mocked(api.run).mockResolvedValue(run);
    vi.mocked(api.patch).mockRejectedValue(
      new ApiError("artifact_not_found", "missing", 404),
    );
    mount(<AppRoutes />, "/runs/test-run");
    expect(
      await screen.findByText("No patch is available for this run."),
    ).toBeInTheDocument();
  });
});

describe("measured metrics and event semantics", () => {
  it("does not convert unmeasured inference into zero", () => {
    mount(<MetricsPanel metrics={metrics} />);
    expect(screen.getByText("1.25 s")).toBeInTheDocument();
    expect(screen.getByText(/Not measured · Token usage/)).toBeInTheDocument();
    expect(screen.queryByText("0 tokens")).not.toBeInTheDocument();
  });
  it("displays genuinely measured zero and nonzero inference values", () => {
    mount(
      <MetricsPanel
        metrics={{
          ...metrics,
          inference: { input_tokens: 0, output_tokens: 12, mean_ttft_ms: 430 },
        }}
      />,
    );
    expect(
      screen.getByText("Input tokens").nextElementSibling,
    ).toHaveTextContent("0");
    expect(screen.getByText("TTFT").nextElementSibling).toHaveTextContent(
      "430 ms",
    );
    expect(screen.queryByText("ITL")).not.toBeInTheDocument();
  });
  it("orders and deduplicates actual trace events and expands tool payloads", async () => {
    const user = userEvent.setup();
    mount(
      <TraceViewer
        live={false}
        events={[
          event(3, "agent_completed"),
          event(1, "run_started"),
          event(2),
          event(2),
        ]}
      />,
    );
    const items = within(
      screen.getByRole("list", { name: "Execution trace" }),
    ).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Run started");
    await user.click(screen.getByText("Tool → read_file"));
    expect(screen.getByText("arguments")).toBeInTheDocument();
    expect(screen.getByText(/app.py/)).toBeInTheDocument();
  });
});

describe("history and dashboard", () => {
  it("sends server filters and pagination and links rows to details", async () => {
    vi.mocked(api.runs).mockImplementation(async (filters) => ({
      items: Array.from({ length: 10 }, (_, i) => ({
        ...run,
        run_id: `run-${i}`,
      })),
      limit: 10,
      offset: filters.offset ?? 0,
    }));
    const user = userEvent.setup();
    mount(<AppRoutes />, "/runs");
    await screen.findByRole("link", { name: "run-0" });
    await user.selectOptions(screen.getByLabelText("Status"), "completed");
    await waitFor(() =>
      expect(api.runs).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "completed", offset: 0 }),
        expect.any(AbortSignal),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(api.runs).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 10 }),
        expect.any(AbortSignal),
      ),
    );
    await user.selectOptions(screen.getByLabelText("Task"), task.id);
    await user.selectOptions(screen.getByLabelText("Agent"), "mock");
    await user.selectOptions(screen.getByLabelText("Strategy"), "single");
    await waitFor(() =>
      expect(api.runs).toHaveBeenLastCalledWith(
        expect.objectContaining({
          task_id: task.id,
          agent: "mock",
          strategy: "single",
          offset: 0,
        }),
        expect.any(AbortSignal),
      ),
    );
    await user.click(screen.getByRole("link", { name: "run-0" }));
    expect(await screen.findByText("run-0")).toBeInTheDocument();
  });
  it("labels dashboard statistics as a bounded snapshot and handles no runs", async () => {
    vi.mocked(api.runs).mockResolvedValue({ items: [], limit: 20, offset: 0 });
    mount(<AppRoutes />);
    expect(
      await screen.findByText(/Snapshot of the latest 0 runs/),
    ).toBeInTheDocument();
    expect(screen.getByText(/No runs in this view/)).toBeInTheDocument();
  });
});

describe("controlled experiments", () => {
  it("renders progress without inventing an overall winner", async () => {
    mount(<AppRoutes />, "/experiments");
    expect(await screen.findByRole("link", { name: "Strategy pilot" })).toBeInTheDocument();
    expect(screen.getByText("6 / 6")).toBeInTheDocument();
    expect(screen.queryByText(/winner/i)).not.toBeInTheDocument();
  });

  it("renders task-cluster summaries, matrix outcomes, and run links", async () => {
    mount(<AppRoutes />, "/experiments/strategy-study-pilot-v1");
    expect(await screen.findByRole("table", { name: "Strategy summaries" })).toBeInTheDocument();
    const matrix = screen.getByRole("table", { name: "Experiment run matrix" });
    expect(within(matrix).getByText("1/1")).toBeInTheDocument();
    expect(within(matrix).getByText("0/1")).toBeInTheDocument();
    expect(within(matrix).getAllByRole("link", { name: "run 1" })[0]).toHaveAttribute(
      "href",
      `/runs/${run.run_id}`,
    );
    expect(screen.getByText(/bootstrap tasks, not individual runs/i)).toBeInTheDocument();
  });
});
