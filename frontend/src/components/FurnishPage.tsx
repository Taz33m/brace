import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { api } from "../api";
import type { FurnishScene } from "../types";
import "./furnish.css";

/**
 * One room, three states, from one standpoint: as it was, cleared, and furnished again.
 * The first two are the scan and Matterport's defurnished view of it. The third puts a generated
 * model where each piece of furniture stood. Keys 1, 2 and 3, or the three marks at the bottom.
 */
type State = "as_it_was" | "cleared" | "furnished";
const ORDER: State[] = ["as_it_was", "cleared", "furnished"];
const FACE_M = 40;
const rad = (deg: number) => (deg * Math.PI) / 180;

export function FurnishPage({ id, scan }: { id: number; scan: string }) {
  const [room, setRoom] = useState<FurnishScene | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<State>("as_it_was");
  const [note, setNote] = useState<string | null>(null);
  const mount = useRef<HTMLDivElement>(null);
  const live = useRef({ state });
  live.current.state = state;
  const made = room?.models_made ?? 0;

  useEffect(() => {
    let current = true;
    const read = () => api.furnish(id, scan).then((r) => { if (current) { setRoom(r); setError(null); } }).catch((e) => { if (current) setError(e.message); });
    read();
    const t = window.setInterval(read, 8000);     // models arrive one at a time while they are being made
    return () => { current = false; window.clearInterval(t); };
  }, [id, scan]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => { const n = Number(e.key); if (n >= 1 && n <= 3) setState(ORDER[n - 1]); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const sweep = room?.sweep_id, heading = room?.standpoint.h, eye = room?.standpoint.z, yaw = room?.view.yaw_deg;
  const placed = JSON.stringify((room?.pieces ?? []).map((p) => [p.name, p.model, p.east_m, p.north_m]));
  useEffect(() => {
    const el = mount.current;
    if (!el || !room || sweep == null || heading == null || eye == null) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(78, el.clientWidth / el.clientHeight, 0.05, 300);
    camera.rotation.order = "YXZ";
    // Start facing the furniture: the same aim the room was read from.
    let look = heading + (yaw ?? 0), tilt = -10;
    camera.rotation.set(rad(tilt), -rad(look), 0);
    const loader = new THREE.TextureLoader();
    const cube = (url: (face: number) => string) => {
      const group = new THREE.Group(), size = FACE_M * 2.002, mats: THREE.MeshBasicMaterial[] = [];
      const plane = (face: number) => {
        const tex = loader.load(url(face));
        tex.colorSpace = THREE.SRGBColorSpace;
        const mat = new THREE.MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false, transparent: true });
        mats.push(mat);
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), mat);
        mesh.renderOrder = 0;
        return mesh;
      };
      // Sides: face 1 looks along the position's heading; 2, 3 and 4 each turn a further 90 degrees clockwise.
      for (let k = 0; k < 4; k++) { const pivot = new THREE.Group(), m = plane(k + 1); m.position.z = -FACE_M; pivot.add(m); pivot.rotation.y = -rad(heading + 90 * k); group.add(pivot); }
      const caps = new THREE.Group(), up = plane(0), down = plane(5);
      up.position.y = FACE_M; up.rotation.x = Math.PI / 2; down.position.y = -FACE_M; down.rotation.x = -Math.PI / 2;
      caps.add(up, down); caps.rotation.y = -rad(heading); group.add(caps);
      return { group, mats };
    };
    const was = cube((f) => `/api/buildings/${id}/pano/${scan}/${sweep}/${f}.jpg?size=2048`);
    const cleared = cube((f) => `/api/buildings/${id}/furnish/${scan}/cleared/${sweep}/${f}.jpg?size=2048`);
    cleared.group.renderOrder = 1;
    for (const m of cleared.mats) m.opacity = 0;
    scene.add(was.group, cleared.group);

    // The new furniture: real geometry standing in the room, so it holds still as you look around.
    const things = new THREE.Group();
    scene.add(things, new THREE.HemisphereLight(0xffffff, 0x8a7f72, 1.6));
    const sun = new THREE.DirectionalLight(0xfff4e2, 1.4);
    sun.position.set(2, 4, 1);
    scene.add(sun);
    const gltf = new GLTFLoader();
    for (const p of room.pieces) {
      const at = new THREE.Vector3(p.east_m - room.standpoint.e, -eye + p.stands_on_m, -(p.north_m - room.standpoint.n));
      if (!p.model) {
        // No model yet: the space the piece takes, drawn as a quiet block.
        const block = new THREE.Mesh(new THREE.BoxGeometry(p.width_m, p.height_m, p.depth_m), new THREE.MeshStandardMaterial({ color: 0xe9e4da, transparent: true, opacity: 0.55, roughness: 1 }));
        block.position.copy(at).setY(at.y + p.height_m / 2); block.rotation.y = Math.PI - rad(p.faces_deg);
        things.add(block);
        continue;
      }
      gltf.load(`/api/furnish/models/${p.model}.glb`, (file) => {
        const model = file.scene, box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3());
        // Sized to the piece that stood here, standing on the floor (or the table), facing the way it faced.
        const k = Math.min(p.height_m / Math.max(size.y, 0.01), Math.max(p.width_m, p.depth_m) / Math.max(size.x, size.z, 0.01) * 1.05);
        model.scale.setScalar(k);
        const fitted = new THREE.Box3().setFromObject(model), centre = fitted.getCenter(new THREE.Vector3());
        model.position.set(at.x - centre.x, at.y - fitted.min.y, at.z - centre.z);
        const turn = new THREE.Group();
        turn.position.copy(at); model.position.sub(at); turn.add(model); turn.rotation.y = Math.PI - rad(p.faces_deg);
        things.add(turn);
      });
    }

    let drag: { x: number; y: number } | null = null;
    const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY }; };
    const move = (e: PointerEvent) => {
      if (!drag) return;
      look -= (e.clientX - drag.x) * 0.2; tilt = Math.max(-70, Math.min(70, tilt + (e.clientY - drag.y) * 0.2));
      drag = { x: e.clientX, y: e.clientY };
      camera.rotation.set(rad(tilt), -rad(look), 0);
    };
    const up = () => { drag = null; };
    renderer.domElement.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    const resize = () => { renderer.setSize(el.clientWidth, el.clientHeight); camera.aspect = el.clientWidth / el.clientHeight; camera.updateProjectionMatrix(); };
    window.addEventListener("resize", resize);

    let raf = 0, bare = 0, shown = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      // The room clears, and fills, slowly enough to watch.
      const wantBare = live.current.state === "as_it_was" ? 0 : 1, wantShown = live.current.state === "furnished" ? 1 : 0;
      bare += (wantBare - bare) * 0.045; shown += (wantShown - shown) * 0.06;
      for (const m of cleared.mats) m.opacity = bare;
      things.visible = shown > 0.02;
      things.scale.setScalar(0.94 + 0.06 * shown);
      things.traverse((o) => { const mat = (o as THREE.Mesh).material as THREE.Material | undefined; if (mat && "opacity" in mat && !(o as THREE.Mesh).userData.fixed) { mat.transparent = true; mat.opacity = Math.min(1, shown * (mat.userData.base ?? (mat.userData.base = mat.opacity))); } });
      renderer.render(scene, camera);
    };
    frame();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("resize", resize);
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
    // Rebuilt only when the room or what stands in it changes, not on every poll.
  }, [id, scan, sweep, heading, eye, yaw, placed]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div className="fatal" role="alert">{error}</div>;
  const make = () => { setNote(null); api.furnishMake(id, scan).then(() => setNote("Making the furniture. Each piece takes a few minutes.")).catch((e: Error) => setNote(e.message)); };
  return (
    <div className="furnish">
      <div className="furnish-stage" ref={mount} />
      {room && (
        <>
          <p className="furnish-label" key={state}>{room.labels[state]}</p>
          {state === "furnished" && (
            <p className="furnish-count">
              <strong>{room.contents}</strong> pieces stood here
              {made < room.contents && <span>{made} of {room.contents} have a model{room.making?.running ? ", more on the way" : ""}</span>}
              {made < room.contents && room.can_generate && !room.making?.running && <button onClick={make}>Make the furniture</button>}
              {note && <span>{note}</span>}
              {room.making?.stopped && <span>{room.making.stopped}</span>}
            </p>
          )}
          <nav className="furnish-states" aria-label="The room">
            {ORDER.map((s, i) => <button key={s} aria-pressed={state === s} onClick={() => setState(s)}><kbd>{i + 1}</kbd>{["As it was", "Cleared", "Furnished again"][i]}</button>)}
          </nav>
        </>
      )}
    </div>
  );
}
