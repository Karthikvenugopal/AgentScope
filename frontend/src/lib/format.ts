export const duration = (ms: number | null | undefined) =>
  ms == null ? "Not measured" : `${(ms / 1000).toFixed(2)} s`;
export const count = (n: number | null | undefined) =>
  n == null ? "Not measured" : n.toLocaleString();
export const date = (value: string | null) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "Not started";
