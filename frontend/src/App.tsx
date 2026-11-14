import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Scenario } from "./types";
import { OwnerSignIn, RecoveryEntry, ResidentEntry } from "./recovery/RecoveryEntry";
import { consumeResidentInvitation, parseAppRoute, prepareHash } from "./recovery/routes";
import type { AppRoute } from "./recovery/routes";

type PrepareRoute = Extract<AppRoute, { kind: "prepare" }>;

const BuildingPage = lazy(() => import("./components/BuildingPage").then(module => ({ default: module.BuildingPage })));
const MapPage = lazy(() => import("./components/MapPage").then(module => ({ default: module.MapPage })));
const VrPage = lazy(() => import("./components/VrPage").then(module => ({ default: module.VrPage })));
const SiteModelPage = lazy(() => import("./components/SiteModelPage").then(module => ({ default: module.SiteModelPage })));
const FurnishPage = lazy(() => import("./components/FurnishPage").then(module => ({ default: module.FurnishPage })));
const PlacePage = lazy(() => import("./components/PlacePage").then(module => ({ default: module.PlacePage })));
const ScenePage = lazy(() => import("./components/ScenePage").then(module => ({ default: module.ScenePage })));
const Story = lazy(() => import("./story/Story").then(module => ({ default: module.Story })));
const HomePage = lazy(() => import("./story/Story").then(module => ({ default: module.HomePage })));
const ScheduleTree = lazy(() => import("./story/ScheduleTree").then(module => ({ default: module.ScheduleTree })));
const InsidePov = lazy(() => import("./story/InsidePov").then(module => ({ default: module.InsidePov })));
const InsurerFile = lazy(() => import("./story/InsurerFile").then(module => ({ default: module.InsurerFile })));
const FloodTest = lazy(() => import("./story/FloodTest").then(module => ({ default: module.FloodTest })));
const WalkPage = lazy(() => import("./components/WalkPage").then(module => ({ default: module.WalkPage })));

/** Read and scrub invitations before any child can issue a network request. */
export function captureBrowserRoute(): AppRoute {
  const route = parseAppRoute(window.location.hash);
  try {
    const invitation = consumeResidentInvitation(window.location, window.history);
    return route.kind === "resident" ? { ...route, invitation_token: invitation } : route;
  } catch {
    return { kind: "invalid", message: "This invitation is invalid. Request a new invitation." };
  }
}

// React StrictMode invokes initializers twice. The first read must survive URL scrubbing.
let initialRoute: AppRoute | undefined;
export function captureInitialRoute(): AppRoute { return initialRoute ??= captureBrowserRoute(); }

export function go(scenario: string, step: string | null, building?: number | null) {
  window.location.hash = prepareHash(scenario, step, building ?? null);
}

export function App() {
  const [route, setRoute] = useState<AppRoute>(captureInitialRoute);
  useEffect(() => {
    initialRoute = undefined;
    const onHash = () => setRoute(captureBrowserRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const consumed = useCallback((invitation: string) => {
    initialRoute = undefined;
    setRoute(current => current.kind === "resident" && current.invitation_token === invitation
      ? { ...current, invitation_token: null } : current);
  }, []);
  if (route.kind === "resident") return <ResidentEntry key={route.invitation_token === null ? "resident-session" : `resident-invitation:${route.invitation_token}`}
    invitation_token={route.invitation_token} on_invitation_consumed={consumed} />;
  if (route.kind === "recovery") return <RecoveryEntry case_id={route.case_id} />;
  if (route.kind === "invalid") return <div className="fatal" role="alert">{route.message}</div>;
  if (route.kind === "schedule") return <Suspense fallback={<div className="st-wait" />}><ScheduleTree key={route.controller ? "ctl" : "screen"} site={route.site} controller={route.controller} /></Suspense>;
  if (route.kind === "inside") return <Suspense fallback={<div className="st-wait" />}><InsidePov site={route.site} scan={route.scan} stereo={route.stereo} /></Suspense>;
  if (route.kind === "file") return <Suspense fallback={<div className="st-wait" />}><InsurerFile site={route.site} scan={route.scan} /></Suspense>;
  if (route.kind === "flood") return <Suspense fallback={<div className="st-wait" />}><FloodTest site={route.site} /></Suspense>;
  if (route.kind === "home") return <Suspense fallback={<div className="st-wait" />}><HomePage /></Suspense>;
  if (route.kind === "story") return <Suspense fallback={<div className="st-wait" />}><Story key={route.id} id={route.id} /></Suspense>;
  if (route.kind === "furnish") return <Suspense fallback={<div className="fatal quiet" role="status">Loading the room…</div>}>
    <FurnishPage key={route.scan} id={route.building} scan={route.scan} />
  </Suspense>;
  if (route.kind === "place") return <Suspense fallback={<div className="fatal quiet" role="status">Loading the building…</div>}>
    <PlacePage key={`${route.model}:${route.watch}`} model={route.model} watch={route.watch} />
  </Suspense>;
  if (route.kind === "model") return <Suspense fallback={<div className="fatal quiet" role="status">Loading the site model…</div>}>
    <SiteModelPage key={route.building ?? "all"} id={route.building} />
  </Suspense>;
  return <Suspense fallback={<div className="fatal quiet" role="status">Loading preparation tools…</div>}>
    {route.kind === "walk" || route.kind === "scene"
      ? <PrepareApp route={{ kind: "prepare", scenario: route.scenario, step: route.step, building: route.building, vr: false }} walk={route.kind === "walk"} scene={route.kind === "scene"} />
      : <PrepareApp route={route} />}
  </Suspense>;
}

function PrepareApp({ route, walk = false, scene = false }: { route: PrepareRoute; walk?: boolean; scene?: boolean }) {
  const [config, setConfig] = useState<{ sdk_key: string; agent_ready: boolean; voice_ready: boolean } | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    setError(null);
    Promise.all([api.config(), api.scenarios()])
      .then(([c, s]) => { if (current) { setConfig(c); setScenarios(s); } })
      .catch((e: unknown) => {
        if (!current) return;
        const status = (e as { status?: number })?.status;
        if (status === 401 || status === 403) { setNeedsSignIn(true); return; }
        const message = e instanceof Error ? e.message : "The forecast could not be loaded.";
        setError(`The forecast could not be loaded: ${message}`);
      });
    return () => { current = false; };
  }, [reload]);

  if (needsSignIn) return <OwnerSignIn on_signed_in={() => { setNeedsSignIn(false); setReload(value => value + 1); }} />;
  if (error) return <div className="fatal">{error}</div>;
  if (!config || !scenarios) return <div className="fatal quiet">Loading the forecast…</div>;
  if (scenarios.length === 0) return <div className="fatal">No scenarios are available. Run <code>uv run python -m scripts.fetch_hazards</code> and reload.</div>;

  const scenario = scenarios.find((s) => s.id === route.scenario) ?? scenarios[0];
  const step = scenario.steps.find((s) => s.id === route.step)?.id ?? scenario.steps[scenario.steps.length - 1]?.id ?? null;

  // Keyed by the building alone: moving the forecast clock keeps the walk-through, and its conversation, where they are.
  if (scene && route.building != null) return <ScenePage key={route.building} id={route.building} scenario={scenario} step={step} />;
  if (walk && route.building != null) return <WalkPage key={route.building} id={route.building} scenario={scenario} step={step} voiceReady={config.voice_ready} />;
  if (route.vr && route.building != null) return <VrPage key={route.building} id={route.building} scenario={scenario} step={step} />;
  if (route.building != null) {
    return <BuildingPage key={`${route.building}-${scenario.id}-${step}`} id={route.building} scenario={scenario} step={step}
                         sdkKey={config.sdk_key} agentReady={config.agent_ready} voiceReady={config.voice_ready} onBack={() => go(scenario.id, step)} />;
  }
  return <MapPage scenarios={scenarios} scenario={scenario} step={step}
                  onScenario={(id) => go(id, null)} onStep={(s) => go(scenario.id, s)} onOpen={(id) => go(scenario.id, step, id)} />;
}
