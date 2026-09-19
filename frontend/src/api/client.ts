import createClient from "openapi-fetch";
import type { components, paths } from "./generated/schema";

export type Run = components["schemas"]["RunDetail"];
export type RunSummary = components["schemas"]["RunSummary"];
export type Status = components["schemas"]["RunStatus"];
export type Metrics = components["schemas"]["RunMetrics"];
export type TraceEvent = components["schemas"]["PublicTraceEvent"];
export type TracePage = components["schemas"]["TracePage"];
export type RunFilters = NonNullable<
  paths["/api/v1/runs"]["get"]["parameters"]["query"]
>;
export interface ExperimentProgress {
  planned: number;
  completed: number;
  benchmark_successes: number;
  benchmark_failures: number;
  infrastructure_failures: number;
  protocol_exclusions: number;
  pending: number;
  running: number;
}
export interface ExperimentListItem {
  experiment_id: string;
  name: string;
  status: string;
  benchmark_name: string;
  benchmark_version: string;
  spec_hash: string;
  created_at: string;
  progress: ExperimentProgress;
}
export interface ExperimentDetail extends ExperimentListItem {
  research_question: string;
  benchmark_manifest_hash: string;
  pause_reason: string | null;
  configurations: Array<{
    configuration_id: string;
    strategy: string;
    provider: string;
  }>;
  schedule: Array<{
    scheduled_order: number;
    configuration_id: string;
    task_id: string;
    repetition: number;
    status: string;
    valid_run_id: string | null;
  }>;
  analysis: {
    valid_runs: number;
    invalid_attempts: number;
    task_aggregates: Array<{
      task_id: string;
      configuration_id: string;
      valid_repetitions: number;
      successes: number;
      success_probability: number;
      task_wall_time_ms: number | null;
      total_tokens: number | null;
    }>;
    strategy_summary: Record<
      string,
      {
        mean_task_success_probability: number | null;
        success_bootstrap_95_ci: [number | null, number | null];
        all_runs: Record<
          string,
          { mean: number | null; median: number | null; p25: number | null; p75: number | null }
        >;
      }
    >;
  };
}

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

// Same-origin by default: Vite/Compose proxies route to the backend.
const transport = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL || window.location.origin,
  fetch: (request) => globalThis.fetch(request),
});
function unwrap<T>(result: {
  data?: T;
  error?: unknown;
  response: Response;
}): T {
  if (!result.response.ok) {
    const error = result.error as
      components["schemas"]["ErrorResponse"] | undefined;
    throw new ApiError(
      error?.error?.code ?? "service_unavailable",
      error?.error?.message ?? "The API could not complete this request.",
      result.response.status,
    );
  }
  return result.data as T;
}

export const api = {
  strategies: async (signal?: AbortSignal) =>
    unwrap(await transport.GET("/api/v1/strategies", { signal })),
  agents: async (signal?: AbortSignal) =>
    unwrap(await transport.GET("/api/v1/agents", { signal })),
  tasks: async (signal?: AbortSignal) =>
    unwrap(await transport.GET("/api/v1/tasks", { signal })),
  experiments: async (signal?: AbortSignal) =>
    unwrap(
      await transport.GET("/api/v1/experiments", { signal }),
    ) as unknown as ExperimentListItem[],
  experiment: async (id: string, signal?: AbortSignal) =>
    unwrap(
      await transport.GET("/api/v1/experiments/{experiment_id}", {
        params: { path: { experiment_id: id } },
        signal,
      }),
    ) as unknown as ExperimentDetail,
  task: async (id: string, signal?: AbortSignal) =>
    unwrap(
      await transport.GET("/api/v1/tasks/{task_id}", {
        params: { path: { task_id: id } },
        signal,
      }),
    ),
  runs: async (query: RunFilters, signal?: AbortSignal) =>
    unwrap(await transport.GET("/api/v1/runs", { params: { query }, signal })),
  run: async (id: string, signal?: AbortSignal) =>
    unwrap(
      await transport.GET("/api/v1/runs/{run_id}", {
        params: { path: { run_id: id } },
        signal,
      }),
    ),
  create: async (body: components["schemas"]["CreateRunRequest"]) =>
    unwrap(await transport.POST("/api/v1/runs", { body })),
  trace: async (id: string, after: number, signal?: AbortSignal) =>
    unwrap(
      await transport.GET("/api/v1/runs/{run_id}/trace", {
        params: {
          path: { run_id: id },
          query: { after_sequence: after, limit: 100 },
        },
        signal,
      }),
    ),
  patch: async (id: string, signal?: AbortSignal) =>
    unwrap(
      await transport.GET("/api/v1/runs/{run_id}/patch", {
        params: { path: { run_id: id } },
        parseAs: "text",
        signal,
      }),
    ),
  ready: async (signal?: AbortSignal) =>
    unwrap(await transport.GET("/ready", { signal })),
};
