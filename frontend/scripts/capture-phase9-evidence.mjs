// Read-only capture of the persisted Phase 9 experiment ledger and analysis.
import { chromium, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";

const base = process.env.DEMO_URL ?? "http://127.0.0.1:5176";
const experimentId = process.env.EXPERIMENT_ID ?? "strategy-study-v1";
const images = fileURLToPath(new URL("../../docs/images/", import.meta.url));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));

try {
    await page.goto(`${base}/experiments`);
    await expect(page.getByRole("link", { name: "Controlled orchestration strategy study v1" }))
        .toBeVisible({ timeout: 30000 });
    await expect(page.getByText("108 / 108", { exact: true })).toBeVisible();
    await page.screenshot({
        path: `${images}/phase9-experiments.png`,
        fullPage: true,
    });

    await page.goto(`${base}/experiments/${experimentId}`);
    await expect(page.getByRole("heading", { name: "Strategy summaries" })).toBeVisible();
    await expect(page.getByText("108/108", { exact: true })).toBeVisible();
    await page.screenshot({
        path: `${images}/phase9-strategy-summary.png`,
        fullPage: true,
    });
    await page.getByRole("table", { name: "Experiment run matrix" }).screenshot({
        path: `${images}/phase9-run-matrix.png`,
    });

    expect(errors).toEqual([]);
    console.log(
        JSON.stringify(
            {
                base,
                experiment_id: experimentId,
                screenshots: [
                    "phase9-experiments.png",
                    "phase9-strategy-summary.png",
                    "phase9-run-matrix.png",
                ],
                errors,
            },
            null,
            2,
        ),
    );
} finally {
    await browser.close();
}
