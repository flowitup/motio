import type { Project } from "@/lib/api";

/** Refetch interval for a list of projects: quickly while one is queued or running, rarely when nothing is. */
export const BUSY_MS = 4_000;
export const IDLE_MS = 20_000;
export const busy = (list?: Project[]) => !!list?.some((p) => p.status === "queued" || p.status === "running");
export const pollProjects = (q: { state: { data?: Project[] } }) => (busy(q.state.data) ? BUSY_MS : IDLE_MS);
