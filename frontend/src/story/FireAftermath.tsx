import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import "./fire-aftermath.css";

type View = "before" | "cleared" | "fire";
const LABELS: Record<View, string> = { before: "Before", cleared: "Furniture removed", fire: "After the fire" };

/** A generated scenario at the same home and standpoint as the kitchen walkthrough. Never assessment evidence. */
export function FireAftermath() {
  const mount = useRef<HTMLDivElement>(null);
  const choose = useRef<(view: View) => void>(() => {});
  const [view, setView] = useState<View>("fire");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const el = mount.current;
    if (!el) return;
    let disposed = false, raf = 0;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
    catch { setError("The room could not open. Please enable WebGL and reload."); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(76, 1, 0.1, 100);
    camera.rotation.order = "YXZ";
    const geometry = new THREE.SphereGeometry(30, 64, 40);
    geometry.scale(-1, 1, 1);
    const material = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const sphere = new THREE.Mesh(geometry, material);
    scene.add(sphere);
    const textures = new Map<View, THREE.Texture>();
    const loader = new THREE.TextureLoader();
    let selected: View = "fire", yaw = Math.PI, pitch = 0;
    const draw = () => {
      camera.rotation.set(pitch, yaw, 0);
      renderer.render(scene, camera);
    };
    choose.current = next => {
      selected = next;
      const texture = textures.get(next);
      if (texture) { setReady(true); material.map = texture; material.needsUpdate = true; setError(""); draw(); }
      else { material.map = null; material.needsUpdate = true; setReady(false); draw(); setError("This view is unavailable. Choose another view or reload."); }
    };
    for (const name of Object.keys(LABELS) as View[]) {
      loader.load(`/aftermath/verdugo/${name}.${name === "fire" ? "png" : "jpg"}`, texture => {
        if (disposed) { texture.dispose(); return; }
        texture.colorSpace = THREE.SRGBColorSpace;
        textures.set(name, texture);
        if (selected === name) { material.map = texture; material.needsUpdate = true; setReady(true); setError(""); draw(); }
      }, undefined, () => { if (!disposed && selected === name) setError("This view could not load. Choose another view or reload."); });
    }
    const size = () => {
      renderer.setSize(el.clientWidth, el.clientHeight, false);
      camera.aspect = el.clientWidth / Math.max(1, el.clientHeight);
      camera.updateProjectionMatrix(); draw();
    };
    const resize = new ResizeObserver(size); resize.observe(el); size();
    let dragging = false, x = 0, y = 0;
    const down = (e: PointerEvent) => { dragging = true; x = e.clientX; y = e.clientY; el.setPointerCapture(e.pointerId); };
    const move = (e: PointerEvent) => { if (!dragging) return; yaw += (e.clientX - x) * 0.004; pitch = Math.max(-1.2, Math.min(1.2, pitch + (e.clientY - y) * 0.004)); x = e.clientX; y = e.clientY; draw(); };
    const up = () => { dragging = false; };
    const key = (e: KeyboardEvent) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "Home") { yaw = Math.PI; pitch = 0; }
      if (e.key === "ArrowLeft") yaw += 0.1;
      if (e.key === "ArrowRight") yaw -= 0.1;
      if (e.key === "ArrowUp") pitch = Math.min(1.2, pitch + 0.1);
      if (e.key === "ArrowDown") pitch = Math.max(-1.2, pitch - 0.1);
      draw();
    };
    el.addEventListener("pointerdown", down); el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up); el.addEventListener("keydown", key);
    // Observe only to redraw after the section returns to the viewport; no permanent animation loop.
    const observer = new IntersectionObserver(entries => { if (entries[0].isIntersecting) raf = requestAnimationFrame(draw); }); observer.observe(el);
    return () => { disposed = true; choose.current = () => {}; cancelAnimationFrame(raf); observer.disconnect(); resize.disconnect(); el.removeEventListener("pointerdown", down); el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up); el.removeEventListener("keydown", key); textures.forEach(t => t.dispose()); geometry.dispose(); material.dispose(); renderer.dispose(); renderer.domElement.remove(); };
  }, []);
  return <section className="fire-aftermath" id="home-after-fire" aria-label="The same home after a hypothetical fire">
    <div ref={mount} className="fire-aftermath-room" tabIndex={0} role="region" aria-label={`${LABELS[view]} panorama. Drag or use arrow keys to look around. Home resets the view.`} />
    <header><span>VERDUGO MESA · THE SAME HOME</span><h2>{LABELS[view]}</h2></header>
    {(!ready || error) && <p className="fire-aftermath-status" role="status">{error || "Opening the home…"}</p>}
    <footer>
      <nav aria-label="Compare the home">{(Object.keys(LABELS) as View[]).map(v => <button key={v} aria-pressed={view === v} onClick={() => { setView(v); choose.current(v); }}>{LABELS[v]}</button>)}</nav>
      <p>{view === "fire" ? "AI-generated fire scenario · Furniture removed after the fire · Not observed damage" : view === "cleared" ? "Digitally cleared view · Matterport" : "Original home · Matterport"}</p>
      <small>Drag to look around</small>
    </footer>
  </section>;
}
