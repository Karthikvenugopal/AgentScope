import { classes } from "../lib/styles";
import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAgents, useTask, useTasks, useStrategies } from "../api/queries";
import { ErrorNotice, Loading, Empty } from "../components/Feedback";

export function NewRunPage() {
  const tasks = useTasks();
  const agents = useAgents();
  const strategies = useStrategies();
  const [strategy, setStrategy] = useState("single");
  const [planner, setPlanner] = useState<"mock" | "codex" | "claude-code">(
    "mock",
  );
  const [implementer, setImplementer] = useState<
    "mock" | "codex" | "claude-code"
  >("mock");
  const [reviewer, setReviewer] = useState<"mock" | "codex" | "claude-code">(
    "mock",
  );
  const [count, setCount] = useState<2 | 3>(3);
  const workerCounts = strategies.data?.find((s) => s.id === "parallel_implementers")?.worker_counts;
  const effectiveCount = count === 3 && workerCounts && !workerCounts.includes(3) ? 2 : count;
  const [agent, setAgent] = useState("mock");
  const [model, setModel] = useState("");
  const selectedAgents =
    strategy === "single" ? [agent] : [planner, implementer, reviewer];
  const available = selectedAgents.every((id) =>
    agents.data?.some((a) => a.id === id && a.available),
  );
  const usesRealProvider = selectedAgents.some((id) => id !== "mock");
  const [selection, setSelection] = useState("");
  const id = selection || tasks.data?.[0]?.id || "";
  const task = useTask(id);
  const navigate = useNavigate();
  const cache = useQueryClient();
  const submitted = useRef(false);
  const create = useMutation({
    mutationFn: () =>
      api.create({
        task_id: id,
        agent: strategy === "single" ? agent : "mock",
        strategy,
        configuration:
          strategy !== "single"
            ? {
                planner: { agent: planner },
                reviewer: { agent: reviewer },
                ...(strategy === "parallel_implementers"
                  ? { implementers: { agent: implementer, count: effectiveCount } }
                  : { implementer: { agent: implementer } }),
              }
            : agent !== "mock" && model.trim()
              ? { model: model.trim() }
              : {},
      }),
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${run.run_id}`);
    },
    onSettled: () => {
      submitted.current = false;
    },
  });
  return (
    <>
      <div className={classes("page-heading")}>
        <div>
          <p className={classes("eyebrow")}>WORKBENCH / NEW RUN</p>
          <h1>
            Give an agent a task.
            <br />
            Keep the evidence.
          </h1>
          <p className={classes("lede")}>
            A reproducible coding task, a controlled execution, and an
            independent verdict.
          </p>
        </div>
        <span className={classes("outline-label")}>CODING-AGENT HARNESS</span>
      </div>
      <div className={classes("new-run-layout")}>
        <section className={classes("panel")}>
          <div className={classes("section-heading")}>
            <h2>Configure execution</h2>
            <span className={classes("step")}>01 / SETUP</span>
          </div>
          {tasks.isPending ? (
            <Loading>Loading benchmark tasks…</Loading>
          ) : tasks.isError ? (
            <ErrorNotice
              error={tasks.error}
              retry={() => void tasks.refetch()}
            />
          ) : !tasks.data.length ? (
            <Empty>No benchmark tasks are available.</Empty>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (submitted.current || !task.data || !available) return;
                submitted.current = true;
                create.mutate();
              }}
            >
              <label htmlFor="task">Benchmark task</label>
              <select
                id="task"
                value={id}
                onChange={(e) => setSelection(e.target.value)}
                disabled={create.isPending}
              >
                {tasks.data.map((t) => (
                  <option value={t.id} key={t.id}>
                    {t.title} · {t.language} · {t.difficulty} · {t.source}
                  </option>
                ))}
              </select>
              <div className={classes("two-columns")}>
                <div>
                  <label htmlFor="agent">Agent</label>
                  <select
                    id="agent"
                    value={agent}
                    onChange={(e) => setAgent(e.target.value)}
                    disabled={create.isPending || strategy !== "single"}
                  >
                    {agents.data?.map((a) => (
                      <option key={a.id} value={a.id} disabled={!a.available}>
                        {a.id}
                        {a.available
                          ? ""
                          : ` · ${a.reason?.replaceAll("_", " ") ?? "unavailable"}`}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="strategy">Execution strategy</label>
                  <select
                    id="strategy"
                    value={strategy}
                    onChange={(e) => setStrategy(e.target.value)}
                    disabled={create.isPending}
                  >
                    <option value="single">Single agent</option>
                    {strategies.data
                      ?.filter((s) => s.id !== "single")
                      .map((s) => (
                        <option key={s.id} value={s.id} disabled={!s.available}>
                          {s.name}
                        </option>
                      ))}
                  </select>
                </div>
              </div>
              {strategies.isError && (
                <ErrorNotice
                  error={strategies.error}
                  retry={() => void strategies.refetch()}
                />
              )}
              {strategy !== "single" && (
                <fieldset disabled={create.isPending}>
                  <legend>Independent role providers</legend>
                  {(
                    [
                      ["Planner", planner, setPlanner],
                      ["Implementer", implementer, setImplementer],
                      ["Reviewer", reviewer, setReviewer],
                    ] as const
                  ).map(([label, value, setValue]) => (
                    <div key={label}>
                      <label htmlFor={`role-${label}`}>{label}</label>
                      <select
                        id={`role-${label}`}
                        value={value}
                        onChange={(e) =>
                          setValue(e.target.value as typeof value)
                        }
                      >
                        {agents.data?.map((a) => (
                          <option
                            key={a.id}
                            value={a.id}
                            disabled={!a.available}
                          >
                            {a.id}
                            {!a.available ? " · unavailable" : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                  {strategy === "parallel_implementers" && (
                    <>
                      <label htmlFor="workers">Parallel implementers</label>
                      <select
                        id="workers"
                      value={effectiveCount}
                        onChange={(e) =>
                          setCount(Number(e.target.value) as 2 | 3)
                        }
                      >
                        {strategies.data
                          ?.find((s) => s.id === strategy)
                          ?.worker_counts.map((n) => (
                            <option key={n} value={n}>
                              {n}
                            </option>
                          ))}
                      </select>
                    </>
                  )}
                  <p>
                    Role sessions use separate containers. Only the selected
                    patch reaches official verification. Real providers may
                    incur multiple charges.
                  </p>
                </fieldset>
              )}
              {agents.isPending && (
                <Loading>Checking provider availability…</Loading>
              )}
              {agents.isError && (
                <ErrorNotice
                  error={agents.error}
                  retry={() => void agents.refetch()}
                />
              )}
              {strategy === "single" && agent !== "mock" && (
                <>
                  <label htmlFor="model">Model (optional)</label>
                  <input
                    id="model"
                    value={model}
                    maxLength={128}
                    placeholder="Provider default"
                    onChange={(e) => setModel(e.target.value)}
                    disabled={create.isPending}
                  />
                </>
              )}
              <div className={classes("notice")}>
                <strong>
                  {usesRealProvider
                    ? "Real provider execution"
                    : "No model credentials required"}
                </strong>
                <p>
                  {usesRealProvider
                    ? "Uses configured provider authentication in disposable containers with outbound network access. Provider usage may incur multiple charges. Official verification remains separate."
                    : "The mock agent follows a fixed tool script. It edits real code and runs real tests inside Docker; it makes no model calls."}
                </p>
              </div>
              {create.isError && <ErrorNotice error={create.error} />}
              <button
                className={classes("primary launch")}
                type="submit"
                disabled={
                  create.isPending || !task.data || task.isError || !available
                }
              >
                {create.isPending ? "Submitting run…" : "Run Agent"}{" "}
                <span aria-hidden="true">→</span>
              </button>
              <p className={classes("footnote")}>
                Execution is queued asynchronously. You’ll be taken to the live
                trajectory.
              </p>
            </form>
          )}
        </section>
        <aside className={classes("panel task-preview")}>
          <p className={classes("eyebrow")}>BENCHMARK BRIEF</p>
          {task.isError ? (
            <ErrorNotice error={task.error} />
          ) : task.data ? (
            <>
              <h2>{task.data.title}</h2>
              <code className={classes("task-id")}>{task.data.id}</code>
              <p>{task.data.description}</p>
              <dl className={classes("facts")}>
                <div>
                  <dt>Source</dt>
                  <dd>{task.data.source === "agentscope" ? "AgentScope Native" : "Harbor"}</dd>
                </div>
                <div>
                  <dt>Dataset</dt>
                  <dd>{task.data.dataset} · {task.data.dataset_version}</dd>
                </div>
                <div>
                  <dt>Agent workspace source</dt>
                  <dd><code>{task.data.repository.source}</code></dd>
                </div>
                <div>
                  <dt>Language / difficulty</dt>
                  <dd>{task.data.language} · {task.data.difficulty}</dd>
                </div>
                <div>
                  <dt>Task version</dt>
                  <dd>{task.data.version}</dd>
                </div>
                <div>
                  <dt>Task timeout</dt>
                  <dd>{task.data.timeout_seconds} seconds</dd>
                </div>
                <div>
                  <dt>Agent-visible tests</dt>
                  <dd>
                    <code>{task.data.test_command}</code>
                  </dd>
                </div>
                <div>
                  <dt>Frozen task hash</dt>
                  <dd><code>{task.data.task_hash?.slice(0, 12) ?? "unfrozen"}</code></dd>
                </div>
              </dl>
              <h3>Expected behavior</h3>
              <p>{task.data.expected_behavior}</p>
            </>
          ) : (
            <Loading>Select a task to view its configuration.</Loading>
          )}
          <div className={classes("verification-note")}>
            <strong>Independent by design</strong>
            <p>
              Official tests are withheld from the agent and executed after its
              work is finished.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}
