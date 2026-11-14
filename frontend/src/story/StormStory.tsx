import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import { CabinWindow, Sky, SplitChars } from "./Cabin";
import { gsap, prefersReducedMotion } from "./gsap";

/**
 * Before the storm, told by scrolling. Through the cabin window, down through cloud onto Houston, down
 * onto one building, the hours it has, inside one of its homes, and then the live product: the site in
 * three dimensions with the plan on it. Nothing here advances by itself; the scroll is the film's clock,
 * and it runs backwards as well as forwards.
 */
const PARKER = 4303509, SCENARIO = "beryl-2024", STEP = "adv33", LATER = "adv37", SCAN = "39JTmBzqWxr";
const RING = [1, 0.256, 0.064, 0.016];            // each aerial covers this share of the widest one's width, all on one centre
const rad = (deg: number) => (deg * Math.PI) / 180;
const clamp = (v: number) => Math.max(0, Math.min(1, v));

interface Descent { levels: { level: number; bounds: [number, number, number, number]; url: string }[]; site: { bounds: [number, number, number, number]; captured?: string } }
type Cue = { hash?: string; key?: string; click?: string; text?: RegExp; wait?: number };

// What the live site shows at each stretch of the scroll. Each state says everything it needs, so it reads the same scrolling up as down.
const SITE_AT: { from: number; cues: Cue[] }[] = [
  { from: 0, cues: [{ hash: `#/scene/${SCENARIO}/${STEP}/b/${PARKER}` }, { key: "1" }] },
  { from: 18.2, cues: [{ hash: `#/scene/${SCENARIO}/${STEP}/b/${PARKER}` }, { key: "2" }] },
  { from: 21.2, cues: [{ hash: `#/scene/${SCENARIO}/${STEP}/b/${PARKER}` }, { key: "1" }, { click: ".scene-jobs button", text: /evergreen|pine/i, wait: 1500 }] },
  { from: 24.2, cues: [{ hash: `#/scene/${SCENARIO}/${LATER}/b/${PARKER}` }, { key: "1", wait: 900 }] },
  { from: 27.2, cues: [{ hash: `#/scene/${SCENARIO}/${LATER}/b/${PARKER}` }, { click: ".scene-jobs button", text: /resident/i, wait: 400 }] },
];

export function StormStory() {
  return (
    <>
      <Sky />
      <Hero />
      <CloudRise />
      <Ground />
      <section className="st-end">
        <h2>Brace</h2>
        <a href="#/">All scenarios</a>
      </section>
    </>
  );
}

/** The fly-through, as in the plane project: pinned for two and a half screens of scroll, fully reversible. */
function Hero() {
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
    <section ref={section} className="st-hero" aria-label="A storm is coming">
      <div ref={stage} className="st-stage">
        <CabinWindow zoom={zoom} onReady={onReady} />
        <div className="st-safe">
          <div ref={copy} className="st-fill st-will">
            <h1 data-hero-lead className="st-lead">
              <span className="st-sr">A storm is coming</span>
              <SplitChars text="A storm" className="st-line" /><SplitChars text="is coming" className="st-line st-indent" />
            </h1>
            <p data-hero-counter className="st-counter">
              <span className="st-sr">Thirty-nine hours out</span>
              <SplitChars text="Thirty-nine" className="st-line st-outdent" /><SplitChars text="hours out" className="st-line" />
            </p>
            <div ref={aside} className="st-aside">
              <p className="st-aside-title">Hurricane Beryl,<br />July 2024</p>
              <span className="st-rule" />
              <p className="st-aside-text">A replay of the real forecasts, in the order the National Hurricane Center issued them.</p>
            </div>
          </div>
          <div ref={cue} className="st-cue">
            <div ref={cueInner}>
              <span className="st-cue-line" />
              <p><span>Scroll to descend</span><span>Houston, Texas</span></p>
            </div>
          </div>
          <div ref={statement} className="st-statement">
            <div className="st-statement-shade" />
            <p><span className="st-brand">BRACE</span> reads each forecast against every building in its path, and turns it into the work that still fits before the wind arrives.</p>
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
 *   0 to 10   the cloud clears over Houston with every building in the wind field lit, and the view falls onto one of them
 *   8 to 10   the hours that building has
 *  10 to 14   inside one of its homes, as Matterport scanned it
 *  14 to 30   the live site in three dimensions, stepping through the plan as the scroll goes on
 */
function Ground() {
  const section = useRef<HTMLElement>(null);
  const [descent, setDescent] = useState<Descent | null>(null);
  const [hours, setHours] = useState<number | null>(null);
  const [homes, setHomes] = useState<{ name: string; units: number | null; built: number | null; rent: string | null } | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [room, setRoom] = useState<{ sweep: string; heading: number; yaw: number } | null>(null);
  const [siteLoaded, setSiteLoaded] = useState(false);
  const rings = useRef<(HTMLDivElement | null)[]>([]);
  const dots = useRef<HTMLCanvasElement>(null), ground = useRef<HTMLDivElement>(null);
  const pano = useRef<HTMLDivElement>(null), frame = useRef<HTMLIFrameElement>(null);
  const live = useRef({ z: 0, pan: 0, inside: 0, site: -1, loaded: false, timers: [] as number[] });
  live.current.loaded = siteLoaded;

  useEffect(() => {
    let current = true;
    fetch(`/api/buildings/${PARKER}/descent`).then((r) => (r.ok ? r.json() : null)).then((d) => { if (current && d) setDescent(d); }).catch(() => {});
    api.building(PARKER, SCENARIO, STEP).then((b) => {
      if (!current) return;
      setHours(b.threat.hours_left ?? null);
      const record = b.record as { name?: string; units?: number; year_built?: number };
      const dollars = (n: number) => `$${n.toLocaleString("en-US")}`;
      setHomes({ name: record.name ?? "", units: record.units ?? null, built: record.year_built ?? null,
                 rent: b.rent ? `Homes advertised at ${dollars(b.rent.low)} to ${dollars(b.rent.high)} a month` : null });
    }).catch(() => {});
    api.furnish(PARKER, SCAN).then((r) => { if (current) setRoom({ sweep: r.sweep_id, heading: r.standpoint.h, yaw: r.view.yaw_deg }); }).catch(() => {});
    return () => { current = false; };
  }, []);

  // Every building in the forecast wind field that falls inside the widest photograph, as a point of light on it.
  useEffect(() => {
    const canvas = dots.current, wide = descent?.levels[0]?.bounds;
    if (!canvas || !wide) return;
    let current = true;
    api.portfolio(SCENARIO, STEP, "", "").then((p) => {
      if (!current) return;
      setCount(p.shown);
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
  }, [descent]);

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
    now.timers = SITE_AT[state].cues.map((cue) => window.setTimeout(() => {
      try {
        if (cue.hash && win.location.hash !== cue.hash) win.location.hash = cue.hash;
        if (cue.key) win.dispatchEvent(new KeyboardEvent("keydown", { key: cue.key, bubbles: true }));
        if (cue.click) [...win.document.querySelectorAll<HTMLElement>(cue.click)].find((el) => !cue.text || cue.text.test(el.textContent ?? ""))?.click();
      } catch { /* the page went away mid-step */ }
    }, cue.wait ?? 0));
  }, []);

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
          let at = 0;
          SITE_AT.forEach((s, i) => { if (t >= s.from) at = i; });
          if (t >= 13.6) siteTo(at);
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
        .fromTo(q("backdrop"), { autoAlpha: 0 }, { autoAlpha: 1, duration: 1 }, 10.1)
        .fromTo(q("clock"), { autoAlpha: 0, scale: 0.92, filter: "blur(10px)" }, { autoAlpha: 1, scale: 1, filter: "blur(0px)", ease: "power3.out", duration: 1.1 }, 8)
        .to([q("clock"), q("place")], { autoAlpha: 0, duration: 0.6 }, 10)
        .fromTo(pano.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 1 }, 10.1)
        .fromTo(state, { pan: -30, inside: 0 }, { pan: 30, inside: 1, duration: 4.2 }, 10)
        .fromTo(q("inside"), { autoAlpha: 0, y: 24, filter: "blur(8px)" }, { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 0.8 }, 11)
        .to(q("inside"), { autoAlpha: 0, duration: 0.6 }, 13.2)
        .to(pano.current, { autoAlpha: 0, duration: 0.7 }, 13.5)
        .fromTo(frame.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.9 }, 14.1)
        .to({}, { duration: 15 }, 15);
    }, el);
    return () => ctx.revert();
  }, [descent, zoomTo, siteTo]);

  // The scanned room, as a panorama the scroll turns.
  useEffect(() => {
    const el = pano.current;
    if (!el || !room) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(74, el.clientWidth / el.clientHeight, 0.05, 300);
    camera.rotation.order = "YXZ";
    const loader = new THREE.TextureLoader(), FACE = 40, size = FACE * 2.002, group = new THREE.Group();
    const plane = (face: number) => {
      const tex = loader.load(`/api/buildings/${PARKER}/pano/${SCAN}/${room.sweep}/${face}.jpg?size=2048`);
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
  }, [room]);

  // Enter approves the notice when it is the thing on screen. It sends a real message, so nothing else does it.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || live.current.site !== SITE_AT.length - 1) return;
      try { frame.current?.contentWindow?.document.querySelector<HTMLElement>(".scene-approve")?.click(); } catch { /* not there */ }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const site = descent?.site.bounds, last = descent?.levels[3]?.bounds;
  const box = site && last ? {
    left: `${((site[0] - last[0]) / (last[2] - last[0])) * 100}%`, width: `${((site[2] - site[0]) / (last[2] - last[0])) * 100}%`,
    top: `${((last[3] - site[3]) / (last[3] - last[1])) * 100}%`, height: `${((site[3] - site[1]) / (last[3] - last[1])) * 100}%`,
  } : null;

  return (
    <section ref={section} className="st-ground-section" aria-label="Houston, then one building">
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
          <p className="st-kicker">Houston, Texas</p>
          {count != null && <p className="st-figure"><strong>{count.toLocaleString("en-US")}</strong> buildings in the forecast wind field</p>}
        </div>
        <div data-g="place" className="st-place">
          <h2>{homes?.name}</h2>
          <p>{[homes?.units ? `${homes.units} homes` : null, homes?.built ? `built ${homes.built}` : null].filter(Boolean).join(", ")}</p>
          {homes?.rent && <p className="st-place-rent">{homes.rent}<small>CoStar apartment listing</small></p>}
        </div>
        {hours != null && (
          <div data-g="clock" className="st-clock">
            <strong>{Math.round(hours)}</strong>
            <span>hours until the wind arrives</span>
          </div>
        )}
        <div data-g="backdrop" className="st-backdrop" />
        <div ref={pano} className="st-pano" />
        <p data-g="inside" className="st-inside">Inside one of its homes.<small>Matterport scan</small></p>
        <iframe ref={frame} className="st-site" title="The Parker at Ellington in three dimensions" src={`/#/scene/${SCENARIO}/${STEP}/b/${PARKER}`} data-shot="site" tabIndex={-1} onLoad={() => setSiteLoaded(true)} />
        <p className="st-credit">Aerial photographs: Vexcel</p>
      </div>
    </section>
  );
}
