// Real browser + real API only. No network interception or invented run data.
/* global document, innerWidth */
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.DEMO_URL ?? "http://127.0.0.1:5173";
const images = fileURLToPath(new URL("../../docs/images/", import.meta.url));
await mkdir(images, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({
    viewport: { width: 1440, height: 1100 },
    deviceScaleFactor: 1,
});
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const evidence = {
    base,
    captured_at: new Date().toISOString(),
    environment_note:
        process.env.DEMO_NOTE ?? "Default runtime resource limits",
    runs: [],
    screenshots: [],
};
try {
    await page.goto(base);
    await expect(
        page.getByRole("heading", { name: /verifiable outcomes/ }),
    ).toBeVisible();
    await page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("link", { name: "New Run" })
        .click();
    await expect(
        page.getByRole("heading", { name: "Fix the health response" }),
    ).toBeVisible();
    await page.screenshot({ path: `${images}/new-run.png`, fullPage: true });
    evidence.screenshots.push("new-run.png");

    // The benchmark takes ~1 second. Real polls may skip sub-second stages, so
    // repeat real submissions if needed to observe both active statuses.
    let complete;
    for (let attempt = 0; attempt < 10; attempt++) {
        if (attempt) await page.goto(`${base}/runs/new`);
        await expect(
            page.getByRole("button", { name: /Run Agent/ }),
        ).toBeEnabled();
        const accepted = page.waitForResponse(
            (response) =>
                response.request().method() === "POST" &&
                response.url().endsWith("/api/v1/runs"),
        );
        await page.getByRole("button", { name: /Run Agent/ }).click();
        const response = await accepted;
        expect(response.status()).toBe(202);
        const submission = await response.json();
        const record = {
            run_id: submission.run_id,
            accepted_status: submission.status,
            visible_statuses: [],
            trace_cursors: [],
        };
        evidence.runs.push(record);
        const traceListener = (request) => {
            if (request.url().includes(`/runs/${record.run_id}/trace`))
                record.trace_cursors.push(
                    Number(
                        new URL(request.url()).searchParams.get(
                            "after_sequence",
                        ),
                    ),
                );
        };
        page.on("request", traceListener);
        const deadline = Date.now() + 60000;
        let activeShot = false;
        while (Date.now() < deadline) {
            const badge = page
                .getByTestId("run-status")
                .getByTestId("status-badge");
            const status = await badge.textContent().catch(() => null);
            if (status && !record.visible_statuses.includes(status))
                record.visible_statuses.push(status);
            if (
                !activeShot &&
                ["Running", "Verifying"].includes(status) &&
                (await page
                    .getByRole("list", { name: "Execution trace" })
                    .getByRole("listitem")
                    .count()) > 2
            ) {
                await page.screenshot({
                    path: `${images}/active-trace.png`,
                    fullPage: true,
                });
                activeShot = true;
            }
            if (status === "Completed") break;
            if (status && /failed|Timed out/i.test(status))
                throw new Error(`Real run did not complete: ${record.run_id}`);
            await page.waitForTimeout(40);
        }
        await expect(
            page.getByText("3 / 3 passed", { exact: true }),
        ).toBeVisible();
        await expect(page.getByLabel("Unified diff")).toContainText(
            '+    return {"status": "ok"}',
        );
        await expect(
            page.getByText("27 events received", { exact: false }),
        ).toBeVisible();
        complete = record;
        page.off("request", traceListener);
        if (
            record.visible_statuses.includes("Running") &&
            record.visible_statuses.includes("Verifying") &&
            activeShot
        )
            break;
    }
    if (
        !complete?.visible_statuses.includes("Running") ||
        !complete.visible_statuses.includes("Verifying")
    )
        throw new Error(
            "Polling did not observe both active stages; screenshots retained, but demo is not complete.",
        );
    await page.screenshot({
        path: `${images}/completed-run.png`,
        fullPage: true,
    });
    await page.getByRole("button", { name: "Collapse trace" }).click();
    await page.screenshot({
        path: `${images}/metrics-patch.png`,
        fullPage: true,
    });
    evidence.screenshots.push(
        "active-trace.png",
        "completed-run.png",
        "metrics-patch.png",
    );
    const runResponse = await page.request.get(
        `${base}/api/v1/runs/${complete.run_id}`,
    );
    evidence.result = await runResponse.json();
    await page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("link", { name: "Runs", exact: true })
        .click();
    await page.getByLabel("Status", { exact: true }).selectOption("completed");
    await expect(
        page.getByRole("link", {
            name: complete.run_id.slice(0, 10),
            exact: true,
        }),
    ).toBeVisible();
    await page.setViewportSize({ width: 820, height: 1180 });
    await page.goto(`${base}/runs/${complete.run_id}`);
    await expect(
        page.getByRole("heading", { name: "Verification passed" }),
    ).toBeVisible();
    const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
    );
    expect(overflow).toBe(false);
    expect(errors).toEqual([]);
    await writeFile(
        `${images}/demo-evidence.json`,
        JSON.stringify(evidence, null, 2) + "\n",
    );
    console.log(JSON.stringify(evidence, null, 2));
} finally {
    await browser.close();
}
