import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type TraceEvent } from "../../api/client";

export type TraceState = {
  events: TraceEvent[];
  cursor: number;
  more: boolean;
};
export function mergeEvents(previous: TraceEvent[], incoming: TraceEvent[]) {
  return [
    ...new Map(
      [...previous, ...incoming].map((event) => [event.sequence_number, event]),
    ).values(),
  ].sort((a, b) => a.sequence_number - b.sequence_number);
}

export function useTrace(id: string, live: boolean, enabled: boolean) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["trace", id],
    enabled,
    queryFn: async ({ signal }): Promise<TraceState> => {
      const previous = cache.getQueryData<TraceState>(["trace", id]);
      const page = await api.trace(id, previous?.cursor ?? 0, signal);
      return {
        events: mergeEvents(previous?.events ?? [], page.events),
        cursor: Math.max(previous?.cursor ?? 0, page.next_after_sequence),
        more: page.events.length === 100,
      };
    },
    refetchInterval: (query) =>
      query.state.data?.more ? 100 : live ? 1000 : false,
  });
  // Drain the final committed trace even if the status poll wins the race.
  useEffect(() => {
    if (enabled && !live)
      void cache.invalidateQueries({ queryKey: ["trace", id] });
  }, [cache, id, live, enabled]);
  return query;
}
