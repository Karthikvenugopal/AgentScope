import { Link } from "react-router-dom";
import { useExperiments } from "../api/queries";
import { ErrorNotice, Loading } from "../components/Feedback";
import { classes } from "../lib/styles";

export function ExperimentsPage() {
  const query = useExperiments();
  return (
    <>
      <div className={classes("page-heading compact")}>
        <div>
          <p className={classes("eyebrow")}>RESEARCH / CONTROLLED EXPERIMENTS</p>
          <h1>Repeated runs, clustered by task.</h1>
          <p className={classes("lede")}>
            Immutable schedules, infrastructure exclusions, and task-level
            statistical summaries. No overall ranking is generated.
          </p>
        </div>
      </div>
      <section className={classes("panel")}>
        {query.isPending ? (
          <Loading>Loading experiments…</Loading>
        ) : query.isError ? (
          <ErrorNotice error={query.error} retry={() => void query.refetch()} />
        ) : (
          <div className={classes("table-scroll")}>
            <table aria-label="Experiments">
              <thead>
                <tr>
                  <th>Experiment</th>
                  <th>Status</th>
                  <th>Benchmark</th>
                  <th>Valid runs</th>
                  <th>Benchmark failures</th>
                  <th>Invalid attempts</th>
                </tr>
              </thead>
              <tbody>
                {query.data.map((experiment) => (
                  <tr key={experiment.experiment_id}>
                    <td>
                      <Link to={`/experiments/${experiment.experiment_id}`}>
                        {experiment.name}
                      </Link>
                      <small>{experiment.experiment_id}</small>
                    </td>
                    <td>{experiment.status}</td>
                    <td>
                      {experiment.benchmark_name} · {experiment.benchmark_version}
                    </td>
                    <td>
                      {experiment.progress.completed} / {experiment.progress.planned}
                    </td>
                    <td>{experiment.progress.benchmark_failures}</td>
                    <td>
                      {experiment.progress.infrastructure_failures +
                        experiment.progress.protocol_exclusions}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
