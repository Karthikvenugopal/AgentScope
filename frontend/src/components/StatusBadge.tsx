import { classes } from "../lib/styles";
import type { Status } from "../api/client";
import { labels } from "../lib/status";
export function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      data-testid="status-badge"
      className={classes(`badge badge-${status}`)}
    >
      {labels[status]}
    </span>
  );
}
