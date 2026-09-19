import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useTrace } from "../src/features/trace/useTrace";
import { useRun } from "../src/api/queries";
import { api } from "../src/api/client";
import { wrapper } from "./helpers";
import { event, run } from "./fixtures";

afterEach(() => vi.useRealTimers());
describe("polling lifecycle", () => {
  it("requests only newer trace events, deduplicates overlap, and drains the terminal tail", async () => {
    const trace = vi
      .spyOn(api, "trace")
      .mockResolvedValueOnce({ events: [event(1)], next_after_sequence: 1 })
      .mockResolvedValueOnce({
        events: [event(1), event(2)],
        next_after_sequence: 2,
      })
      .mockResolvedValue({
        events: [event(3, "run_completed")],
        next_after_sequence: 3,
      });
    const hook = renderHook(({ live }) => useTrace("test-run", live, true), {
      initialProps: { live: true },
      wrapper: wrapper(),
    });
    await waitFor(() => expect(hook.result.current.data?.cursor).toBe(1));
    await waitFor(() => expect(hook.result.current.data?.cursor).toBe(2), {
      timeout: 2500,
    });
    expect(trace.mock.calls[1][1]).toBe(1);
    await waitFor(() =>
      expect(
        hook.result.current.data?.events.map((e) => e.sequence_number),
      ).toEqual([1, 2]),
    );
    hook.rerender({ live: false });
    await waitFor(() => expect(hook.result.current.data?.cursor).toBe(3));
    expect(trace.mock.calls[2][1]).toBe(2);
    vi.useFakeTimers();
    const calls = trace.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });
    expect(trace).toHaveBeenCalledTimes(calls);
  });
  it("polls active run states and stops after completion", async () => {
    const get = vi
      .spyOn(api, "run")
      .mockResolvedValueOnce({ ...run, status: "running" })
      .mockResolvedValue(run);
    const hook = renderHook(() => useRun("test-run"), { wrapper: wrapper() });
    await waitFor(() =>
      expect(hook.result.current.data?.status).toBe("running"),
    );
    await waitFor(
      () => expect(hook.result.current.data?.status).toBe("completed"),
      { timeout: 2500 },
    );
    const calls = get.mock.calls.length;
    vi.useFakeTimers();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });
    expect(get).toHaveBeenCalledTimes(calls);
  });
});
