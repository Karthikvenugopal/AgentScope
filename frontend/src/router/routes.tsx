import { classes } from "../lib/styles";
import { Link, Route, Routes } from "react-router-dom";
import { Shell } from "../components/Shell";
import { DashboardPage } from "../pages/DashboardPage";
import { NewRunPage } from "../pages/NewRunPage";
import { RunDetailPage } from "../pages/RunDetailPage";
import { RunsPage } from "../pages/RunsPage";
import { ExperimentDetailPage } from "../pages/ExperimentDetailPage";
import { ExperimentsPage } from "../pages/ExperimentsPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<DashboardPage />} />
        <Route path="runs/new" element={<NewRunPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="experiments" element={<ExperimentsPage />} />
        <Route path="experiments/:experimentId" element={<ExperimentDetailPage />} />
        <Route
          path="*"
          element={
            <section className={classes("panel")}>
              <h1>Page not found</h1>
              <Link to="/">Return to the dashboard</Link>
            </section>
          }
        />
      </Route>
    </Routes>
  );
}
