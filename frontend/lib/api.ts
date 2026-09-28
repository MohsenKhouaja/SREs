import useSWR from "swr";
import type {Approval, Investigation, LabRun} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {"Content-Type": "application/json", ...init?.headers},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

const fetcher = <T,>(path: string) => apiFetch<T>(path);

export function useInvestigations() {
  return useSWR<{investigations: Investigation[]}>("/investigations", fetcher, {refreshInterval: 4000});
}

export function useInvestigation(id?: string) {
  return useSWR<Investigation>(id ? `/investigation/${id}` : null, fetcher, {refreshInterval: 2500});
}

export function useApprovals() {
  return useSWR<{approvals: Approval[]}>("/approvals", fetcher, {refreshInterval: 3000});
}

export function useApproval(id?: string) {
  return useSWR<Approval>(id ? `/approvals/${id}` : null, fetcher, {refreshInterval: 2500});
}

export function useLabRun(id?: string | null) {
  return useSWR<LabRun>(id ? `/lab/runs/${id}` : null, fetcher, {refreshInterval: 4000});
}

export function formatScenario(scenario: string): string {
  return scenario.split("-").map((word) => word[0]?.toUpperCase() + word.slice(1)).join(" ");
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function formatTime(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeStyle: "short"}).format(new Date(value));
}

export function duration(start: string, end?: string | null): string {
  const milliseconds = new Date(end || Date.now()).getTime() - new Date(start).getTime();
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
