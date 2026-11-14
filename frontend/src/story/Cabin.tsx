import { Fragment, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { gsap, prefersReducedMotion } from "./gsap";
import { drawKeyedWindow } from "./key-window";

/**
 * The cabin, copied from the plane project: a fixed sky behind everything, and the window artwork with
 * its glass cut out so the live sky shows through. The scenes above drive the sky's layers by their
 * data-sky names, exactly as they do there.
 */
export function Sky({ whisper = "Every building in its path." }: { whisper?: string }) {
  return (
    <div className="st-sky" data-sky-root aria-hidden="true">
      <div data-sky="zoom" className="st-fill st-will">
        <div data-sky="parallax" className="st-sky-photo"><img src="/show/sky.jpg" alt="" /></div>
      </div>
      <div data-sky="drift" className="st-sky-drift">
        <div className="st-sky-drift-track">
          {[false, true, false, true].map((mirrored, i) => (
            <div key={i} className="st-sky-drift-tile"><img src="/show/wisps.jpg" alt="" style={mirrored ? { transform: "scaleX(-1)" } : undefined} /></div>
          ))}
        </div>
      </div>
      <div data-sky="sweep" className="st-sky-sweep"><img src="/show/wisps.jpg" alt="" /></div>
      <div data-sky="scrim" className="st-sky-scrim" />
      <div data-sky="bank" className="st-sky-bank"><img src="/show/bank.jpg" alt="" /></div>
      <div data-sky="veil" className="st-sky-veil" />
      <p data-sky="whisper" className="st-sky-whisper">{whisper}</p>
    </div>
  );
}

/** The window frame. `zoom` is the box the fly-through scales; the tilt under the cursor is built in. */
export function CabinWindow({ zoom, onReady }: { zoom?: RefObject<HTMLDivElement>; onReady?: () => void }) {
  const [fallback, setFallback] = useState(false);
  const tilt = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  // Cut the glass out of the window artwork so the live sky shows through it.
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    let cancelled = false;
    drawKeyedWindow("/show/window.jpg", el, window.innerWidth < 768 ? 2048 : 2752)
      .catch(() => { if (!cancelled) setFallback(true); })
      .finally(() => { if (!cancelled) onReady?.(); });
    return () => { cancelled = true; };
  }, [onReady]);

  // The window and the sky drift gently against each other under the cursor.
  useEffect(() => {
    const el = tilt.current;
    const parallax = document.querySelector<HTMLElement>('[data-sky="parallax"]');
    if (!el || prefersReducedMotion() || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    gsap.set(el, { transformPerspective: 1400 });
    const rotateY = gsap.quickTo(el, "rotationY", { duration: 1.4, ease: "power3.out" });
    const rotateX = gsap.quickTo(el, "rotationX", { duration: 1.4, ease: "power3.out" });
    const shiftX = gsap.quickTo(el, "x", { duration: 1.4, ease: "power3.out" });
    const shiftY = gsap.quickTo(el, "y", { duration: 1.4, ease: "power3.out" });
    const skyX = parallax ? gsap.quickTo(parallax, "x", { duration: 2, ease: "power3.out" }) : null;
    const skyY = parallax ? gsap.quickTo(parallax, "y", { duration: 2, ease: "power3.out" }) : null;
    const move = (e: PointerEvent) => {
      if (window.scrollY > window.innerHeight * 2.6) return;
      const x = e.clientX / window.innerWidth - 0.5, y = e.clientY / window.innerHeight - 0.5;
      rotateY(x * 3.2); rotateX(-y * 2.4); shiftX(x * 14); shiftY(y * 10);
      skyX?.(-x * 26); skyY?.(-y * 18);
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => { window.removeEventListener("pointermove", move); gsap.killTweensOf(el); if (parallax) gsap.killTweensOf(parallax); };
  }, []);

  return (
    <div ref={zoom} className="st-window-box st-will">
      <div ref={tilt} className="st-fill">
        <div className="st-band st-band-top" /><div className="st-band st-band-bottom" /><div className="st-band st-band-left" /><div className="st-band st-band-right" />
        <canvas ref={canvas} aria-hidden="true" className="st-window-art" />
        {fallback && <img src="/show/window.jpg" alt="" className="st-window-art" />}
      </div>
    </div>
  );
}

/** A line split into letters for the blur reveal. Words never break mid-word. */
export function SplitChars({ text, className }: { text: string; className?: string }) {
  const words = text.split(" ");
  return (
    <span aria-hidden="true" className={className}>
      {words.map((word, w) => (
        <Fragment key={`${word}-${w}`}>
          <span className="st-word">{Array.from(word).map((c, i) => <span key={i} data-char className="st-char">{c}</span>)}</span>
          {w < words.length - 1 && " "}
        </Fragment>
      ))}
    </span>
  );
}
