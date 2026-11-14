import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import type Lenis from "lenis";

// Copied from the plane project: plugins register once, and every animation is made inside an effect.
gsap.registerPlugin(ScrollTrigger);

export const prefersReducedMotion = (): boolean => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
/** The page's smooth scroller, when there is one, so a control on the page can take the scroll somewhere. */
export const smooth: { lenis: Lenis | null } = { lenis: null };
export function scrollToY(y: number): void {
  if (smooth.lenis) smooth.lenis.scrollTo(y, { duration: 1.6 });
  else window.scrollTo({ top: y, behavior: prefersReducedMotion() ? "auto" : "smooth" });
}
export { gsap, ScrollTrigger };
