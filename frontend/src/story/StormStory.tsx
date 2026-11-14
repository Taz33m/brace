import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import { CabinWindow, Sky, SplitChars } from "./Cabin";
import { gsap, prefersReducedMotion, scrollToY } from "./gsap";

/**
 * Before the weather arrives, told by scrolling. Through the cabin window, down through cloud onto the
 * city with every building in the warning lit, down onto one building, what it is worth and the hours it
 * has, and then the live product: the site in three dimensions with the plan on it. Nothing here advances
 * by itself; the scroll is the film's clock, and it runs backwards as well as forwards.
 *
 * One story, two cities: the hurricane over Houston and the fire weather over Los Angeles are the same
 * component given a different building, forecast and words.
 */
const RING = [1, 0.256, 0.064, 0.016];            // each aerial covers this share of the widest one's width, all on one centre
const rad = (deg: number) => (deg * Math.PI) / 180;
const clamp = (v: number) => Math.max(0, Math.min(1, v));
const dollars = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
/** A large sum the way it is said aloud: $22.9 billion, $29.95 million. */
const sum = (n: number) => (n >= 1e9 ? `$${(n / 1e9).toFixed(1)} billion` : n >= 1e6 ? `$${(n / 1e6).toFixed(2).replace(/\.?0+$/, "")} million` : dollars(n));

/** Up to three lines on why this building: the chapter's own reasons first, and where the low ground is when that is the point. */
function why(reasons: string[], first: RegExp | undefined, ground: { lowest: { id: string }[]; spread_m: number } | null | undefined): string[] {
  const ordered = first ? [...reasons.filter((r) => first.test(r)), ...reasons.filter((r) => !first.test(r))] : reasons;
  if (!ground) return ordered.slice(0, 3);
  const ids = ground.lowest.map((s) => s.id);
  const named = ids.length > 1 ? `${ids.slice(0, -1).join(", ")} and ${ids[ids.length - 1]} stand` : `${ids[0]} stands`;
  return [ordered[0], `${named} on the lowest ground, ${ground.spread_m.toFixed(1)} m below the highest building (Vexcel terrain model)`, ...ordered.slice(1, 2)].filter(Boolean);
}

interface Descent { levels: { level: number; bounds: [number, number, number, number]; url: string }[]; site: { bounds: [number, number, number, number]; captured?: string } }
type Cue = { hash?: string; key?: string; click?: string; text?: RegExp; wait?: number };
interface Chapter {
  building: number; scenario: string; step: string;
  room?: string;                                   // a scan to step inside on the way, where there is one worth the time
  label: string;                                   // what the section is, for a screen reader
  hero: { lead: [string, string]; counter: [string, string]; said: string; aside: [string, string]; asideText: string; place: string; statement: string };
  whisper: string;                                 // the line in the cloud
  city: string; counted: string;                   // "Houston, Texas", "buildings in the forecast wind field"
  clock: string;                                   // "hours until the wind arrives"
  why?: RegExp;                                    // the reasons this chapter is about, shown first
  ground?: boolean;                                // say which structures stand on the lowest ground
  // What the live site shows at each stretch of scroll, counted from where the site comes up. Each state says
  // everything it needs, so it reads the same scrolling up as down.
  site: { from: number; cues: Cue[] }[];
  length: number;                                  // how long the site stays, in the timeline's units
  notice?: number;                                 // the state in which Enter approves the notice
  stops?: { label: string; from: number }[];       // one building at several moments: the bar under it
}

const at = (scenario: string, step: string, building: number) => `#/scene/${scenario}/${step}/b/${building}`;
const P = 4303509, V = 9519837, G = 1507455;
const HOUSTON: Chapter = {
  building: P, scenario: "beryl-2024", step: "adv33", room: "39JTmBzqWxr", label: "Houston, then one building",
  hero: { lead: ["A storm", "is coming"], counter: ["Thirty-nine", "hours out"], said: "A storm is coming. Thirty-nine hours out.", aside: ["Hurricane Beryl,", "July 2024"],
          asideText: "A replay of the real forecasts, in the order the National Hurricane Center issued them.", place: "Houston, Texas",
          statement: "reads each forecast against every building in its path, and turns it into the work that still fits before the wind arrives." },
  whisper: "Every building in its path.", city: "Houston, Texas", counted: "buildings in the forecast wind field", clock: "hours until the wind arrives",
  site: [
    { from: 0, cues: [{ hash: at("beryl-2024", "adv33", P) }, { key: "1" }] },
    { from: 3.2, cues: [{ hash: at("beryl-2024", "adv33", P) }, { key: "2" }] },
    { from: 6.2, cues: [{ hash: at("beryl-2024", "adv33", P) }, { key: "1" }, { click: ".scene-jobs button", text: /evergreen|pine/i, wait: 1500 }] },
    { from: 9.2, cues: [{ hash: at("beryl-2024", "adv37", P) }, { key: "1", wait: 900 }] },
    { from: 12.2, cues: [{ hash: at("beryl-2024", "adv37", P) }, { click: ".scene-jobs button", text: /resident/i, wait: 400 }] },
    { from: 15.2, cues: [{ hash: at("beryl-2024", "adv39", P) }, { key: "1", wait: 900 }] },
    { from: 18.2, cues: [{ hash: at("beryl-2024", "adv39", P) }, { key: "3", wait: 700 }] },
  ],
  length: 21, notice: 4,
  stops: [{ label: "36 hours", from: 0 }, { label: "12 hours", from: 9.2 }, { label: "The morning after", from: 15.2 }],
};
const LOS_ANGELES: Chapter = {
  building: V, scenario: "la-red-flag-jan-2025", step: "20250105T2240Z", label: "Los Angeles, then one building",
  hero: { lead: ["The wind", "is coming"], counter: ["Forty-three", "hours out"], said: "The wind is coming. Forty-three hours out.", aside: ["Santa Ana windstorm,", "January 2025"],
          asideText: "A replay of the real Red Flag Warnings, in the order the National Weather Service issued them.", place: "Los Angeles, California",
          statement: "reads each warning against every building inside it, and turns it into the work that still fits before the wind arrives." },
  whisper: "Every building inside the warning.", city: "Los Angeles, California", counted: "buildings inside the Red Flag Warning", clock: "hours until the Red Flag Warning starts",
  site: [
    { from: 0, cues: [{ key: "1" }] },
    { from: 3.2, cues: [{ key: "1" }, { click: ".scene-jobs button", text: /limbs|within 5 ft/i, wait: 1500 }] },
    { from: 6.2, cues: [{ key: "1" }, { click: ".scene-jobs button", text: /gutter/i, wait: 1500 }] },
    { from: 9.2, cues: [{ key: "1" }, { click: ".scene-jobs button", text: /defensible/i, wait: 1500 }] },
  ],
  length: 12.5,
};

const HOUSTON_WATER: Chapter = {
  ...HOUSTON, building: G, room: undefined, label: "Houston, then one building in a flood zone", why: /flood|ponding|water/i, ground: true,
  hero: { ...HOUSTON.hero, lead: ["The water", "is coming"], said: "The water is coming. Thirty-nine hours out." },
  site: [
    { from: 0, cues: [{ key: "1" }] },
    { from: 3.2, cues: [{ key: "1" }, { click: ".scene-jobs button", text: /channel|south lot/i, wait: 1500 }] },
    { from: 6.2, cues: [{ key: "1" }, { click: ".scene-jobs button", text: /ground-floor/i, wait: 1500 }] },
    { from: 9.2, cues: [{ key: "1" }, { click: ".scene-jobs button", text: /open roof bay/i, wait: 1500 }] },
  ],
  length: 12.5, notice: undefined, stops: undefined,
};

export function StormStory() { return <Before chapter={HOUSTON} />; }
export function FloodStory() { return <Before chapter={HOUSTON_WATER} />; }
export function FireStory() { return <Before chapter={LOS_ANGELES} />; }

function Before({ chapter }: { chapter: Chapter }) {
  return (
    <>
      <Sky whisper={chapter.whisper} />
      <Hero copy={chapter.hero} />
      <CloudRise />
      <Ground chapter={chapter} />
      <section className="st-end">
        <h2>Brace</h2>
        <a href="#/">All scenarios</a>
      </section>
    </>
  );
}

/** The fly-through, as in the plane project: pinned for two and a half screens of scroll, fully reversible. */
function Hero({ copy: words }: { copy: Chapter["hero"] }) {
  const [ready, setReady] = useState(false);
  const section = useRef<HTMLElement>(null), stage = useRef<HTMLDivElement>(null), zoom = useRef<HTMLDivElement>(null);
  const copy = useRef<HTMLDivElement>(null), cue = useRef<HTMLDivElement>(null), cueInner = useRef<HTMLDivElement>(null);
  const aside = useRef<HTMLDivElement>(null), statement = useRef<HTMLDivElement>(null);
  const onReady = useCallback(() => setReady(true), []);

  useEffect(() => {
    const el = section.current, pinned = stage.current;
    if (!el || !pinned) return;
    const skyZoom = document.querySelector<HTMLElement>('[data-sky="zoom"]'), sweep = document.querySelector<HTMLElement>('[data-sky="sweep"]');
    const mm = gsap.matchMedia();
    mm.add({ motion: "(prefers-reduced-motion: no-preference)", reduce: "(prefers-reduced-motion: reduce)" }, (context) => {
      const { motion } = context.conditions as { motion: boolean };
      if (motion) {
        // Letters wait for the window to be ready.
        gsap.set(el.querySelectorAll("[data-char]"), { autoAlpha: 0, yPercent: 35, filter: "blur(14px)" });
        gsap.set([aside.current, cueInner.current], { autoAlpha: 0, y: 24 });
      }
      const timeline = gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: { trigger: el, start: "top top", end: () => `+=${Math.round(window.innerHeight * 2.5)}`, scrub: 1, pin: pinned, anticipatePin: 1, invalidateOnRefresh: true, refreshPriority: 10 },
      });
      if (motion) {
        timeline
          .to(zoom.current, { scale: 5.4, ease: "power2.in", duration: 6.2 }, 0)
          .to(zoom.current, { autoAlpha: 0, duration: 0.6 }, 5.8)
          .to(skyZoom, { scale: 1.15, duration: 7 }, 0)
          .to(copy.current, { scale: 2.4, autoAlpha: 0, ease: "power2.in", duration: 3.4 }, 0)
          .to(cue.current, { autoAlpha: 0, duration: 0.7 }, 0)
          .fromTo(sweep, { xPercent: 30, autoAlpha: 0 }, { xPercent: -10, autoAlpha: 0.95, ease: "power1.in", duration: 2.6 }, 2.6)
          .to(sweep, { xPercent: -45, autoAlpha: 0, ease: "power1.out", duration: 2 }, 5.2)
          .fromTo(statement.current, { y: 150, scale: 0.85, autoAlpha: 0, filter: "blur(10px)" }, { y: 0, scale: 1, autoAlpha: 1, filter: "blur(0px)", ease: "power3.out", duration: 3.2 }, 6.1)
          .to({}, { duration: 0.7 });
      } else {
        timeline
          .to(copy.current, { autoAlpha: 0, duration: 2 }, 0)
          .to(cue.current, { autoAlpha: 0, duration: 0.6 }, 0)
          .to(zoom.current, { autoAlpha: 0, duration: 2 }, 2.4)
          .fromTo(statement.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 2 }, 4.2)
          .to({}, { duration: 1 });
      }
    });
    return () => mm.revert();
  }, []);

  // Headlines resolve out of blur once the window is drawn.
  useEffect(() => {
    const el = section.current;
    if (!ready || !el || prefersReducedMotion()) return;
    const timeline = gsap.timeline({ delay: 0.25 });
    timeline
      .to(el.querySelectorAll("[data-hero-lead] [data-char]"), { autoAlpha: 1, yPercent: 0, filter: "blur(0px)", duration: 1.5, ease: "power3.out", stagger: 0.045 }, 0)
      .to(el.querySelectorAll("[data-hero-counter] [data-char]"), { autoAlpha: 1, yPercent: 0, filter: "blur(0px)", duration: 1.5, ease: "power3.out", stagger: 0.045 }, 0.45)
      .to([aside.current, cueInner.current], { autoAlpha: 1, y: 0, duration: 1.2, ease: "power3.out", stagger: 0.15 }, 0.9);
    return () => { timeline.kill(); };
  }, [ready]);

  return (
    <section ref={section} className="st-hero" aria-label={words.said}>
      <div ref={stage} className="st-stage">
        <CabinWindow zoom={zoom} onReady={onReady} />
        <div className="st-safe">
          <div ref={copy} className="st-fill st-will">
            <h1 data-hero-lead className="st-lead">
              <span className="st-sr">{words.said}</span>
              <SplitChars text={words.lead[0]} className="st-line" /><SplitChars text={words.lead[1]} className="st-line st-indent" />
            </h1>
            <p data-hero-counter className="st-counter" aria-hidden="true">
              <SplitChars text={words.counter[0]} className="st-line st-outdent" /><SplitChars text={words.counter[1]} className="st-line" />
            </p>
            <div ref={aside} className="st-aside">
              <p className="st-aside-title">{words.aside[0]}<br />{words.aside[1]}</p>
              <span className="st-rule" />
              <p className="st-aside-text">{words.asideText}</p>
            </div>
          </div>
          <div ref={cue} className="st-cue">
            <div ref={cueInner}>
              <span className="st-cue-line" />
              <p><span>Scroll to descend</span><span>{words.place}</span></p>
            </div>
          </div>
          <div ref={statement} className="st-statement">
            <div className="st-statement-shade" />
            <p><span className="st-brand">BRACE</span> {words.statement}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

/** A stretch of open scroll where a bank of cloud rises and whites out the view. The clouds live in the fixed sky; this only sets the pace. */
function CloudRise() {
  const zone = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = zone.current;
    if (!el) return;
    const bank = document.querySelector<HTMLElement>('[data-sky="bank"]'), whisper = document.querySelector<HTMLElement>('[data-sky="whisper"]'), veil = document.querySelector<HTMLElement>('[data-sky="veil"]');
    const mm = gsap.matchMedia();
    mm.add({ motion: "(prefers-reduced-motion: no-preference)", reduce: "(prefers-reduced-motion: reduce)" }, (context) => {
      const { motion } = context.conditions as { motion: boolean };
      const timeline = gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger: el, start: "top bottom", end: "bottom bottom", scrub: 1, refreshPriority: 8 } });
      if (motion) {
        timeline
          .fromTo(bank, { yPercent: 105, scale: 1, autoAlpha: 1 }, { yPercent: -8, scale: 1.45, ease: "power1.out", duration: 6 }, 0)
          .fromTo(whisper, { autoAlpha: 0, y: 40, filter: "blur(8px)" }, { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 1.6 }, 2.2)
          .to(whisper, { autoAlpha: 0, y: -30, filter: "blur(6px)", duration: 1.2 }, 4.4)
          .fromTo(veil, { autoAlpha: 0 }, { autoAlpha: 1, duration: 1.8 }, 4.4);
      } else {
        timeline
          .fromTo(bank, { autoAlpha: 0, yPercent: -8, scale: 1.45 }, { autoAlpha: 1, duration: 3 }, 0)
          .fromTo(veil, { autoAlpha: 0 }, { autoAlpha: 1, duration: 1.8 }, 4.4);
      }
    });
    return () => mm.revert();
  }, []);
  return <div ref={zone} aria-hidden="true" className="st-cloud-rise" />;
}

/**
 * From cloud to the ground and on into the product, on one pinned stage:
 *   0 to 10   the cloud clears over the city with every building in the warning lit, and the view falls onto one of them
 *   6 to 10   what that building is, what it is worth, why it was picked, and the hours it has
 *  10 to 14   inside one of its homes, as Matterport scanned it (only where the chapter names a room)
 *  then       the live site in three dimensions, stepping through the plan as the scroll goes on
 */
function Ground({ chapter: c }: { chapter: Chapter }) {
  const section = useRef<HTMLElement>(null);
  const [descent, setDescent] = useState<Descent | null>(null);
  const [hours, setHours] = useState<number | null>(null);
  const [homes, setHomes] = useState<{ name: string; units: number | null; built: number | null; rent: string | null; sold: string | null; soldHow: string | null; work: string | null; why: string[] } | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [city, setCity] = useState<{ homes: number; sold: number; of: number } | null>(null);
  const [room, setRoom] = useState<{ sweep: string; heading: number; yaw: number } | null>(null);
  const [siteLoaded, setSiteLoaded] = useState(false);
  const rings = useRef<(HTMLDivElement | null)[]>([]);
  const dots = useRef<HTMLCanvasElement>(null), ground = useRef<HTMLDivElement>(null);
  const pano = useRef<HTMLDivElement>(null), frame = useRef<HTMLIFrameElement>(null);
  const scrub = useRef<HTMLDivElement>(null), handle = useRef<HTMLElement>(null), dragging = useRef(false);
  const live = useRef({ z: 0, pan: 0, inside: 0, site: -1, loaded: false, timers: [] as number[] });
  live.current.loaded = siteLoaded;

  // Where the live site comes up on the timeline: later when there is a room to step inside first.
  const start = c.room ? 15 : 11.4, total = start + c.length;
  const stops = useMemo(() => c.stops ?? [], [c]);
  // Where the handle sits for a point on the timeline: on a stop, sliding to the next over the last stretch before it.
  const handleAt = useCallback((t: number) => {
    if (stops.length < 2) return 0;
    let x = 0;
    stops.forEach((stop, i) => { if (i) x = Math.max(x, (i - 1 + clamp((t - (start + stop.from - 0.8)) / 0.8)) / (stops.length - 1)); });
    return x;
  }, [stops, start]);

  useEffect(() => {
    let current = true;
    fetch(`/api/buildings/${c.building}/descent`).then((r) => (r.ok ? r.json() : null)).then((d) => { if (current && d) setDescent(d); }).catch(() => {});
    api.building(c.building, c.scenario, c.step).then((b) => {
      if (!current) return;
      setHours(b.threat.hours_left ?? null);
      const record = b.record as { name?: string; units?: number; year_built?: number };
      const sale = b.last_sale as { price?: number; date?: string; basis?: string; portfolio?: boolean } | null | undefined;
      const before = b.plan?.totals.before_arrival;
      setHomes({ name: record.name ?? "", units: record.units ?? null, built: record.year_built ?? null,
                 rent: b.rent ? `Homes advertised at ${dollars(b.rent.low)} to ${dollars(b.rent.high)} a month` : null,
                 sold: sale?.price ? `Last sold for ${sum(sale.price)}${sale.date ? ` in ${sale.date.slice(0, 4)}` : ""}` : null,
                 soldHow: sale?.price ? (sale.portfolio ? "CoStar sale record: its share of a portfolio sale" : "CoStar sale record") : null,
                 work: before?.count ? `${dollars(before.cost_low)} to ${dollars(before.cost_high)} of work still fits` : null,
                 why: why(b.reasons ?? [], c.why, c.ground ? b.ground : null) });
    }).catch(() => {});
    if (c.room) api.furnish(c.building, c.room).then((r) => { if (current) setRoom({ sweep: r.sweep_id, heading: r.standpoint.h, yaw: r.view.yaw_deg }); }).catch(() => {});
    return () => { current = false; };
  }, [c]);

  // Every building in the warning that falls inside the widest photograph, as a point of light on it.
  useEffect(() => {
    const canvas = dots.current, wide = descent?.levels[0]?.bounds;
    if (!canvas || !wide) return;
    let current = true;
    api.portfolio(c.scenario, c.step, "", "").then((p) => {
      if (!current) return;
      setCount(p.shown);
      if (p.value.buildings_with_sale) setCity({ homes: p.homes, sold: p.value.last_sale_total, of: p.value.buildings_with_sale });
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const [west, south, east, north] = wide, size = canvas.width;
      ctx.clearRect(0, 0, size, size);
      for (const [, lat, lon] of p.points) {
        if (lon < west || lon > east || lat < south || lat > north) continue;
        const x = ((lon - west) / (east - west)) * size, y = ((north - lat) / (north - south)) * size;
        const glow = ctx.createRadialGradient(x, y, 0, x, y, 16);
        glow.addColorStop(0, "rgba(255, 194, 14, 0.9)"); glow.addColorStop(0.35, "rgba(255, 194, 14, 0.4)"); glow.addColorStop(1, "rgba(255, 194, 14, 0)");
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, 16, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#fff3c4"; ctx.beginPath(); ctx.arc(x, y, 3.2, 0, Math.PI * 2); ctx.fill();
      }
    }).catch(() => {});
    return () => { current = false; };
  }, [descent, c]);

  // The four photographs sit on one centre, each a quarter the width of the one before. Zooming is scaling them together.
  const zoomTo = useCallback((z: number) => {
    const side = Math.max(window.innerWidth, window.innerHeight);
    const end = ((0.9 * window.innerHeight) / side) / RING[3];      // the last photograph ends nine tenths of the screen's height
    const scale = Math.pow(end, z);
    rings.current.forEach((el, i) => {
      if (!el) return;
      if (i === 4) { el.style.transform = `scale(${scale * RING[3]})`; el.style.setProperty("--line", `${1.5 / (scale * RING[3])}px`); return; }
      const s = scale * RING[i], next = i < 3 ? scale * RING[i + 1] : 0;
      el.style.transform = `scale(${s})`;
      el.style.opacity = i === 0 ? "1" : String(clamp((s - 0.3) / 0.3));
      el.style.visibility = (i > 0 && s < 0.3) || next >= 1.35 ? "hidden" : "visible";
    });
    if (dots.current) { dots.current.style.transform = `scale(${scale})`; dots.current.style.opacity = String(clamp(1 - (scale - 2.2) / 4)); }
  }, []);

  // The live site, told what to show.
  const siteTo = useCallback((state: number) => {
    const now = live.current, win = frame.current?.contentWindow;
    if (state === now.site || !now.loaded || !win) return;
    now.site = state;
    now.timers.forEach((t) => window.clearTimeout(t));
    now.timers = c.site[state].cues.map((cue) => window.setTimeout(() => {
      try {
        if (cue.hash && win.location.hash !== cue.hash) win.location.hash = cue.hash;
        if (cue.key) win.dispatchEvent(new KeyboardEvent("keydown", { key: cue.key, bubbles: true }));
        if (cue.click) [...win.document.querySelectorAll<HTMLElement>(cue.click)].find((el) => !cue.text || cue.text.test(el.textContent ?? ""))?.click();
      } catch { /* the page went away mid-step */ }
    }, cue.wait ?? 0));
  }, [c]);

  useEffect(() => {
    const el = section.current;
    if (!el || !descent) return;
    const q = (name: string) => el.querySelector<HTMLElement>(`[data-g="${name}"]`);
    const state = live.current;
    zoomTo(0);
    const ctx = gsap.context(() => {
      const timeline = gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: { trigger: el, start: "top top", end: "bottom bottom", scrub: 1, invalidateOnRefresh: true },
        onUpdate: () => {
          const t = timeline.time();
          let now = 0;
          c.site.forEach((s, i) => { if (t >= start + s.from) now = i; });
          if (t >= start - 1.4) siteTo(now);
          // The handle sits on the moment the scroll is in, and slides as the scroll crosses to the next.
          const x = handleAt(t);
          if (handle.current && !dragging.current) handle.current.style.left = `${x * 100}%`;
          scrub.current?.querySelectorAll<HTMLElement>("button").forEach((b, i) => b.setAttribute("aria-pressed", String(Math.round(x * (stops.length - 1)) === i)));
        },
      });
      timeline
        .fromTo(ground.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 1.3 }, 0)
        .fromTo(q("city"), { autoAlpha: 0, y: 30, filter: "blur(8px)" }, { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 1 }, 0.5)
        .to(q("city"), { autoAlpha: 0, y: -24, filter: "blur(6px)", duration: 0.8 }, 2.6)
        .to(state, { z: 1, ease: "power1.inOut", duration: 5.6, onUpdate: () => zoomTo(state.z) }, 1.6)
        .fromTo(q("outline"), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.8 }, 6.6)
        .fromTo(q("place"), { autoAlpha: 0, y: 24, filter: "blur(8px)" }, { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 0.9 }, 6.8)
        .fromTo(q("dim"), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.9 }, 7.9)
        .fromTo(q("clock"), { autoAlpha: 0, scale: 0.92, filter: "blur(10px)" }, { autoAlpha: 1, scale: 1, filter: "blur(0px)", ease: "power3.out", duration: 1.1 }, 8)
        .to([q("clock"), q("place")], { autoAlpha: 0, duration: 0.6 }, 10)
        .fromTo(q("backdrop"), { autoAlpha: 0 }, { autoAlpha: 1, duration: 1 }, 10.1);
      if (c.room) {
        timeline
          .fromTo(pano.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 1 }, 10.1)
          .fromTo(state, { pan: -30, inside: 0 }, { pan: 30, inside: 1, duration: 4.2 }, 10)
          .fromTo(q("inside"), { autoAlpha: 0, y: 24, filter: "blur(8px)" }, { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 0.8 }, 11)
          .to(q("inside"), { autoAlpha: 0, duration: 0.6 }, 13.2)
          .to(pano.current, { autoAlpha: 0, duration: 0.7 }, 13.5);
      }
      timeline
        .fromTo(frame.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.9 }, start - 0.9)
        .fromTo(scrub.current, { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.7 }, start - 0.1)
        .to({}, { duration: total - start }, start);
    }, el);
    return () => ctx.revert();
  }, [descent, zoomTo, siteTo, handleAt, c, start, total, stops]);

  // The scanned room, as a panorama the scroll turns.
  useEffect(() => {
    const el = pano.current;
    if (!el || !room || !c.room) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(74, el.clientWidth / el.clientHeight, 0.05, 300);
    camera.rotation.order = "YXZ";
    const loader = new THREE.TextureLoader(), FACE = 40, size = FACE * 2.002, group = new THREE.Group();
    const plane = (face: number) => {
      const tex = loader.load(`/api/buildings/${c.building}/pano/${c.room}/${room.sweep}/${face}.jpg?size=2048`);
      tex.colorSpace = THREE.SRGBColorSpace;
      return new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false }));
    };
    // Sides: face 1 looks along the position's heading; 2, 3 and 4 each turn a further 90 degrees clockwise.
    for (let k = 0; k < 4; k++) { const pivot = new THREE.Group(), m = plane(k + 1); m.position.z = -FACE; pivot.add(m); pivot.rotation.y = -rad(room.heading + 90 * k); group.add(pivot); }
    const caps = new THREE.Group(), up = plane(0), down = plane(5);
    up.position.y = FACE; up.rotation.x = Math.PI / 2; down.position.y = -FACE; down.rotation.x = -Math.PI / 2;
    caps.add(up, down); caps.rotation.y = -rad(room.heading); group.add(caps);
    scene.add(group);
    const resize = () => { renderer.setSize(el.clientWidth, el.clientHeight); camera.aspect = el.clientWidth / el.clientHeight; camera.updateProjectionMatrix(); };
    window.addEventListener("resize", resize);
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      if (getComputedStyle(el).visibility === "hidden") return;      // nothing to draw while the room is not on screen
      const s = live.current;
      camera.fov = 86 - 12 * s.inside; camera.updateProjectionMatrix();
      camera.rotation.set(rad(-8), -rad(room.heading + room.yaw + s.pan), 0);
      renderer.render(scene, camera);
    };
    draw();
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [room, c]);

  // Enter approves the notice when it is the thing on screen. It sends a real message, so nothing else does it.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || c.notice == null || live.current.site !== c.notice) return;
      try { frame.current?.contentWindow?.document.querySelector<HTMLElement>(".scene-approve")?.click(); } catch { /* not there */ }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [c]);

  // Taking the handle, or choosing a stop, moves the scroll to that moment; the scroll then does the rest.
  const goTo = useCallback((stop: number) => {
    const el = section.current;
    if (!el || !stops[stop]) return;
    const top = el.getBoundingClientRect().top + window.scrollY;
    scrollToY(top + ((start + stops[stop].from + 0.5) / total) * (el.offsetHeight - window.innerHeight));
  }, [stops, start, total]);
  const drag = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const track = e.currentTarget, box = track.getBoundingClientRect();
    const where = (x: number) => Math.max(0, Math.min(1, (x - box.left) / box.width));
    dragging.current = true;
    track.setPointerCapture(e.pointerId);
    if (handle.current) handle.current.style.left = `${where(e.clientX) * 100}%`;
    const move = (m: PointerEvent) => { if (handle.current) handle.current.style.left = `${where(m.clientX) * 100}%`; };
    const up = (m: PointerEvent) => {
      track.removeEventListener("pointermove", move); track.removeEventListener("pointerup", up); track.removeEventListener("pointercancel", up);
      dragging.current = false;
      goTo(Math.round(where(m.clientX) * (stops.length - 1)));
    };
    track.addEventListener("pointermove", move); track.addEventListener("pointerup", up); track.addEventListener("pointercancel", up);
  }, [goTo, stops]);

  const site = descent?.site.bounds, last = descent?.levels[3]?.bounds;
  const box = site && last ? {
    left: `${((site[0] - last[0]) / (last[2] - last[0])) * 100}%`, width: `${((site[2] - site[0]) / (last[2] - last[0])) * 100}%`,
    top: `${((last[3] - site[3]) / (last[3] - last[1])) * 100}%`, height: `${((site[3] - site[1]) / (last[3] - last[1])) * 100}%`,
  } : null;

  return (
    <section ref={section} className="st-ground-section" style={{ height: `${Math.round(total * 57)}vh` }} aria-label={c.label}>
      <div className="st-stage st-sticky">
        <div ref={ground} className="st-ground">
          {descent?.levels.map((level, i) => (
            <div key={level.level} ref={(n) => { rings.current[i] = n; }} className={`st-ring${i ? " st-ring-inset" : ""}`}>
              <img src={level.url} alt="" draggable={false} />
            </div>
          ))}
          <div ref={(n) => { rings.current[4] = n; }} className="st-ring">{box && <div data-g="outline" className="st-outline" style={box} />}</div>
          <canvas ref={dots} className="st-dots" width={1600} height={1600} />
          <div data-g="dim" className="st-dim" />
        </div>
        <div data-g="city" className="st-city">
          <p className="st-kicker">{c.city}</p>
          {count != null && <p className="st-figure"><strong>{count.toLocaleString("en-US")}</strong> {c.counted}</p>}
          {city && <p className="st-money">{city.homes.toLocaleString("en-US")} homes. {sum(city.sold)} is what {city.of.toLocaleString("en-US")} of these buildings last sold for.<small>CoStar sale records. Not today's value, and not a loss estimate.</small></p>}
        </div>
        <div data-g="place" className="st-place">
          <h2>{homes?.name}</h2>
          <p>{[homes?.units ? `${homes.units.toLocaleString("en-US")} homes` : null, homes?.built ? `built ${homes.built}` : null].filter(Boolean).join(", ")}</p>
          {homes?.sold && <p className="st-place-rent">{homes.sold}<small>{homes.soldHow}</small></p>}
          {homes?.rent && <p className="st-place-rent">{homes.rent}<small>CoStar apartment listing</small></p>}
          {!!homes?.why.length && <ul className="st-why">{homes.why.map((w) => <li key={w}>{w}</li>)}</ul>}
        </div>
        {hours != null && (
          <div data-g="clock" className="st-clock">
            <strong>{Math.round(hours)}</strong>
            <span>{c.clock}</span>
            {homes?.work && <em>{homes.work}</em>}
          </div>
        )}
        <div data-g="backdrop" className="st-backdrop" />
        <div ref={pano} className="st-pano" />
        <p data-g="inside" className="st-inside">Inside one of its homes.<small>Matterport scan</small></p>
        <iframe ref={frame} className="st-site" title={`${homes?.name ?? "The building"} in three dimensions`} src={`/${at(c.scenario, c.step, c.building)}`} data-shot="site" tabIndex={-1} onLoad={() => setSiteLoaded(true)} />
        <div ref={scrub} className="st-scrub" role="group" aria-label="The moment shown" hidden={stops.length < 2}>
          <div className="st-scrub-track" onPointerDown={drag}><i ref={handle} /></div>
          {stops.map((stop, i) => <button key={stop.label} type="button" style={{ left: `${(i / Math.max(1, stops.length - 1)) * 100}%` }} onClick={() => goTo(i)}>{stop.label}</button>)}
        </div>
        <p className="st-credit">Aerial photographs: Vexcel</p>
      </div>
    </section>
  );
}
