import { classes } from "../lib/styles";
import { Link } from "react-router-dom";
import type { RunSummary } from "../api/client";
import { date, duration } from "../lib/format";
import { StatusBadge } from "./StatusBadge";
import { Empty } from "./Feedback";

export function RunTable({ runs }: { runs: RunSummary[] }) {
  if (!runs.length)
    return (
      <Empty>
        No runs in this view. <Link to="/runs/new">Launch a benchmark run</Link>{" "}
        to start collecting evidence.
      </Empty>
    );
  return (
    <div className={classes("table-scroll")}>
      <table>
        <thead>
          <tr>
            {[
              "Run / task",
              "Agent",
              "Strategy",
              "Status",
              "Verification",
              "Started",
              "Elapsed¹",
            ].map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id}>
              <td>
                <Link to={`/runs/${run.run_id}`} className={classes("mono")}>
                  {run.run_id.slice(0, 10)}
                </Link>
                <small>{run.task_id}</small>
              </td>
              <td>{run.agent}</td>
              <td>{run.strategy}</td>
              <td>
                <StatusBadge status={run.status} />
              </td>
              <td>
                {run.status === "completed"
                  ? "Passed"
                  : run.status === "verification_failed"
                    ? "Did not pass"
                    : "See run"}
              </td>
              <td>{date(run.started_at)}</td>
              <td className={classes("mono")}>
                {run.started_at && run.finished_at
                  ? duration(
                      new Date(run.finished_at).getTime() -
                        new Date(run.started_at).getTime(),
                    )
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={classes("footnote")}>
        ¹ Elapsed from persisted timestamps. Exact test counts and measured
        durations are available in run details.
      </p>
    </div>
  );
}
