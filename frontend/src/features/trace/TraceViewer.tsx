import { classes } from "../../lib/styles";
import { useState } from "react";
import type { TraceEvent } from "../../api/client";
import { duration } from "../../lib/format";
import { mergeEvents } from "./useTrace";
import { Empty } from "../../components/Feedback";

function title(event: TraceEvent) {
  const p = event.payload;
  if (event.event_type === "tool_call_started")
    return `Tool → ${p.tool ?? "unknown"}`;
  if (event.event_type === "tool_call_completed")
    return `Tool completed · ${p.tool ?? "unknown"}`;
  if (event.event_type === "tool_call_failed")
    return `Tool failed · ${p.tool ?? "unknown"}`;
  if (event.event_type === "agent_turn_started")
    return `Agent turn ${p.turn_number} started`;
  if (event.event_type === "agent_turn_completed")
    return `Agent turn ${p.turn_number} · ${p.turn_status}`;
  if (event.event_type === "test_executed")
    return "Agent-invoked tests executed";
  if (event.event_type === "verification_completed")
    return "Independent verification passed";
  return event.event_type
    .replaceAll("_", " ")
    .replace(/^./, (c) => c.toUpperCase());
}

function Field({ name, value }: { name: string; value: unknown }) {
  const [limit, setLimit] = useState(2000);
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (text == null) return null;
  const expandable =
    typeof value === "object" ||
    text.length > 140 ||
    name === "stdout" ||
    name === "stderr";
  return expandable ? (
    <div className={classes("field trace-field")}>
      <dt>{name}</dt>
      <dd>
        <details>
          <summary>
            Inspect {name}{" "}
            <span className={classes("muted")}>
              {text.length.toLocaleString()} characters
            </span>
          </summary>
          <pre>{text.slice(0, limit) || "(empty)"}</pre>
          {text.length > limit && (
            <>
              <p className={classes("footnote")}>
                Display capped at {limit.toLocaleString()} characters; the event
                JSON download retains the full API payload.
              </p>
              {limit < 20000 && (
                <button
                  className={classes("secondary")}
                  onClick={() => setLimit(Math.min(limit + 5000, 20000))}
                >
                  Show more {name}
                </button>
              )}
            </>
          )}
        </details>
      </dd>
    </div>
  ) : (
    <div className={classes("field")}>
      <dt>{name}</dt>
      <dd>{text || "(empty)"}</dd>
    </div>
  );
}

function download(event: TraceEvent) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(event, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `event-${event.sequence_number}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function TraceViewer({
  events,
  live,
}: {
  events: TraceEvent[];
  live: boolean;
}) {
  const [visible, setVisible] = useState(100);
  const ordered = mergeEvents([], events);
  if (!ordered.length)
    return (
      <Empty>
        {live
          ? "Waiting for the worker to emit its first event…"
          : "No trace events are available for this run."}
      </Empty>
    );
  return (
    <>
      <ol className={classes("trace-list")} aria-label="Execution trace">
        {ordered.slice(0, visible).map((event) => (
          <li
            key={event.sequence_number}
            className={classes(
              event.event_type.startsWith("verification")
                ? "official-event"
                : "",
            )}
          >
            <details>
              <summary>
                <span className={classes("sequence")}>
                  {String(event.sequence_number).padStart(2, "0")}
                </span>
                <span className={classes("event-name")}>{title(event)}</span>
                <time dateTime={event.timestamp}>
                  {new Date(event.timestamp).toLocaleTimeString()}
                </time>
                {typeof event.payload.duration_ms === "number" && (
                  <span className={classes("event-duration")}>
                    {duration(event.payload.duration_ms)}
                  </span>
                )}
              </summary>
              <div className={classes("event-detail")}>
                <code>{event.event_type}</code>
                <p className={classes("footnote")}>
                  Event ID: {event.event_id}
                </p>
                <dl>
                  {Object.entries(event.payload).map(([name, value]) => (
                    <Field key={name} name={name} value={value} />
                  ))}
                </dl>
                <button
                  className={classes("secondary")}
                  onClick={() => download(event)}
                >
                  Download event JSON
                </button>
              </div>
            </details>
          </li>
        ))}
      </ol>
      {visible < ordered.length && (
        <button
          className={classes("secondary")}
          onClick={() => setVisible((n) => n + 100)}
        >
          Show next events ({ordered.length - visible} remaining)
        </button>
      )}
      <p className={classes("footnote")}>
        {ordered.length} events received · ordered by sequence · expand an event
        to inspect its payload.
      </p>
    </>
  );
}
