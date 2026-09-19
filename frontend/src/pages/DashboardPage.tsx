import { classes } from "../lib/styles";
import { Link } from "react-router-dom";
import { useRuns, active } from "../api/queries";
import { RunTable } from "../components/RunTable";
import { ErrorNotice, Loading } from "../components/Feedback";
import { labels } from "../lib/status";

export function DashboardPage() {
  const query = useRuns({ limit: 20, offset: 0 });
  const rows = query.data?.items ?? [];
  const distribution = Object.entries(labels).map(([status, label]) => ({
    label,
    count: rows.filter((r) => r.status === status).length,
  }));
  const tasks = [...new Set(rows.map((r) => r.task_id))];
  return (
    <>
      <div className={classes("page-heading")}>
        <div>
          <p className={classes("eyebrow")}>WORKBENCH / OVERVIEW</p>
          <h1>
            From agent activity
            <br />
            to verifiable outcomes.
          </h1>
          <p className={classes("lede")}>
            Run coding tasks in isolation. Follow every tool call. Check the
            code against independent tests.
          </p>
        </div>
        <Link className={classes("button")} to="/runs/new">
          New benchmark run <span aria-hidden="true">↗</span>
        </Link>
      </div>
      {query.isError ? (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      ) : query.isPending ? (
        <Loading>Loading recent activity…</Loading>
      ) : (
        <>
          <p className={classes("section-note")}>
            Snapshot of the latest {rows.length} runs · up to 20 records · not
            an experiment aggregate
          </p>
          <div className={classes("stat-grid")}>
            {[
              ["Recent runs", rows.length],
              [
                "Verified passes",
                rows.filter((r) => r.status === "completed").length,
              ],
              [
                "Verification failures",
                rows.filter((r) => r.status === "verification_failed").length,
              ],
              ["Active runs", rows.filter((r) => active(r.status)).length],
            ].map(([label, value]) => (
              <div className={classes("stat")} key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <section className={classes("panel")}>
            <div className={classes("section-heading")}>
              <h2>Recent runs</h2>
              <Link to="/runs">Browse all runs →</Link>
            </div>
            <RunTable runs={rows.slice(0, 8)} />
          </section>
          <div className={classes("two-columns")}>
            <section className={classes("panel")}>
              <h2>Run status distribution</h2>
              <dl className={classes("distribution")}>
                {distribution.map((d) => (
                  <div key={d.label}>
                    <dt>{d.label}</dt>
                    <dd>{d.count}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <section className={classes("panel")}>
              <h2>Recent task activity</h2>
              {tasks.length ? (
                tasks.map((id) => (
                  <div className={classes("activity")} key={id}>
                    <code>{id}</code>
                    <span>
                      {rows.filter((r) => r.task_id === id).length} runs in this
                      snapshot
                    </span>
                  </div>
                ))
              ) : (
                <p>No task activity yet.</p>
              )}
              <p className={classes("muted")}>
                A completed run has passed independent verification.
                Agent-invoked tests alone are not benchmark success.
              </p>
            </section>
          </div>
        </>
      )}
    </>
  );
}
