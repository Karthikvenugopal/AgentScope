import { describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../src/api/client";
import { run, patch } from "./fixtures";

describe("typed API transport", () => {
  it("preserves nullable inference data and uses generated path parameters", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(run), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const result = await api.run("test-run");
    expect(result.metrics?.inference?.input_tokens).toBeNull();
    expect(fetch.mock.calls[0][0].url).toMatch(/\/api\/v1\/runs\/test-run$/);
  });
  it("passes API error codes without losing status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: "run_not_found", message: "Run was not found" },
          }),
          { status: 404 },
        ),
      ),
    );
    await expect(api.run("missing")).rejects.toMatchObject({
      code: "run_not_found",
      status: 404,
    });
  });
  it("handles text patches and non-JSON outages", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(patch))
        .mockResolvedValueOnce(
          new Response("proxy unavailable", { status: 502 }),
        ),
    );
    expect(await api.patch("test-run")).toBe(patch);
    // openapi-fetch returns text errors for parseAs:text; the wrapper stays safe.
    await expect(api.patch("test-run")).rejects.toBeInstanceOf(ApiError);
  });
});
