// Generated from FastAPI OpenAPI. Run npm run generate-api; do not edit.
export interface paths {
  "/api/v1/agents": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Discover configured provider runtimes and capabilities */
    get: operations["agents_api_v1_agents_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/experiments": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List controlled experiments and progress */
    get: operations["experiments_api_v1_experiments_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/experiments/{experiment_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Inspect schedule, runs, and task-level analysis */
    get: operations["experiment_api_v1_experiments__experiment_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/runs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List newest runs with bounded pagination and filters */
    get: operations["runs_api_v1_runs_get"];
    put?: never;
    /** Queue an available benchmark strategy run */
    post: operations["create_run_api_v1_runs_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/runs/{run_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Get persisted lifecycle, verification, and metrics */
    get: operations["run_api_v1_runs__run_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/runs/{run_id}/artifacts": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Get artifact sizes and hashes without host paths */
    get: operations["artifacts_api_v1_runs__run_id__artifacts_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/runs/{run_id}/metrics": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Get measured run aggregates; null until available */
    get: operations["metrics_api_v1_runs__run_id__metrics_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/runs/{run_id}/patch": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Get a hash-validated patch */
    get: operations["patch_api_v1_runs__run_id__patch_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/runs/{run_id}/trace": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Poll ordered trace events after a sequence number */
    get: operations["trace_api_v1_runs__run_id__trace_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/strategies": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Discover bounded orchestration architectures */
    get: operations["strategies_api_v1_strategies_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/tasks": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List benchmark metadata without verifier material */
    get: operations["tasks_api_v1_tasks_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/tasks/{task_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Get agent-visible benchmark configuration */
    get: operations["task_api_v1_tasks__task_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/health": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Process liveness */
    get: operations["health_health_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/ready": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Database and coordinator readiness */
    get: operations["ready_ready_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /** ArtifactSummary */
    ArtifactSummary: {
      /** Sha256 */
      sha256: string;
      /** Size Bytes */
      size_bytes: number;
      /** Type */
      type: string;
    };
    /**
     * CreateRunRequest
     * @example {
     *       "agent": "mock",
     *       "configuration": {},
     *       "strategy": "single",
     *       "task_id": "incorrect_api_response"
     *     }
     */
    CreateRunRequest: {
      /**
       * Agent
       * @description mock, codex, claude-code; check /agents for availability
       * @default mock
       */
      agent?: string;
      configuration?: components["schemas"]["RunConfiguration"];
      /**
       * Strategy
       * @description single, planner_implementer_reviewer, parallel_implementers
       * @default single
       */
      strategy?: string;
      /** Task Id */
      task_id: string;
    };
    /** ErrorDetail */
    ErrorDetail: {
      /** Code */
      code: string;
      /** Message */
      message: string;
    };
    /** ErrorResponse */
    ErrorResponse: {
      error: components["schemas"]["ErrorDetail"];
    };
    /** Health */
    Health: {
      /**
       * Status
       * @default alive
       * @constant
       */
      status?: "alive";
    };
    /** ImplementersConfiguration */
    ImplementersConfiguration: {
      /**
       * Agent
       * @default mock
       * @enum {string}
       */
      agent?: "mock" | "codex" | "claude-code";
      /**
       * Count
       * @default 3
       * @enum {integer}
       */
      count?: 2 | 3;
      /** Model */
      model?: string | null;
    };
    /** InferenceMetrics */
    InferenceMetrics: {
      /** Cache Creation Input Tokens */
      cache_creation_input_tokens?: number | null;
      /** Cached Input Tokens */
      cached_input_tokens?: number | null;
      /** Input Tokens */
      input_tokens?: number | null;
      /** Mean Itl Ms */
      mean_itl_ms?: number | null;
      /** Mean Ttft Ms */
      mean_ttft_ms?: number | null;
      /** Model Calls */
      model_calls?: number | null;
      /** Model Latency Ms */
      model_latency_ms?: number | null;
      /** Output Tokens */
      output_tokens?: number | null;
      /** Output Tokens Per Second */
      output_tokens_per_second?: number | null;
      /** Provenance */
      provenance?: {
        [key: string]: components["schemas"]["MetricSource"];
      };
      /** Reasoning Tokens */
      reasoning_tokens?: number | null;
      /** Time To First Provider Output Ms */
      time_to_first_provider_output_ms?: number | null;
      /** Total Tokens */
      total_tokens?: number | null;
    };
    JsonValue: unknown;
    /** MetricSource */
    MetricSource: {
      /**
       * Provenance
       * @enum {string}
       */
      provenance: "measured" | "derived" | "unavailable";
      /** Source */
      source?: string | null;
    };
    /** Plan */
    Plan: {
      /** Analysis */
      analysis: string;
      /** Files Likely Relevant */
      files_likely_relevant?: string[];
      /** Steps */
      steps: string[];
    };
    /** ProviderAvailability */
    ProviderAvailability: {
      /** Available */
      available: boolean;
      capabilities?: components["schemas"]["ProviderCapabilities"] | null;
      /** Id */
      id: string;
      /** Reason */
      reason?: string | null;
      /** Version */
      version?: string | null;
    };
    /** ProviderCapabilities */
    ProviderCapabilities: {
      /**
       * Model Request Boundaries
       * @default false
       */
      model_request_boundaries?: boolean;
      /**
       * Model Selection
       * @default true
       */
      model_selection?: boolean;
      /**
       * Per Request Usage
       * @default false
       */
      per_request_usage?: boolean;
      /**
       * Session Continuation
       * @default true
       */
      session_continuation?: boolean;
      /**
       * Session Ids
       * @default true
       */
      session_ids?: boolean;
      /**
       * Streaming Events
       * @default true
       */
      streaming_events?: boolean;
      /**
       * Structured Output
       * @default true
       */
      structured_output?: boolean;
      /**
       * Token Stream Timestamps
       * @default false
       */
      token_stream_timestamps?: boolean;
      /**
       * Token Usage
       * @default true
       */
      token_usage?: boolean;
      /**
       * Tool Events
       * @default true
       */
      tool_events?: boolean;
    };
    /** ProviderMetadata */
    ProviderMetadata: {
      /** Duration Ms */
      duration_ms?: number | null;
      /** Exit Code */
      exit_code?: number | null;
      /** Image */
      image: string;
      /** Image Id */
      image_id: string;
      /** Model */
      model?: string | null;
      /** Process Duration Ms */
      process_duration_ms?: number | null;
      /** Process Finished At */
      process_finished_at?: string | null;
      /** Process Started At */
      process_started_at?: string | null;
      provider: components["schemas"]["ProviderName"];
      /** Session Id */
      session_id?: string | null;
      /** Time To First Provider Output Ms */
      time_to_first_provider_output_ms?: number | null;
      /** Version */
      version: string;
    };
    /**
     * ProviderName
     * @enum {string}
     */
    ProviderName: "codex" | "claude-code";
    /**
     * PublicTraceEvent
     * @description Ordered event envelope. Payload excludes private verifier diagnostics.
     */
    PublicTraceEvent: {
      /** Event Id */
      event_id: string;
      /** Event Type */
      event_type: string;
      /** Payload */
      payload: {
        [key: string]: components["schemas"]["JsonValue"];
      };
      /** Run Id */
      run_id: string;
      /** Sequence Number */
      sequence_number: number;
      /**
       * Timestamp
       * Format: date-time
       */
      timestamp: string;
    };
    /** QueuedRun */
    QueuedRun: {
      /** Run Id */
      run_id: string;
      /**
       * Status
       * @default queued
       * @constant
       */
      status?: "queued";
    };
    /** Readiness */
    Readiness: {
      /**
       * Database
       * @enum {string}
       */
      database: "healthy" | "unavailable";
      /**
       * Status
       * @enum {string}
       */
      status: "ready" | "not_ready";
    };
    /**
     * RepositorySpec
     * @description A repository source plus enough provenance to reproduce it later.
     */
    RepositorySpec: {
      /** Revision */
      revision?: string | null;
      /** Source */
      source: string;
      /** Subdirectory */
      subdirectory?: string | null;
      /** @default local */
      type?: components["schemas"]["RepositoryType"];
    };
    /**
     * RepositoryType
     * @description Repository transports understood by the task format.
     * @enum {string}
     */
    RepositoryType: "local" | "git";
    /** Review */
    Review: {
      /**
       * Decision
       * @enum {string}
       */
      decision: "approve" | "revise";
      /** Issues */
      issues?: string[];
      /**
       * Rationale
       * @default
       */
      rationale?: string;
      /** Selected Candidate */
      selected_candidate?: string | null;
      /** Suggested Changes */
      suggested_changes?: string[];
    };
    /** RoleConfiguration */
    RoleConfiguration: {
      /**
       * Agent
       * @default mock
       * @enum {string}
       */
      agent?: "mock" | "codex" | "claude-code";
      /** Model */
      model?: string | null;
    };
    /** RoleMetrics */
    RoleMetrics: {
      /** Duration Ms */
      duration_ms: number;
      /** Input Tokens */
      input_tokens?: number | null;
      /** Invocations */
      invocations: number;
      /** Output Tokens */
      output_tokens?: number | null;
      /** Tool Calls */
      tool_calls: number;
      /** Total Tokens */
      total_tokens?: number | null;
    };
    /**
     * RunConfiguration
     * @description Only controlled resource limits are configurable; no commands or paths.
     */
    RunConfiguration: {
      /**
       * Command Timeout Seconds
       * @default 60
       */
      command_timeout_seconds?: number;
      implementer?: components["schemas"]["RoleConfiguration"] | null;
      implementers?: components["schemas"]["ImplementersConfiguration"] | null;
      /**
       * Max Agent Turns
       * @default 20
       */
      max_agent_turns?: number;
      /**
       * Max Captured Output Bytes
       * @default 1000000
       */
      max_captured_output_bytes?: number;
      /**
       * Max File Write Bytes
       * @default 1000000
       */
      max_file_write_bytes?: number;
      /**
       * Max Tool Calls
       * @default 100
       */
      max_tool_calls?: number;
      /** Model */
      model?: string | null;
      /**
       * Overall Timeout Seconds
       * @default 600
       */
      overall_timeout_seconds?: number;
      planner?: components["schemas"]["RoleConfiguration"] | null;
      reviewer?: components["schemas"]["RoleConfiguration"] | null;
    };
    /** RunDetail */
    RunDetail: {
      /** Agent */
      agent: string;
      /** Artifacts */
      artifacts?: components["schemas"]["ArtifactSummary"][];
      /** Failure Code */
      failure_code?:
        | ("run_execution_failure" | "verification_failed" | "run_timed_out")
        | null;
      /** Failure Reason */
      failure_reason: string | null;
      /** Finished At */
      finished_at: string | null;
      metrics?: components["schemas"]["RunMetrics"] | null;
      orchestration?: components["schemas"]["StrategyResult"] | null;
      provider?: components["schemas"]["ProviderMetadata"] | null;
      /** Run Id */
      run_id: string;
      /** Started At */
      started_at: string | null;
      status: components["schemas"]["RunStatus"];
      /** Strategy */
      strategy: string;
      /** Task Id */
      task_id: string;
      verification?: components["schemas"]["VerificationSummary"] | null;
    };
    /** RunMetrics */
    RunMetrics: {
      /** Agent Execution Time Ms */
      agent_execution_time_ms: number;
      /** Agent Test Runs */
      agent_test_runs: number;
      /** Agent Test Time Ms */
      agent_test_time_ms: number;
      /** Agent Turns */
      agent_turns: number;
      /** Commands Executed */
      commands_executed: number;
      /** Failed Tool Calls */
      failed_tool_calls: number;
      /** Files Modified */
      files_modified: number;
      inference?: components["schemas"]["InferenceMetrics"];
      /** Lines Added */
      lines_added: number;
      /** Lines Removed */
      lines_removed: number;
      /** Official Tests Failed */
      official_tests_failed: number | null;
      /** Official Tests Passed */
      official_tests_passed: number | null;
      /** Official Tests Total */
      official_tests_total: number | null;
      /** Output Truncations */
      output_truncations: number;
      /** Patch Bytes */
      patch_bytes: number;
      /** Per Tool */
      per_tool: {
        [key: string]: number;
      };
      /** Provider Per Tool */
      provider_per_tool?: {
        [key: string]: number;
      };
      /** Provider Tool Calls */
      provider_tool_calls?: number | null;
      /**
       * Retries
       * @default 0
       */
      retries?: number;
      /** Successful Tool Calls */
      successful_tool_calls: number;
      /** Timeouts */
      timeouts: number;
      /** Tool Calls */
      tool_calls: number;
      /** Tool Failures */
      tool_failures: number;
      /** Total Wall Time Ms */
      total_wall_time_ms: number;
      /** Verification Duration Ms */
      verification_duration_ms: number | null;
      /** Verification Passed */
      verification_passed: boolean | null;
      /** Verification Time Ms */
      verification_time_ms: number;
    };
    /** RunPage */
    RunPage: {
      /** Items */
      items: components["schemas"]["RunSummary"][];
      /** Limit */
      limit: number;
      /** Offset */
      offset: number;
    };
    /**
     * RunStatus
     * @enum {string}
     */
    RunStatus:
      | "queued"
      | "running"
      | "verifying"
      | "verification_failed"
      | "completed"
      | "failed"
      | "timed_out";
    /** RunSummary */
    RunSummary: {
      /** Agent */
      agent: string;
      /** Failure Code */
      failure_code?:
        | ("run_execution_failure" | "verification_failed" | "run_timed_out")
        | null;
      /** Failure Reason */
      failure_reason: string | null;
      /** Finished At */
      finished_at: string | null;
      /** Run Id */
      run_id: string;
      /** Started At */
      started_at: string | null;
      status: components["schemas"]["RunStatus"];
      /** Strategy */
      strategy: string;
      /** Task Id */
      task_id: string;
    };
    /** StrategyCapability */
    StrategyCapability: {
      /** Available */
      available: boolean;
      /** Id */
      id: string;
      /** Name */
      name: string;
      /** Supported Roles */
      supported_roles: string[];
      /** Worker Counts */
      worker_counts: number[];
    };
    /** StrategyMetrics */
    StrategyMetrics: {
      /** Concurrency Factor */
      concurrency_factor?: number | null;
      /**
       * Concurrency Factor Provenance
       * @default derived
       * @constant
       */
      concurrency_factor_provenance?: "derived";
      /** Estimated Cost */
      estimated_cost?: number | null;
      /** Input Tokens */
      input_tokens?: number | null;
      /** Output Tokens */
      output_tokens?: number | null;
      /**
       * Peak Concurrent Agents
       * @default 0
       */
      peak_concurrent_agents?: number;
      /** Peak Concurrent Provider Processes */
      peak_concurrent_provider_processes?: number | null;
      /** Per Role */
      per_role?: {
        [key: string]: components["schemas"]["RoleMetrics"];
      };
      /**
       * Provider Invocations
       * @default 0
       */
      provider_invocations?: number;
      /**
       * Provider Tool Calls
       * @default 0
       */
      provider_tool_calls?: number;
      /**
       * Strategy Wall Time Ms
       * @default 0
       */
      strategy_wall_time_ms?: number;
      /**
       * Summed Execution Time Ms
       * @default 0
       */
      summed_execution_time_ms?: number;
      /** Summed Provider Execution Time Ms */
      summed_provider_execution_time_ms?: number | null;
      /** Total Tokens */
      total_tokens?: number | null;
      /** Wall Clock Provider Execution Time Ms */
      wall_clock_provider_execution_time_ms?: number | null;
    };
    /** StrategyResult */
    StrategyResult: {
      /**
       * Candidate Count
       * @default 0
       */
      candidate_count?: number;
      /** Correction Changed Official Result */
      correction_changed_official_result?: boolean | null;
      /** Correction Changed Patch */
      correction_changed_patch?: boolean | null;
      /** Correction Improved Visible Tests */
      correction_improved_visible_tests?: boolean | null;
      /**
       * Corrections
       * @default 0
       */
      corrections?: number;
      /** Executions */
      executions?: components["schemas"]["SubExecution"][];
      metrics?: components["schemas"]["StrategyMetrics"];
      plan?: components["schemas"]["Plan"] | null;
      review?: components["schemas"]["Review"] | null;
      /** Selected Candidate */
      selected_candidate?: string | null;
      /**
       * Strategy
       * @enum {string}
       */
      strategy:
        "single" | "planner_implementer_reviewer" | "parallel_implementers";
    };
    /** SubExecution */
    SubExecution: {
      /** Candidate Id */
      candidate_id?: string | null;
      /** Duration Ms */
      duration_ms: number;
      /** Execution Id */
      execution_id: string;
      /** Failure Reason */
      failure_reason?: string | null;
      /**
       * Files Changed
       * @default []
       */
      files_changed?: string[];
      /**
       * Finished At
       * Format: date-time
       */
      finished_at: string;
      inference?: components["schemas"]["InferenceMetrics"];
      /**
       * Output
       * @default
       */
      output?: string;
      /** Parent Execution Id */
      parent_execution_id: string;
      /**
       * Patch
       * @default
       */
      patch?: string;
      /** Provider */
      provider: string;
      provider_metadata?: components["schemas"]["ProviderMetadata"] | null;
      /**
       * Role
       * @enum {string}
       */
      role: "planner" | "implementer" | "reviewer" | "correction";
      /**
       * Started At
       * Format: date-time
       */
      started_at: string;
      /**
       * Status
       * @enum {string}
       */
      status: "completed" | "failed" | "timed_out";
      /**
       * Tool Calls
       * @default 0
       */
      tool_calls?: number;
      /** Visible Test Exit Code */
      visible_test_exit_code?: number | null;
      /**
       * Visible Test Output
       * @default
       */
      visible_test_output?: string;
      /**
       * Visible Test Output Truncated
       * @default false
       */
      visible_test_output_truncated?: boolean;
      /**
       * Visible Test Timed Out
       * @default false
       */
      visible_test_timed_out?: boolean;
    };
    /** TaskDetail */
    TaskDetail: {
      /** Dataset */
      dataset: string;
      /** Dataset Version */
      dataset_version: string;
      /** Description */
      description: string;
      /** Difficulty */
      difficulty: string;
      /** Expected Behavior */
      expected_behavior: string;
      /** Id */
      id: string;
      /** Language */
      language: string;
      repository: components["schemas"]["RepositorySpec"];
      /** Setup Command */
      setup_command: string | null;
      /** Source */
      source: string;
      /** Tags */
      tags: string[];
      /** Task Hash */
      task_hash: string | null;
      /** Test Command */
      test_command: string;
      /** Timeout Seconds */
      timeout_seconds: number;
      /** Title */
      title: string;
      /** Version */
      version: string;
    };
    /** TaskMetadata */
    TaskMetadata: {
      /** Dataset */
      dataset: string;
      /** Dataset Version */
      dataset_version: string;
      /** Description */
      description: string;
      /** Difficulty */
      difficulty: string;
      /** Id */
      id: string;
      /** Language */
      language: string;
      /** Source */
      source: string;
      /** Tags */
      tags: string[];
      /** Task Hash */
      task_hash: string | null;
      /** Title */
      title: string;
      /** Version */
      version: string;
    };
    /** TracePage */
    TracePage: {
      /** Events */
      events: components["schemas"]["PublicTraceEvent"][];
      /** Next After Sequence */
      next_after_sequence: number;
    };
    /** VerificationSummary */
    VerificationSummary: {
      /** Duration Ms */
      duration_ms: number;
      /** Exit Code */
      exit_code: number | null;
      /** Failed Tests */
      failed_tests: number | null;
      /** Passed */
      passed: boolean;
      /** Passed Tests */
      passed_tests: number | null;
      /** Timed Out */
      timed_out: boolean;
      /** Total Tests */
      total_tests: number | null;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  agents_api_v1_agents_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProviderAvailability"][];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  experiments_api_v1_experiments_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            [key: string]: unknown;
          }[];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  experiment_api_v1_experiments__experiment_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        experiment_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            [key: string]: unknown;
          };
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  runs_api_v1_runs_get: {
    parameters: {
      query?: {
        limit?: number;
        offset?: number;
        task_id?: string | null;
        agent?: string | null;
        strategy?: string | null;
        status?: components["schemas"]["RunStatus"] | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunPage"];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  create_run_api_v1_runs_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateRunRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["QueuedRun"];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  run_api_v1_runs__run_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunDetail"];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  artifacts_api_v1_runs__run_id__artifacts_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ArtifactSummary"][];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  metrics_api_v1_runs__run_id__metrics_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunMetrics"] | null;
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  patch_api_v1_runs__run_id__patch_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "text/x-diff": string;
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  trace_api_v1_runs__run_id__trace_get: {
    parameters: {
      query?: {
        after_sequence?: number;
        limit?: number;
      };
      header?: never;
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TracePage"];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  strategies_api_v1_strategies_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["StrategyCapability"][];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  tasks_api_v1_tasks_get: {
    parameters: {
      query?: {
        source?: string | null;
        dataset?: string | null;
        language?: string | null;
        difficulty?: string | null;
        tag?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TaskMetadata"][];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  task_api_v1_tasks__task_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        task_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TaskDetail"];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  health_health_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Health"];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Required dependency unavailable or queue full */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
    };
  };
  ready_ready_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Readiness"];
        };
      };
      /** @description Task, run, or artifact not found */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Artifact integrity failure */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Request body too large */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Invalid request, configuration, or unsupported agent/strategy */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ErrorResponse"];
        };
      };
      /** @description Service Unavailable */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Readiness"];
        };
      };
    };
  };
}
