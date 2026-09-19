import { classes } from "../lib/styles";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function Shell() {
  const readiness = useQuery({
    queryKey: ["readiness"],
    queryFn: ({ signal }) => api.ready(signal),
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return (
    <>
      <a className={classes("skip")} href="#main">
        Skip to content
      </a>
      <header className={classes("topbar")}>
        <NavLink to="/" className={classes("brand")}>
          <span className={classes("brand-mark")} aria-hidden="true">
            A<span>↗</span>
          </span>
          <span>
            AgentScope<small>CODING AGENT RESEARCH</small>
          </span>
        </NavLink>
        <nav aria-label="Main navigation">
          <NavLink
            to="/"
            end
            className={({ isActive }) => classes(isActive ? "active" : "")}
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/runs/new"
            className={({ isActive }) => classes(isActive ? "active" : "")}
          >
            New Run
          </NavLink>
          <NavLink
            to="/runs"
            end
            className={({ isActive }) => classes(isActive ? "active" : "")}
          >
            Runs
          </NavLink>
          <NavLink
            to="/experiments"
            className={({ isActive }) => classes(isActive ? "active" : "")}
          >
            Experiments
          </NavLink>
        </nav>
        <div
          className={classes(`readiness ${readiness.isSuccess ? "ready" : ""}`)}
          role="status"
        >
          <span aria-hidden="true">●</span> API ·{" "}
          {readiness.isPending
            ? "Checking"
            : readiness.isError
              ? "Unavailable"
              : "Ready"}
        </div>
      </header>
      <main id="main">
        <Outlet />
      </main>
      <footer>
        AgentScope{" "}
        <span>
          Independent verification. Traceable execution. Measured outcomes.
        </span>
      </footer>
    </>
  );
}
