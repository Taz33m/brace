import { useEffect, useRef, useState } from "react";
import Lenis from "lenis";
import { api } from "../api";
import { Sky, CabinWindow } from "./Cabin";
import { gsap, ScrollTrigger, prefersReducedMotion, smooth } from "./gsap";
import { DeskStory } from "./DeskStory";
import { FireStory, FloodStory, StormStory } from "./StormStory";
import "./story.css";

export type StoryId = "storm" | "flood" | "desk" | "after" | "fire";

/** The scenarios, by the city they happen in. The home page lists them; each is told by scrolling. */
export const STORIES: { id: StoryId; where: string; title: string; line: string }[] = [
  { id: "storm", where: "Houston", title: "Thirty-nine hours", line: "You own the building. Hurricane Beryl arrives in 39 hours. What it is worth, what still fits, and three decisions that are yours." },
  { id: "flood", where: "Houston", title: "Before the water", line: "A community in a high-risk flood zone. Which buildings stand on the lowest ground, and what to move first." },
  { id: "desk", where: "Houston", title: "Five buildings, two crews", line: "Not enough crew hours for every roof. Scroll the clock and watch the desk decide who goes where." },
  { id: "after", where: "Houston", title: "After the storm", line: "One room as it was scanned, cleared, and furnished again." },
  { id: "fire", where: "Los Angeles", title: "Before the fire weather", line: "A Red Flag Warning, forty-three hours out. What stands within five feet of the walls, and what clearing it costs." },
];

/** Smooth scrolling, as in the plane project: the page always starts at the top, and the scroll drives every timeline. */
function useSmoothScroll() {
  useEffect(() => {
    document.documentElement.classList.add("st-on");
    if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
    window.scrollTo(0, 0);
    ScrollTrigger.config({ ignoreMobileResize: true });
    let lenis: Lenis | null = null;
    const tick = (time: number) => { lenis?.raf(time * 1000); };
    if (!prefersReducedMotion()) {
      lenis = new Lenis({ duration: 1.25, easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), smoothWheel: true, wheelMultiplier: 0.9 });
      lenis.on("scroll", ScrollTrigger.update);
      smooth.lenis = lenis;
      gsap.ticker.add(tick);
      gsap.ticker.lagSmoothing(0);
    }
    return () => {
      document.documentElement.classList.remove("st-on");
      gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(500, 33);
      smooth.lenis = null;
      lenis?.destroy();
      window.scrollTo(0, 0);
    };
  }, []);
}

export function Story({ id }: { id: StoryId }) {
  useSmoothScroll();
  // Escape goes back to the scenarios.
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") window.location.hash = "#/"; };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  return (
    <div className="st" data-story={id}>
      <a className="st-home" href="#/">Brace</a>
      {id === "storm" ? <StormStory /> : id === "flood" ? <FloodStory /> : id === "fire" ? <FireStory /> : id === "desk" ? <DeskStory /> : <AfterStory />}
    </div>
  );
}

/** After the storm: one room, and the scroll takes the furniture out of it and puts it back. */
function AfterStory() {
  const section = useRef<HTMLElement>(null), frame = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [furniture, setFurniture] = useState(false);
  const now = useRef({ state: 0, loaded: false, furniture: false });
  now.current.loaded = loaded; now.current.furniture = furniture;

  // The room is furnished again only once its furniture has been made.
  useEffect(() => { api.furnish(4303509, "39JTmBzqWxr").then((r) => setFurniture(r.contents > 0 && (r.models_made ?? 0) >= r.contents)).catch(() => {}); }, []);

  useEffect(() => {
    const el = section.current;
    if (!el) return;
    const trigger = ScrollTrigger.create({
      trigger: el, start: "top top", end: "bottom bottom",
      onUpdate: (self) => {
        const s = now.current, want = self.progress < 0.3 ? 1 : self.progress < 0.68 || !s.furniture ? 2 : 3;
        if (want === s.state || !s.loaded) return;
        s.state = want;
        try { frame.current?.contentWindow?.dispatchEvent(new KeyboardEvent("keydown", { key: String(want), bubbles: true })); } catch { /* gone */ }
      },
    });
    return () => trigger.kill();
  }, []);

  return (
    <>
      <section ref={section} className="st-room-section" aria-label="One room, three states">
        <div className="st-stage st-sticky">
          <iframe ref={frame} className="st-site st-shown" title="A living room at The Parker" src="/#/furnish/4303509/39JTmBzqWxr" data-shot="room" tabIndex={-1} onLoad={() => setLoaded(true)} />
        </div>
      </section>
      <section className="st-end"><h2>Brace</h2><a href="#/">All scenarios</a></section>
    </>
  );
}

/** The home page: the cabin, and the scenarios to choose from. */
export function HomePage() {
  useEffect(() => {
    document.documentElement.classList.add("st-on");
    return () => document.documentElement.classList.remove("st-on");
  }, []);
  return (
    <div className="st st-homepage">
      <Sky />
      <div className="st-stage st-home-stage">
        <CabinWindow />
        <div className="st-safe">
          <h1 className="st-lead st-home-mark">Brace</h1>
          <p className="st-home-line">A storm on the way, turned into work,<br />for every building in its path.</p>
          <nav className="st-menu" aria-label="Scenarios">
            {STORIES.map((s, i) => (
              <a key={s.id} href={`#/story/${s.id}`}>
                {(i === 0 || STORIES[i - 1].where !== s.where) && <em>{s.where}</em>}
                <strong>{s.title}</strong>
                <span>{s.line}</span>
              </a>
            ))}
          </nav>
          <p className="st-home-more"><a href="#/beryl-2024">The portfolio map</a><a href="#/model">The site model</a></p>
        </div>
      </div>
    </div>
  );
}
