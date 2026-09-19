// One real paid submission, no routing interception and no invented UI state.
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.DEMO_URL ?? "http://127.0.0.1:5173";
const provider = process.env.DEMO_PROVIDER ?? "codex";
const images = fileURLToPath(new URL("../../docs/images/", import.meta.url));
await mkdir(images, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
const evidence = {
    provider,
    captured_at: new Date().toISOString(),
    visible_statuses: [],
    trace_cursors: [],
};
page.on("pageerror", (error) => errors.push(error.message));
try {
    await page.goto(`${base}/runs/new`);
    const option = page.getByRole("option", { name: provider, exact: true });
    await expect(option).toBeEnabled({ timeout: 30000 });
    await page.getByLabel("Agent", { exact: true }).selectOption(provider);
    await page.screenshot({
        path: `${images}/phase6-${provider}-new-run.png`,
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
    page.on("request", (request) => {
        if (request.url().includes(`/runs/${id}/trace`))
            evidence.trace_cursors.push(
                Number(
                    new URL(request.url()).searchParams.get("after_sequence"),
                ),
            );
    });
    let capturedActive = false;
    const deadline = Date.now() + 150000;
    while (Date.now() < deadline) {
        const status = await page
            .getByTestId("run-status")
            .getByTestId("status-badge")
            .textContent()
            .catch(() => null);
        if (status && !evidence.visible_statuses.includes(status))
            evidence.visible_statuses.push(status);
        const count = await page
            .getByRole("list", { name: "Execution trace" })
            .getByRole("listitem")
            .count();
        if (!capturedActive && status === "Running" && count > 6) {
            await page.screenshot({
                path: `${images}/phase6-${provider}-active.png`,
                fullPage: true,
            });
            capturedActive = true;
        }
        if (
            status === "Completed" ||
            (status && /failed|Timed out/i.test(status))
        )
            break;
        await page.waitForTimeout(80);
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
    await writeFile(
        `${images}/phase6-${provider}-evidence.json`,
        JSON.stringify(evidence, null, 2) + "\n",
    );
    expect(evidence.result.status).toBe("completed");
    expect(evidence.result.verification.passed_tests).toBe(3);
    await expect(page.getByText("3 / 3 passed", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Unified diff")).toContainText(
        'return {"status": "ok"}',
    );
    await page.screenshot({
        path: `${images}/phase6-${provider}-completed.png`,
        fullPage: true,
    });
    await page.getByRole("button", { name: "Collapse trace" }).click();
    await page.screenshot({
        path: `${images}/phase6-${provider}-metrics-patch.png`,
        fullPage: true,
    });
    expect(errors).toEqual([]);
    console.log(
        JSON.stringify(
            {
                run_id: id,
                status: evidence.result.status,
                verification: evidence.result.verification,
                provider: evidence.result.provider,
                metrics: evidence.result.metrics,
                visible_statuses: evidence.visible_statuses,
                incremental_trace: evidence.trace_cursors.some((n) => n > 0),
                errors,
            },
            null,
            2,
        ),
    );
} finally {
    await browser.close();
}
