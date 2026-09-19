import { classes } from "../lib/styles";
import { ApiError } from "../api/client";

export function ErrorNotice({
  error,
  retry,
}: {
  error: Error;
  retry?: () => void;
}) {
  const code = error instanceof ApiError ? error.code : "service_unavailable";
  const message: Record<string, string> = {
    run_not_found:
      "This run could not be found. Check the link or browse the run history.",
    task_not_found:
      "This task is no longer available in the benchmark catalog.",
    artifact_not_found: "No patch is available for this run.",
    artifact_integrity_failure:
      "The stored patch failed its integrity check. It has not been displayed.",
    service_unavailable:
      "The backend is unavailable. Check that the API and PostgreSQL are running.",
  };
  return (
    <div className={classes("notice error")} role="alert">
      <strong>Unable to load this resource</strong>
      <p>
        {message[code] ??
          "The request could not be completed. Check your selection and try again."}
      </p>
      {retry && (
        <button className={classes("secondary")} onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Loading({ children = "Loading…" }: { children?: string }) {
  return (
    <p className={classes("notice muted")} role="status">
      {children}
    </p>
  );
}
export function Empty({ children }: { children: React.ReactNode }) {
  return <div className={classes("empty")}>{children}</div>;
}
