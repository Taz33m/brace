import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./show.css";

/**
 * The show: scenario after scenario, each playing by itself while the presenters speak.
 *
 * A shot is either a rendered clip or a page of the product running live inside a frame. A page shot is
 * told in beats: the first plays when the shot comes up, and each press of the key plays the next one, so
 * the person speaking sets the pace and never has to click around. Two moments are done by hand: a
 * resident's phone, and the headset. Everything else is one key.
 *
 *   Right arrow, Space, Page Down   the next beat, or the next shot
 *   Left arrow, Page Up             the shot before
 *   Enter                           the one thing a shot asks a person to decide (approving a notice)
 *   R                               play this shot again        F   fill the screen
 */
type Cue =
  | { at: number; key: string }                    // a key the page already answers to
  | { at: number; hash: string }                   // another address in the same page
  | { at: number; click: string; text?: RegExp };  // press something on the page (the first match whose words fit)
interface Beat { caption?: string; cues?: Cue[]; decide?: boolean; needs?: "furniture" }
interface Shot {
  id: string;
  scenario: string;
  film?: string;        // a rendered clip, played when it has been made
  page?: string;        // the live page, played when there is no clip (or always, when there is no film)
  beats?: Beat[];
  onward?: boolean;     // a clip that runs straight into the next shot
  hands?: boolean;      // a moment done by hand: the page takes the pointer
  card?: "title" | "end";
}

const PARKER = "beryl-2024/adv33/b/4303509";
const SHOTS: Shot[] = [
  { id: "title", scenario: "Brace", card: "title" },
  { id: "hook", scenario: "A storm is coming", film: "01_hook", onward: true },
  { id: "descent", scenario: "A storm is coming", film: "02_descent" },
  { id: "city", scenario: "Every building in its path", page: "#/beryl-2024/adv27", beats: [
    { caption: "Each forecast, read for every building in its path.", cues: [{ at: 1600, hash: "#/beryl-2024/adv29" }, { at: 3000, hash: "#/beryl-2024/adv31" }, { at: 4400, hash: "#/beryl-2024/adv33" }] },
  ] },
  { id: "stand", scenario: "One building, measured", film: "03_stand", onward: true },
  { id: "snap", scenario: "One building, measured", film: "04_snap", onward: true },
  { id: "pine", scenario: "One building, measured", film: "05_pine" },
  { id: "clock", scenario: "The clock writes the plan", film: "06_clock" },
  { id: "site", scenario: "One building, measured", page: `#/scene/${PARKER}`, hands: true, beats: [
    { caption: "One of them: The Parker at Ellington." },
    { caption: "The scan's own GPS puts this home off its roof. Brace moves it back.", cues: [{ at: 0, key: "2" }] },
    { caption: "One pine, 17.9 metres tall, 1.5 metres from a wall.", cues: [{ at: 0, key: "1" }, { at: 1700, click: ".scene-jobs button", text: /evergreen|pine/i }] },
    { caption: "The plan asks residents to clear their balconies.", cues: [{ at: 0, click: ".scene-jobs button", text: /resident/i }] },
    { decide: true, cues: [{ at: 0, click: ".scene-approve" }] },
    { caption: "Twelve hours out, the same building gets a different plan.", cues: [{ at: 0, hash: "#/scene/beryl-2024/adv37/b/4303509" }, { at: 900, key: "1" }] },
  ] },
  { id: "room", scenario: "After the storm", page: "#/furnish/4303509/39JTmBzqWxr", beats: [
    {},
    { cues: [{ at: 0, key: "2" }] },
    { needs: "furniture", cues: [{ at: 0, key: "3" }] },
  ] },
  { id: "inside", scenario: "Inside any building", page: "#/place/P3S6VUTP3qB/watch", hands: true },
  { id: "end", scenario: "Brace", card: "end" },
];

const FADE_MS = 700;

export function ShowPage({ start = 0 }: { start?: number }) {
  const [clips, setClips] = useState<Set<string> | null>(null);
  const [at, setAt] = useState(start);
  const [beat, setBeat] = useState(0);
  const [leaving, setLeaving] = useState<number | null>(null);
  const [again, setAgain] = useState(0);
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});
  const frames = useRef(new Map<string, HTMLIFrameElement>());
  const films = useRef(new Map<string, HTMLVideoElement>());

  // The room is furnished again only once its furniture has been made; until then that beat is left out.
  const [furniture, setFurniture] = useState(false);
  useEffect(() => {
    fetch("/api/buildings/4303509/furnish/39JTmBzqWxr").then((r) => r.json()).then((d: { models_made?: number; contents?: number }) => setFurniture(!!d.contents && (d.models_made ?? 0) >= d.contents)).catch(() => {});
  }, []);
  useEffect(() => {
    fetch("/api/film").then((r) => r.json()).then((d: { clips: string[] }) => setClips(new Set(d.clips))).catch(() => setClips(new Set()));
  }, []);

  // A shot with a clip plays the clip; one without plays its page; one with neither is left out.
  const shots = useMemo(() => SHOTS.filter((s) => s.card || s.page || (s.film && clips?.has(s.film)))
    .map((s) => ({ ...s, film: s.film && clips?.has(s.film) ? s.film : undefined, beats: s.beats?.filter((b) => b.needs !== "furniture" || furniture) })), [clips, furniture]);
  const shot = shots[Math.min(at, shots.length - 1)];
  const beats = shot?.beats ?? [];

  const go = useCallback((to: number) => {
    setAt((now) => {
      const next = Math.max(0, Math.min(shots.length - 1, to));
      if (next !== now) { setLeaving(now); setBeat(0); window.setTimeout(() => setLeaving((l) => (l === now ? null : l)), FADE_MS + 50); }
      return next;
    });
  }, [shots.length]);

  // What a beat does to the page it plays on.
  const play = useCallback((s: Shot, b: Beat) => {
    const frame = frames.current.get(s.id), win = frame?.contentWindow, timers: number[] = [];
    if (!win) return () => {};
    for (const cue of b.cues ?? []) {
      timers.push(window.setTimeout(() => {
        try {
          if ("key" in cue) win.dispatchEvent(new KeyboardEvent("keydown", { key: cue.key, bubbles: true }));
          else if ("hash" in cue) win.location.hash = cue.hash;
          else {
            const found = [...win.document.querySelectorAll<HTMLElement>(cue.click)].find((el) => !cue.text || cue.text.test(el.textContent ?? ""));
            found?.click();
          }
        } catch { /* the page went away mid-beat: nothing to do */ }
      }, cue.at));
    }
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, []);

  // The current beat plays once the shot is up and its page has loaded.
  const ready = shot && (!shot.page || shot.film || loaded[shot.id]);
  useEffect(() => {
    if (!shot || !ready || shot.film || !shot.page) return;
    const b = beats[beat];
    if (!b || b.decide) return;      // a decision waits for Enter
    return play(shot, b);
  }, [shot?.id, beat, ready, again]);   // eslint-disable-line react-hooks/exhaustive-deps

  // A clip starts from its first frame each time its shot comes up, and holds on its last.
  useEffect(() => {
    for (const [id, v] of films.current) {
      if (id === shot?.id) { v.currentTime = 0; void v.play().catch(() => {}); } else v.pause();
    }
  }, [shot?.id, again, clips]);

  const next = useCallback(() => {
    // A decision is skipped by the arrow: only Enter takes it.
    let b = beat + 1;
    while (b < beats.length && beats[b].decide) b += 1;
    if (b < beats.length) setBeat(b); else go(at + 1);
  }, [beat, beats, at, go]);

  const decide = useCallback(() => {
    const i = beats.findIndex((b, n) => n > beat - 1 && b.decide);
    if (shot && i >= 0 && i <= beat + 1) { play(shot, beats[i]); setBeat(i); }
  }, [beats, beat, shot, play]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(at - 1); }
      else if (e.key === "Enter") { e.preventDefault(); decide(); }
      else if (e.key === "r" || e.key === "R") { setBeat(0); setAgain((n) => n + 1); }
      else if (e.key === "f" || e.key === "F") { void document.documentElement.requestFullscreen?.().catch(() => {}); }
      else if (e.key === "Home") go(0);
    };
    // The same keys work when a page inside the show has taken the keyboard.
    const windows: Window[] = [window];
    for (const f of frames.current.values()) { try { if (f.contentWindow) windows.push(f.contentWindow); } catch { /* not ours */ } }
    windows.forEach((w) => w.addEventListener("keydown", key));
    return () => windows.forEach((w) => { try { w.removeEventListener("keydown", key); } catch { /* gone */ } });
  }, [next, go, decide, at, loaded]);

  // The address remembers the shot, so a reload comes back to it.
  useEffect(() => { window.history.replaceState(window.history.state, "", `#/show/${at + 1}`); }, [at]);

  if (!clips || !shot) return <div className="reel-wait" />;
  // Up now, the one fading out, and the next one loading out of sight so the cut to it is instant.
  const mounted = new Set([at, at + 1, ...(leaving == null ? [] : [leaving])]);
  const caption = shot.film ? null : beats[beat]?.caption ?? [...beats.slice(0, beat)].reverse().find((b) => b.caption)?.caption ?? null;
  const first = shots.map((s, i) => i === 0 || shots[i - 1].scenario !== s.scenario);

  return (
    <div className={`reel${shot.hands ? " is-hands" : ""}`}>
      {shots.map((s, i) => mounted.has(i) && (
        <div key={`${s.id}:${i === at ? again : 0}`} className={`reel-shot${i === at ? " is-on" : ""}`} aria-hidden={i !== at}>
          {s.card === "title" && <div className="reel-card"><img src="/logo.png" width={84} height={84} alt="" /><h1>Brace</h1><p>Before the storm, for every building in its path.</p></div>}
          {s.card === "end" && <div className="reel-card"><img src="/logo.png" width={84} height={84} alt="" /><h1>Brace</h1><p>The forecast, turned into work.</p></div>}
          {s.film && <video ref={(n) => { if (n) films.current.set(s.id, n); else films.current.delete(s.id); }} src={`/api/film/${s.film}.mp4`} muted playsInline preload="auto"
                            onEnded={() => { if (s.onward && i === at) go(at + 1); }} />}
          {!s.film && s.page && <iframe ref={(n) => { if (n) frames.current.set(s.id, n); else frames.current.delete(s.id); }} title={s.scenario} src={`/${s.page}`} data-shot={s.id}
                                         allow="fullscreen" onLoad={() => setLoaded((l) => ({ ...l, [s.id]: true }))} />}
        </div>
      ))}
      {caption && <p className="reel-caption" key={`${shot.id}:${caption}`}>{caption}</p>}
      <ol className="reel-rail" aria-label="Scenarios">
        {shots.map((s, i) => <li key={s.id} className={`${i === at ? "is-on" : i < at ? "is-done" : ""}${first[i] ? " is-first" : ""}`} />)}
      </ol>
    </div>
  );
}
