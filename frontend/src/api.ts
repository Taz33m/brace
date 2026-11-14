import type { Approval, Board, Desk, FurnishScene, Place, PlaceAnswer, PlaceLive, Building, ClockChange, Facing, FindHit, Measured, Portfolio, ResidentReport, SavedStep, Scenario, ScenarioMap, SiteModel, SiteScene } from "./types";

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
  /** The forecast as a table: one row per building, keyed by the CoStar property id. step "all" is every forecast step. */
  forecastCsv: (scenario: string, step: string | null) => `/api/scenarios/${scenario}/forecast.csv${q({ step })}`,
  furnish: (id: number, scan: string) => get<FurnishScene>(`/api/buildings/${id}/furnish/${scan}`),
  furnishMake: (id: number, scan: string) => fetch(`/api/buildings/${id}/furnish/${scan}/make`, { method: "POST" }).then(async (r) => {
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "the models could not be made");
    return r.json() as Promise<{ started: boolean }>;
  }),
  place: (model: string) => get<Place>(`/api/places/${model}`),
  placeFind: (model: string, query: string, start: string | null, mover: "walking" | "wheelchair" = "walking", chairIn = 27) =>
    get<PlaceAnswer>(`/api/places/${model}/find${q({ q: query, start, mover, chair_in: String(chairIn) })}`),
  desk: (scenario: string, step: string) => get<Desk>(`/api/desk${q({ scenario, step })}`),
  placeLive: (model: string) => get<PlaceLive>(`/api/places/${model}/live`),
  placeTell: (model: string, body: Omit<PlaceLive, "rev">) =>
    fetch(`/api/places/${model}/live`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => undefined),
  placePano: (model: string, position: string, face: number) => `/api/places/${model}/pano/${position}/${face}.jpg?size=1024`,
  scene: (id: number) => get<SiteScene>(`/api/buildings/${id}/scene`),
  siteModel: (id: number) => get<SiteModel>(`/api/buildings/${id}/site-model`),
  board: () => get<Board>("/api/site-model/board"),
  measured: (id: number, scenario: string, step: string | null) =>
    get<{ actions: Record<string, Measured[]> }>(`/api/buildings/${id}/measured${q({ scenario, step })}`).then((r) => r.actions),
  find: (id: number, query: string) => get<{ query: string; said: string; hits: FindHit[] }>(`/api/buildings/${id}/find${q({ q: query })}`),
  report: (id: number, text: string, scan_id: string | null) =>
    fetch(`/api/buildings/${id}/reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, scan_id }) })
      .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "could not file the report"); return r.json() as Promise<ResidentReport>; }),
  clearReports: (id: number) => fetch(`/api/buildings/${id}/reports`, { method: "DELETE" }).then(() => undefined),
  /** Approve one action of the saved plan. Always answers with something to say: a refusal from the server
      (no resident case bound, not signed in, delivery switched off) is reported as not approved, never passed over. */
  approve: (id: number, scenario: string, step: string | null, actionId: string): Promise<Approval> =>
    fetch("/api/vr/approve", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ building: id, scenario, step, action_id: actionId }) })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (r.ok && typeof body.say === "string") return body as Approval;
        const why = typeof body.detail === "string" ? body.detail : body.detail?.message ?? body.error?.message ?? "The server refused it.";
        return { ok: false, say: `Not approved, and nothing was published. ${why}` };
      })
      .catch(() => ({ ok: false, say: "Not approved. The approval could not reach the laptop." })),
  startPlan: (id: number, scenario: string, step: string | null) =>
    fetch(`/api/buildings/${id}/plan${q({ scenario, step })}`, { method: "POST" }).then((r) => { if (!r.ok) throw new Error("start failed"); return r.json(); }),
  streamUrl: (id: number, scenario: string, step: string | null, replay: boolean, speed = 5) =>
    `/api/buildings/${id}/plan/stream${q({ scenario, step, replay: replay ? "true" : null, speed: replay ? String(speed) : null })}`,
  file: (id: number, path: string) => `/api/buildings/${id}/file/${path}`,
  aerial: (id: number) => `/api/buildings/${id}/aerial.jpg`,
  oblique: (id: number, view: string, structure?: string | null) => `/api/buildings/${id}/oblique/${view}.jpg${q({ structure })}`,
};
