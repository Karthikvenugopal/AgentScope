// Read-only capture of persisted Phase 8 runs and the real benchmark catalog.
import { chromium, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";

const base = process.env.DEMO_URL ?? "http://127.0.0.1:5176";
const images = fileURLToPath(new URL("../../docs/images/", import.meta.url));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));

try {
    await page.goto(`${base}/runs/new`);
    await expect(page.getByLabel("Benchmark task")).toBeVisible();
    await expect(
        page.getByLabel("Agent", { exact: true }).getByRole("option", { name: "mock" }),
    ).toBeEnabled({ timeout: 30000 });
    await page
        .getByLabel("Benchmark task")
        .selectOption("terminal-bench.cancel-async-tasks");
    await expect(page.getByText("Harbor", { exact: true })).toBeVisible();
    await expect(
        page.getByText("terminal-bench/terminal-bench-2-1 · 2.1@6", {
            exact: true,
        }),
    ).toBeVisible();
    await page.screenshot({
        path: `${images}/phase8-benchmark-browser.png`,
        fullPage: true,
    });

    await page.goto(`${base}/runs/phase8-harbor-cancel-async`);
    await expect(page.getByLabel("Benchmark provenance")).toContainText(
        "terminal-bench/terminal-bench-2-1",
    );
    await expect(
        page.getByRole("heading", { name: "Verification did not pass" }),
    ).toBeVisible();
    const collapse = page.getByRole("button", { name: "Collapse trace" });
    if (await collapse.count()) await collapse.click();
    await page.screenshot({
        path: `${images}/phase8-external-run.png`,
        fullPage: true,
    });

    await page.goto(`${base}/runs/phase8-native-hard-parallel-v2`);
    await expect(page.getByText("Candidate A", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("1 / 1 passed", { exact: true })).toBeVisible();
    const parallelCollapse = page.getByRole("button", {
        name: "Collapse trace",
    });
    if (await parallelCollapse.count()) await parallelCollapse.click();
    await page.screenshot({
        path: `${images}/phase8-strategy-metrics.png`,
        fullPage: true,
    });
    expect(errors).toEqual([]);
    console.log(
        JSON.stringify(
            {
                base,
                screenshots: [
                    "phase8-benchmark-browser.png",
                    "phase8-external-run.png",
                    "phase8-strategy-metrics.png",
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
