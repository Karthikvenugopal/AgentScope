import styles from "../styles.module.css";

/** Bind readable class combinations to CSS Modules without another dependency. */
export function classes(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((name) => styles[name] ?? name)
    .join(" ");
}
