import type { Run, TraceEvent } from "../../api/client";
import { classes } from "../../lib/styles";
import { duration } from "../../lib/format";
import { TraceViewer } from "../trace/TraceViewer";

function patchSize(patch: string) {
  let added = 0, removed = 0, hunk = false;
  for (const line of patch.split("\n")) {
    if (line.startsWith("diff --git")) hunk = false;
    else if (line.startsWith("@@ ")) hunk = true;
    else if (hunk && line.startsWith("+")) added++;
    else if (hunk && line.startsWith("-")) removed++;
  }
  return `+${added} / −${removed}`;
}

export function StrategyPanel({
  run,
  events,
  live,
}: {
  run: Run;
  events: TraceEvent[];
  live: boolean;
}) {
  if (run.strategy === "single") return null;
  const result = run.orchestration;
  const ids = [
    ...new Set(
      events
        .map((e) => e.payload.execution_id)
        .filter((id): id is string => typeof id === "string"),
    ),
  ];
  const m = result?.metrics;
  return (
    <section className={classes("panel")} id="strategy">
      <h2>Strategy architecture</h2>
      <p>
        Selected candidate:{" "}
        <strong>{result?.selected_candidate ?? "Selection pending"}</strong> ·
        Corrections: {result?.corrections ?? "Pending"}
      </p>
      {m && (
        <>
          <h3>Measured strategy workload</h3>
          <dl className={classes("facts")}>
            <div>
              <dt>Strategy wall time</dt>
              <dd>{duration(m.strategy_wall_time_ms)}</dd>
            </div>
            <div>
              <dt>Provider invocations</dt>
              <dd>{m.provider_invocations}</dd>
            </div>
            <div>
              <dt>Peak provider processes</dt>
              <dd>{m.peak_concurrent_provider_processes ?? "Not measured"}</dd>
            </div>
            <div>
              <dt>Summed provider execution time</dt>
              <dd>{duration(m.summed_provider_execution_time_ms)}</dd>
            </div>
            <div>
              <dt>Derived concurrency factor</dt>
              <dd>
                {m.concurrency_factor?.toFixed(2) ?? "Not measured"} (not GPU
                utilization)
              </dd>
            </div>
            <div>
              <dt>Total tokens</dt>
              <dd>{m.total_tokens?.toLocaleString() ?? "Not measured"}</dd>
            </div>
          </dl>
          <div className={classes("table-scroll")}>
            <table>
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Invocations</th>
                  <th>Time</th>
                  <th>Tools</th>
                  <th>Input tokens</th>
                  <th>Output tokens</th>
                  <th>Total tokens</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(m.per_role ?? {}).map(([role, value]) => (
                  <tr key={role}>
                    <td>{role}</td>
                    <td>{value.invocations}</td>
                    <td>{duration(value.duration_ms)}</td>
                    <td>{value.tool_calls}</td>
                    <td>{value.input_tokens ?? "Not measured"}</td>
                    <td>{value.output_tokens ?? "Not measured"}</td>
                    <td>{value.total_tokens ?? "Not measured"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={classes("footnote")}>
            Input token semantics differ by provider; total tokens include
            Claude cache categories. These demonstrations are functional
            validation, not statistical comparisons.
          </p>
        </>
      )}
      {ids.map((id) => {
        const trace = events.filter((e) => e.payload.execution_id === id);
        const execution = result?.executions?.find(
          (e) => e.execution_id === id,
        );
        const role =
          execution?.role ?? String(trace[0]?.payload.role ?? "role");
        const candidate =
          execution?.candidate_id ?? trace[0]?.payload.candidate_id;
        return (
          <details key={id} className={classes("panel")}>
            <summary>
              <strong>
                {role}
                {candidate ? ` · Candidate ${candidate}` : ""}
              </strong>{" "}
              —{" "}
              {String(
                execution?.provider ?? trace[0]?.payload.provider ?? "starting",
              )}{" "}
              {execution?.status ?? "in progress"}
              {candidate && candidate === result?.selected_candidate
                ? " · Selected"
                : ""}
            </summary>
            {execution?.provider_metadata && (
              <p>
                {execution.provider_metadata.version} ·{" "}
                {execution.provider_metadata.model ?? "Model not exposed"}
              </p>
            )}
            {execution?.patch && (
              <details>
                <summary>
                  Candidate patch · {patchSize(execution.patch)} ·{" "}
                  {execution.files_changed?.length} files changed
                </summary>
                <pre>{execution.patch}</pre>
              </details>
            )}
            {execution?.visible_test_exit_code != null && (
              <p>
                Visible tests exit {execution.visible_test_exit_code}. Not
                hidden verification.
              </p>
            )}
            <TraceViewer events={trace} live={live} />
          </details>
        );
      })}
      {result?.review && (
        <>
          <h3>Reviewer rationale</h3>
          <p>{result.review.rationale}</p>
        </>
      )}
      <p>Unselected candidates are never officially verified.</p>
    </section>
  );
}
