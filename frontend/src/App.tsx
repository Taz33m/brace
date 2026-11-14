import { useEffect, useState } from "react";
import { api } from "./api";
import { BuildingPage } from "./components/BuildingPage";
import { MapPage } from "./components/MapPage";
import type { Scenario } from "./types";

interface Route { scenario: string | null; step: string | null; building: number | null }

function parse(): Route {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const b = parts.indexOf("b");
  return {
    scenario: parts[0] ?? null,
    step: parts[1] && parts[1] !== "b" && parts[1] !== "-" ? parts[1] : null,
    building: b >= 0 && parts[b + 1] ? Number(parts[b + 1]) : null,
  };
}

export function go(scenario: string, step: string | null, building?: number | null) {
  window.location.hash = `#/${encodeURIComponent(scenario)}/${step ? encodeURIComponent(step) : "-"}${building ? `/b/${building}` : ""}`;
}

export function App() {
  const [route, setRoute] = useState<Route>(parse());
  const [config, setConfig] = useState<{ sdk_key: string; agent_ready: boolean } | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(parse());
    window.addEventListener("hashchange", onHash);
    Promise.all([api.config(), api.scenarios()])
      .then(([c, s]) => { setConfig(c); setScenarios(s); })
      .catch((e) => setError(e.message === "Failed to fetch" || e.message.includes("Internal")
        ? "The Brace server is not running. Start it with: uv run uvicorn backend.server:app --port 8001"
        : `The forecast feeds could not be loaded: ${e.message}`));
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (error) return <div className="fatal">{error}</div>;
  if (!config || !scenarios) return <div className="fatal quiet">Loading the forecast…</div>;
  if (scenarios.length === 0) return <div className="fatal">No scenarios are available. Run <code>uv run python -m scripts.fetch_hazards</code> and reload.</div>;

  const scenario = scenarios.find((s) => s.id === route.scenario) ?? scenarios.find((s) => !s.live) ?? scenarios[0];
  const step = scenario.steps.find((s) => s.id === route.step)?.id ?? scenario.steps[scenario.steps.length - 1]?.id ?? null;

  if (route.building != null) {
    return <BuildingPage key={`${route.building}-${scenario.id}-${step}`} id={route.building} scenario={scenario} step={step}
                         sdkKey={config.sdk_key} agentReady={config.agent_ready} onBack={() => go(scenario.id, step)} />;
  }
  return <MapPage scenarios={scenarios} scenario={scenario} step={step}
                  onScenario={(id) => go(id, null)} onStep={(s) => go(scenario.id, s)} onOpen={(id) => go(scenario.id, step, id)} />;
}
