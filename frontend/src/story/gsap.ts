import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

// Copied from the plane project: plugins register once, and every animation is made inside an effect.
gsap.registerPlugin(ScrollTrigger);

export const prefersReducedMotion = (): boolean => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
export { gsap, ScrollTrigger };
