import { classes } from "../lib/styles";
import { Link, useSearchParams } from "react-router-dom";
import { useRuns, useTasks } from "../api/queries";
import { RunTable } from "../components/RunTable";
import { labels } from "../lib/status";
import { ErrorNotice, Loading } from "../components/Feedback";
import type { Status } from "../api/client";

const pageSize = 10;
export function RunsPage() {
  const [params, setParams] = useSearchParams();
  const tasks = useTasks();
  const requestedOffset = Number(params.get("offset") ?? 0);
  const offset =
    Number.isInteger(requestedOffset) &&
    requestedOffset >= 0 &&
    requestedOffset <= 1000000
      ? requestedOffset
      : 0;
  const selectedStatus = params.get("status") ?? "";
  const status = Object.hasOwn(labels, selectedStatus)
    ? (selectedStatus as Status)
    : undefined;
  const query = useRuns({
    limit: pageSize,
    offset,
    status,
    task_id: params.get("task_id") || undefined,
    agent: params.get("agent") || undefined,
    strategy: params.get("strategy") || undefined,
  });
  const filter = (key: string, value: string) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("offset");
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    });
  return (
    <>
      <div className={classes("page-heading compact")}>
        <div>
          <p className={classes("eyebrow")}>WORKBENCH / HISTORY</p>
          <h1>Every run, inspectable.</h1>
          <p className={classes("lede")}>
            Browse execution records and compare outcomes. Newest submissions
            first.
          </p>
        </div>
        <Link className={classes("button")} to="/runs/new">
          New run ↗
        </Link>
      </div>
      <section className={classes("panel")}>
        <div className={classes("filters")}>
          <div>
            <label htmlFor="status-filter">Status</label>
            <select
              id="status-filter"
              value={status ?? ""}
              onChange={(e) => filter("status", e.target.value)}
            >
              <option value="">All statuses</option>
              {Object.entries(labels).map(([s, label]) => (
                <option key={s} value={s}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="task-filter">Task</label>
            <select
              id="task-filter"
              value={params.get("task_id") ?? ""}
              onChange={(e) => filter("task_id", e.target.value)}
            >
              <option value="">All tasks</option>
              {tasks.data?.map((t) => (
                <option value={t.id} key={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="agent-filter">Agent</label>
            <select
              id="agent-filter"
              value={params.get("agent") ?? ""}
              onChange={(e) => filter("agent", e.target.value)}
            >
              <option value="">All agents</option>
              <option value="mock">Mock</option>
              <option value="codex">Codex</option>
              <option value="claude-code">Claude Code</option>
            </select>
          </div>
          <div>
            <label htmlFor="strategy-filter">Strategy</label>
            <select
              id="strategy-filter"
              value={params.get("strategy") ?? ""}
              onChange={(e) => filter("strategy", e.target.value)}
            >
              <option value="">All strategies</option>
              <option value="single">Single</option>
              <option value="planner_implementer_reviewer">Planner → Implementer → Reviewer</option>
              <option value="parallel_implementers">Parallel implementers</option>
            </select>
          </div>
        </div>
        {tasks.isError && (
          <ErrorNotice error={tasks.error} retry={() => void tasks.refetch()} />
        )}
        {query.isPending ? (
          <Loading>Loading run history…</Loading>
        ) : query.isError ? (
          <ErrorNotice error={query.error} retry={() => void query.refetch()} />
        ) : (
          <RunTable runs={query.data.items} />
        )}
        <div className={classes("pagination")}>
          <span>
            {query.data?.items.length
              ? `Showing ${offset + 1}–${offset + query.data.items.length}`
              : "No records in this page"}
          </span>
          <div>
            <button
              className={classes("secondary")}
              disabled={offset === 0 || query.isFetching}
              onClick={() =>
                setParams((p) => {
                  const n = new URLSearchParams(p);
                  n.set("offset", String(Math.max(0, offset - pageSize)));
                  return n;
                })
              }
            >
              Previous
            </button>
            <button
              className={classes("secondary")}
              disabled={
                !query.data ||
                query.data.items.length < pageSize ||
                query.isFetching ||
                offset >= 1000000
              }
              onClick={() =>
                setParams((p) => {
                  const n = new URLSearchParams(p);
                  n.set("offset", String(offset + pageSize));
                  return n;
                })
              }
            >
              Next
            </button>
          </div>
        </div>
      </section>
    </>
  );
}
