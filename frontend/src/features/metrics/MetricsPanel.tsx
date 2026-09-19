import { classes } from "../../lib/styles";
import type { Metrics } from "../../api/client";
import { count, duration } from "../../lib/format";

export function MetricsPanel({
  metrics: m,
}: {
  metrics: Metrics | null | undefined;
}) {
  if (!m)
    return (
      <p className={classes("notice muted")}>
        Metrics become available after execution and finalization. Unavailable
        measurements are never treated as zero.
      </p>
    );
  const groups = [
    [
      "Execution",
      [
        ["Total wall time", duration(m.total_wall_time_ms)],
        ["Agent time", duration(m.agent_execution_time_ms)],
        ["Verification time", duration(m.verification_time_ms)],
      ],
    ],
    [
      "Agent behavior",
      [
        ["Harness turns", count(m.agent_turns)],
        ["Tool calls", count(m.tool_calls)],
        ["Failed tool calls", count(m.failed_tool_calls)],
      ],
    ],
    [
      "Code changes",
      [
        ["Files modified", count(m.files_modified)],
        ["Lines added / removed", `+${m.lines_added} / −${m.lines_removed}`],
        ["Patch size", `${count(m.patch_bytes)} bytes`],
      ],
    ],
    [
      "Testing",
      [
        ["Controlled-tool test runs", count(m.agent_test_runs)],
        ["Official tests passed", count(m.official_tests_passed)],
        ["Official tests failed", count(m.official_tests_failed)],
      ],
    ],
  ] as const;
  const inference = m.inference;
  const measurements = [
    ["Model calls", inference?.model_calls, ""],
    ["Input tokens", inference?.input_tokens, ""],
    ["Output tokens", inference?.output_tokens, ""],
    ["Cached input tokens", inference?.cached_input_tokens, ""],
    [
      "Time to first provider output",
      inference?.time_to_first_provider_output_ms,
      "ms",
    ],
    ["TTFT", inference?.mean_ttft_ms, "ms"],
    ["ITL", inference?.mean_itl_ms, "ms"],
    ["Generation throughput", inference?.output_tokens_per_second, "tok/s"],
  ] as const;
  return (
    <>
      <div className={classes("metrics-grid")}>
        {groups.map(([heading, rows]) => (
          <div className={classes("metric-group")} key={heading}>
            <h3>{heading}</h3>
            <dl>
              {rows.map(([name, value]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
      <div className={classes("inference")}>
        <h3>Inference measurements</h3>
        {measurements.every(([, n]) => n == null) ? (
          <p>
            Not measured · Token usage, TTFT, ITL, and throughput are
            unavailable.
          </p>
        ) : (
          <dl className={classes("facts")}>
            {measurements
              .filter(([, n]) => n != null)
              .map(([name, n, unit]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>
                    {count(n)} {unit}
                  </dd>
                </div>
              ))}
          </dl>
        )}
      </div>
      {inference?.provenance && (
        <details>
          <summary>Measurement provenance</summary>
          <dl className={classes("facts")}>
            {Object.entries(inference.provenance).map(([key, source]) => (
              <div key={key}>
                <dt>{key.replaceAll("_", " ")}</dt>
                <dd>
                  {source.provenance}
                  {source.source ? ` · ${source.source}` : ""}
                </dd>
              </div>
            ))}
          </dl>
          <p>
            First provider output includes CLI startup. It is not model TTFT.
            Missing model boundaries cannot establish generation throughput or
            ITL.
          </p>
        </details>
      )}
      <p className={classes("footnote")}>
        Wall time covers the harness through cleanup, excluding artifact export
        and database commit. Agent tests and official tests are distinct
        measurements. Native shell commands are not guessed to be tests. A
        native CLI session occupies one harness turn, not one model call.
      </p>
    </>
  );
}
