// Explicitly opt in: one real paid submission per invocation, never repeated trials.
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

if (process.env.RUN_PHASE7_LIVE !== "1")
    throw new Error("Set RUN_PHASE7_LIVE=1 for paid demonstration");
const strategy = process.env.DEMO_STRATEGY ?? "planner_implementer_reviewer";
const base = process.env.DEMO_URL ?? "http://127.0.0.1:5175";
const images = fileURLToPath(new URL("../../docs/images/", import.meta.url));
await mkdir(images, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const evidence = {
    strategy,
    captured_at: new Date().toISOString(),
    visible_statuses: [],
    errors: [],
};
page.on("pageerror", (e) => evidence.errors.push(e.message));
try {
    await page.goto(`${base}/runs/new`);
    await expect(
        page.getByRole("option", { name: "codex", exact: true }),
    ).toBeEnabled({ timeout: 30000 });
    await page.getByLabel("Execution strategy").selectOption(strategy);
    if (strategy === "single") {
        await page.getByLabel("Agent", { exact: true }).selectOption("codex");
    } else {
        await page
            .getByLabel("Planner", { exact: true })
            .selectOption("claude-code");
        await page
            .getByLabel("Implementer", { exact: true })
            .selectOption("codex");
        await page
            .getByLabel("Reviewer", { exact: true })
            .selectOption("claude-code");
        if (strategy === "parallel_implementers")
            await page.getByLabel("Parallel implementers").selectOption("3");
    }
    await page.screenshot({
        path: `${images}/phase7-${strategy}-new.png`,
        fullPage: true,
    });
    const accepted = page.waitForResponse(
        (r) =>
            r.request().method() === "POST" && r.url().endsWith("/api/v1/runs"),
    );
    await page.getByRole("button", { name: /Run Agent/ }).click();
    const response = await accepted;
    expect(response.status()).toBe(202);
    evidence.submission = await response.json();
    const id = evidence.submission.run_id;
    const deadline = Date.now() + 180000;
    let activeCaptured = false;
    while (Date.now() < deadline) {
        const status = await page
            .getByTestId("run-status")
            .getByTestId("status-badge")
            .textContent()
            .catch(() => null);
        if (status && !evidence.visible_statuses.includes(status))
            evidence.visible_statuses.push(status);
        const candidates = await page.locator("#strategy > details").count();
        if (
            !activeCaptured &&
            status === "Running" &&
            candidates >= (strategy === "parallel_implementers" ? 4 : 2)
        ) {
            await page.screenshot({
                path: `${images}/phase7-${strategy}-active.png`,
                fullPage: true,
            });
            activeCaptured = true;
        }
        if (status && /Completed|failed|Timed out/i.test(status)) break;
        await page.waitForTimeout(100);
    }
    evidence.result = await (
        await page.request.get(`${base}/api/v1/runs/${id}`)
    ).json();
    evidence.trace = await (
        await page.request.get(`${base}/api/v1/runs/${id}/trace?limit=500`)
    ).json();
    evidence.patch = await (
        await page.request.get(`${base}/api/v1/runs/${id}/patch`)
    ).text();
    const collapse = page.getByRole("button", {
        name: "Collapse trace",
        exact: true,
    });
    if (await collapse.count()) await collapse.click();
    await page.screenshot({
        path: `${images}/phase7-${strategy}-completed.png`,
        fullPage: true,
    });
    await writeFile(
        `${images}/phase7-${strategy}-evidence.json`,
        JSON.stringify(evidence, null, 2),
    );
    console.log(
        JSON.stringify(
            {
                run_id: id,
                status: evidence.result.status,
                verification: evidence.result.verification,
                orchestration: evidence.result.orchestration?.metrics,
                errors: evidence.errors,
            },
            null,
            2,
        ),
    );
    expect(evidence.result.status).toBe("completed");
    expect(evidence.result.verification.passed_tests).toBe(3);
} finally {
    await browser.close();
}
