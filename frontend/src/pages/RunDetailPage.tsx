import { classes } from "../lib/styles";
import { Link, useParams } from "react-router-dom";
import { useState } from "react";
import { useRun, useTask, active } from "../api/queries";
import { Loading, ErrorNotice } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { MetricsPanel } from "../features/metrics/MetricsPanel";
import { PatchPanel } from "../features/artifacts/PatchPanel";
import { VerificationPanel } from "../features/runs/VerificationPanel";
import { TraceViewer } from "../features/trace/TraceViewer";
import { useTrace } from "../features/trace/useTrace";
import { date } from "../lib/format";
import { StrategyPanel } from "../features/runs/StrategyPanel";

export function RunDetailPage() {
  const [expanded, setExpanded] = useState(true);
  const { runId = "" } = useParams();
  const query = useRun(runId);
  const run = query.data;
  const task = useTask(run?.task_id ?? "");
  const live = active(run?.status);
  const trace = useTrace(runId, live, !!run);
  if (!run)
    return query.isError ? (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    ) : (
      <Loading>Loading run…</Loading>
    );
  return (
    <>
      <div className={classes("page-heading compact")}>
        <div>
          <p className={classes("eyebrow")}>
            <Link to="/runs">RUNS</Link> / EXECUTION RECORD
          </p>
          <h1>{task.data?.title ?? run.task_id}</h1>
          <p className={classes("mono muted run-id")}>{runId}</p>
        </div>
        <div
          data-testid="run-status"
          className={classes("run-status")}
          aria-live="polite"
        >
          <StatusBadge status={run.status} />
          <span>
            {live
              ? "Live · updating every second"
              : "Finalized execution record"}
          </span>
        </div>
      </div>
      <div className={classes("run-meta")}>
        <span>
          Agent <strong>{run.agent}</strong>
        </span>
        <span>
          Strategy <strong>{run.strategy}</strong>
        </span>
        <span>
          Task <code>{run.task_id}</code>
        </span>
        <span>
          Started <strong>{date(run.started_at)}</strong>
        </span>
      </div>
      {task.data && (
        <div className={classes("run-meta")} aria-label="Benchmark provenance">
          <span>
            Source <strong>{task.data.source === "agentscope" ? "AgentScope Native" : "Harbor"}</strong>
          </span>
          <span>
            Dataset <strong>{task.data.dataset} · {task.data.dataset_version}</strong>
          </span>
          <span>
            Language / difficulty <strong>{task.data.language} · {task.data.difficulty}</strong>
          </span>
          <span>
            Frozen task <code>{task.data.task_hash?.slice(0, 12) ?? "unavailable"}</code>
          </span>
        </div>
      )}
      {run.provider && (
        <div className={classes("run-meta")}>
          <span>
            Provider version <strong>{run.provider.version}</strong>
          </span>
          <span>
            Model <strong>{run.provider.model ?? "Not exposed"}</strong>
          </span>
          <span>
            Session <code>{run.provider.session_id ?? "Not exposed"}</code>
          </span>
        </div>
      )}
      {query.isError && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {run.failure_reason && (
        <div className={classes("notice error")} role="alert">
          <strong>
            {run.failure_code?.replaceAll("_", " ") ?? "Run failed"}
          </strong>
          <p>{run.failure_reason}</p>
          <p>Available execution evidence is retained below.</p>
        </div>
      )}
      <VerificationPanel run={run} />
      <StrategyPanel run={run} events={trace.data?.events ?? []} live={live} />
      <nav className={classes("section-nav")} aria-label="Run sections">
        <a href="#metrics">Metrics</a>
        <a href="#trajectory">Execution trace</a>
        <a href="#patch">Patch</a>
        <a href="#artifacts">Artifacts</a>
      </nav>
      <section className={classes("panel")} id="metrics">
        <div className={classes("section-heading")}>
          <h2>Measured work</h2>
          <span className={classes("step")}>01 / METRICS</span>
        </div>
        <MetricsPanel metrics={run.metrics} />
      </section>
      <section className={classes("panel")} id="trajectory">
        <div className={classes("section-heading")}>
          <div>
            <h2>Agent trajectory</h2>
            <p className={classes("muted")}>
              The chronological record of tools, edits, commands, and
              verification.
            </p>
          </div>
          <button
            className={classes("secondary")}
            aria-expanded={expanded}
            aria-controls="trace-content"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Collapse trace" : "Expand trace"}
          </button>
        </div>
        {trace.isError && (
          <ErrorNotice error={trace.error} retry={() => void trace.refetch()} />
        )}
        <div id="trace-content">
          {expanded ? (
            <TraceViewer
              key={runId}
              events={(trace.data?.events ?? []).filter(
                (e) => run.strategy === "single" || !e.payload.execution_id,
              )}
              live={live}
            />
          ) : (
            <p className={classes("muted")}>
              {trace.data?.events.length ?? 0} events received. Expand to
              inspect the trajectory.
            </p>
          )}
        </div>
      </section>
      <section className={classes("panel")} id="patch">
        <div className={classes("section-heading")}>
          <h2>Resulting patch</h2>
          <span className={classes("patch-count")}>
            {run.metrics
              ? `+${run.metrics.lines_added} / −${run.metrics.lines_removed}`
              : "Not available yet"}
          </span>
        </div>
        <PatchPanel id={runId} ready={!live} />
      </section>
      <section className={classes("panel")} id="artifacts">
        <div className={classes("section-heading")}>
          <h2>Artifact integrity</h2>
          <span className={classes("step")}>SHA-256</span>
        </div>
        {run.artifacts?.length ? (
          <div className={classes("table-scroll")}>
            <table>
              <thead>
                <tr>
                  <th>Artifact</th>
                  <th>Bytes</th>
                  <th>Content hash</th>
                </tr>
              </thead>
              <tbody>
                {run.artifacts.map((a) => (
                  <tr key={a.type}>
                    <td>{a.type}</td>
                    <td>{a.size_bytes.toLocaleString()}</td>
                    <td>
                      <code className={classes("hash")}>{a.sha256}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={classes("muted")}>
            No finalized artifacts are available.
          </p>
        )}
        <p className={classes("footnote")}>
          Host filesystem paths are not exposed. Raw artifact downloads are not
          part of this API.
        </p>
      </section>
    </>
  );
}
