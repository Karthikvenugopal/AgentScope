import { classes } from "../../lib/styles";
import type { Run } from "../../api/client";
import { duration } from "../../lib/format";

export function VerificationPanel({ run }: { run: Run }) {
  const v = run.verification;
  return (
    <div
      className={classes(
        `verification-box ${v?.passed ? "passed" : v ? "not-passed" : ""}`,
      )}
    >
      <div>
        <p className={classes("eyebrow")}>INDEPENDENT OFFICIAL VERIFICATION</p>
        <h3>
          {v
            ? v.passed
              ? "Verification passed"
              : "Verification did not pass"
            : run.status === "verifying"
              ? "Verification in progress"
              : "No official result yet"}
        </h3>
        <p>
          Performed independently after agent execution. Tests invoked by the
          agent do not determine benchmark success.
        </p>
      </div>
      {v && (
        <dl>
          <div>
            <dt>Official tests</dt>
            <dd>
              {v.passed_tests != null && v.total_tests != null
                ? `${v.passed_tests} / ${v.total_tests} passed`
                : "Counts not measured"}
            </dd>
          </div>
          <div>
            <dt>Duration</dt>
            <dd>{duration(v.duration_ms)}</dd>
          </div>
          <div>
            <dt>Outcome</dt>
            <dd>
              {v.timed_out
                ? "Timed out"
                : v.exit_code != null
                  ? `Exit ${v.exit_code}`
                  : "Exit status unavailable"}
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}
