import type { Building, ClockChange, Facing, Portfolio, SavedStep, Scenario, ScenarioMap } from "./types";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not JSON */ }
    throw Object.assign(new Error(detail), { status: r.status });
  }
  return r.json();
}

const q = (params: Record<string, string | null | undefined>) => {
  const s = Object.entries(params).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`).join("&");
  return s ? `?${s}` : "";
};

export const api = {
  config: () => get<{ sdk_key: string; agent_ready: boolean; voice_ready: boolean }>("/api/config"),
  scenarios: () => get<Scenario[]>("/api/scenarios"),
  scenario: (id: string, step: string | null) => get<Scenario & { step: string | null; map: ScenarioMap }>(`/api/scenarios/${id}${q({ step })}`),
  portfolio: (scenario: string, step: string | null, manager: string, kind: string) =>
    get<Portfolio>(`/api/portfolio${q({ scenario, step, manager, kind })}`),
  building: (id: number, scenario: string, step: string | null) => get<Building>(`/api/buildings/${id}${q({ scenario, step })}`),
  facing: (id: number, scenario: string, step: string | null) => get<Facing>(`/api/buildings/${id}/facing${q({ scenario, step })}`),
  savedSteps: (id: number, scenario: string) => get<{ plans: SavedStep[] }>(`/api/buildings/${id}/plans${q({ scenario })}`).then((r) => r.plans),
  clock: (id: number, scenario: string, earlier: string, later: string) => get<ClockChange>(`/api/buildings/${id}/clock${q({ scenario, earlier, later })}`),
  startPlan: (id: number, scenario: string, step: string | null) =>
    fetch(`/api/buildings/${id}/plan${q({ scenario, step })}`, { method: "POST" }).then((r) => { if (!r.ok) throw new Error("start failed"); return r.json(); }),
  streamUrl: (id: number, scenario: string, step: string | null, replay: boolean, speed = 5) =>
    `/api/buildings/${id}/plan/stream${q({ scenario, step, replay: replay ? "true" : null, speed: replay ? String(speed) : null })}`,
  file: (id: number, path: string) => `/api/buildings/${id}/file/${path}`,
  aerial: (id: number) => `/api/buildings/${id}/aerial.jpg`,
  oblique: (id: number, view: string, structure?: string | null) => `/api/buildings/${id}/oblique/${view}.jpg${q({ structure })}`,
};
