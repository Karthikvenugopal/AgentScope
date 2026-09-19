import type { Status } from "../api/client";

export const labels: Record<Status, string> = {
  queued: "Queued",
  running: "Running",
  verifying: "Verifying",
  completed: "Completed",
  failed: "Execution failed",
  timed_out: "Timed out",
  verification_failed: "Verification failed",
};
