import { useQuery } from "@tanstack/react-query";
import { api, ApiError, type RunFilters, type Status } from "./client";

export const active = (status?: Status) =>
  status === "queued" || status === "running" || status === "verifying";
export const retry = (attempt: number, error: Error) =>
  !(error instanceof ApiError && error.status < 500) && attempt < 2;
export const useTasks = () =>
  useQuery({
    queryKey: ["tasks"],
    queryFn: ({ signal }) => api.tasks(signal),
    staleTime: 60_000,
  });
export const useAgents = () =>
  useQuery({
    queryKey: ["agents"],
    queryFn: ({ signal }) => api.agents(signal),
    staleTime: 30_000,
  });
export const useStrategies = () =>
  useQuery({
    queryKey: ["strategies"],
    queryFn: ({ signal }) => api.strategies(signal),
    staleTime: 60_000,
  });
export const useExperiments = () =>
  useQuery({
    queryKey: ["experiments"],
    queryFn: ({ signal }) => api.experiments(signal),
    refetchInterval: 5000,
  });
export const useExperiment = (id: string) =>
  useQuery({
    queryKey: ["experiment", id],
    queryFn: ({ signal }) => api.experiment(id, signal),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  });
export const useTask = (id: string) =>
  useQuery({
    queryKey: ["task", id],
    queryFn: ({ signal }) => api.task(id, signal),
    enabled: !!id,
    staleTime: 60_000,
  });
export const useRuns = (filters: RunFilters) =>
  useQuery({
    queryKey: ["runs", filters],
    queryFn: ({ signal }) => api.runs(filters, signal),
    refetchInterval: 5000,
  });
export const useRun = (id: string) =>
  useQuery({
    queryKey: ["run", id],
    queryFn: ({ signal }) => api.run(id, signal),
    refetchInterval: (query) =>
      active(query.state.data?.status) ? 1000 : false,
  });
