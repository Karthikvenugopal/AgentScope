import { Link, useParams } from "react-router-dom";
import { useExperiment } from "../api/queries";
import { ErrorNotice, Loading } from "../components/Feedback";
import { classes } from "../lib/styles";
import { count, duration } from "../lib/format";

const probability = (value: number | null) =>
  value == null ? "Unavailable" : `${(value * 100).toFixed(1)}%`;

export function ExperimentDetailPage() {
  const { experimentId = "" } = useParams();
  const query = useExperiment(experimentId);
  if (!query.data)
    return query.isError ? (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    ) : (
      <Loading>Loading experiment…</Loading>
    );
  const experiment = query.data;
  const aggregate = new Map(
    experiment.analysis.task_aggregates.map((row) => [
      `${row.task_id}:${row.configuration_id}`,
      row,
    ]),
  );
  const taskIds = [...new Set(experiment.schedule.map((row) => row.task_id))].sort();
  return (
    <>
      <div className={classes("page-heading compact")}>
        <div>
          <p className={classes("eyebrow")}>
            <Link to="/experiments">EXPERIMENTS</Link> / EXECUTION MATRIX
          </p>
          <h1>{experiment.name}</h1>
          <p className={classes("lede")}>{experiment.research_question}</p>
        </div>
        <span className={classes("outline-label")}>{experiment.status}</span>
      </div>
      <div className={classes("stat-grid")}>
        <div className={classes("stat")}>
          <span>Valid runs</span>
          <strong>{experiment.progress.completed}/{experiment.progress.planned}</strong>
        </div>
        <div className={classes("stat")}>
          <span>Benchmark successes</span>
          <strong>{experiment.progress.benchmark_successes}</strong>
        </div>
        <div className={classes("stat")}>
          <span>Benchmark failures</span>
          <strong>{experiment.progress.benchmark_failures}</strong>
        </div>
        <div className={classes("stat")}>
          <span>Invalid attempts</span>
          <strong>
            {experiment.progress.infrastructure_failures +
              experiment.progress.protocol_exclusions}
          </strong>
        </div>
      </div>
      <section className={classes("panel")}>
        <div className={classes("section-heading")}>
          <h2>Strategy summaries</h2>
          <span className={classes("step")}>TASK-CLUSTER ANALYSIS</span>
        </div>
        <div className={classes("table-scroll")}>
          <table aria-label="Strategy summaries">
            <thead>
              <tr>
                <th>Configuration</th>
                <th>Mean task success</th>
                <th>Bootstrap 95% CI</th>
                <th>Median wall</th>
                <th>Median tokens</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(experiment.analysis.strategy_summary).map(([id, summary]) => (
                <tr key={id}>
                  <td>{id}</td>
                  <td>{probability(summary.mean_task_success_probability)}</td>
                  <td>
                    {summary.success_bootstrap_95_ci.map(probability).join(" – ")}
                  </td>
                  <td>{duration(summary.all_runs.task_wall_time_ms?.median ?? null)}</td>
                  <td>{count(summary.all_runs.total_tokens?.median ?? null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className={classes("panel")}>
        <div className={classes("section-heading")}>
          <div>
            <h2>Task × configuration matrix</h2>
            <p className={classes("muted")}>
              Official successes over valid repetitions. Run IDs link to immutable records.
            </p>
          </div>
        </div>
        <div className={classes("table-scroll")}>
          <table aria-label="Experiment run matrix">
            <thead>
              <tr>
                <th>Task</th>
                {experiment.configurations.map((configuration) => (
                  <th key={configuration.configuration_id}>{configuration.configuration_id}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {taskIds.map((taskId) => (
                <tr key={taskId}>
                  <td><code>{taskId}</code></td>
                  {experiment.configurations.map((configuration) => {
                    const key = `${taskId}:${configuration.configuration_id}`;
                    const result = aggregate.get(key);
                    const runs = experiment.schedule.filter(
                      (entry) =>
                        entry.task_id === taskId &&
                        entry.configuration_id === configuration.configuration_id &&
                        entry.valid_run_id,
                    );
                    return (
                      <td key={key}>
                        <strong>{result ? `${result.successes}/${result.valid_repetitions}` : "Pending"}</strong>
                        <small>
                          {runs.map((entry, index) => (
                            <span key={entry.valid_run_id}>
                              {index > 0 ? " · " : ""}
                              <Link to={`/runs/${entry.valid_run_id}`}>run {entry.repetition}</Link>
                            </span>
                          ))}
                        </small>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <p className={classes("section-note")}>
        Repetitions are averaged within each task before cross-task analysis. Confidence
        intervals bootstrap tasks, not individual runs. No automatic winner is selected.
      </p>
    </>
  );
}
