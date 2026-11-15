import * as THREE from "three";

export const KINDS = ["toilet", "chair", "sofa", "table", "lamp", "plant", "bed"] as const;
export type Kind = typeof KINDS[number];
export type Furniture = { id: string; kind: Kind; color: string; finish: "matte" | "gold" | "chrome" | "wood"; room: "kitchen" | "bathroom"; x: number; z: number; rotation: number; scale: number };

/** Parametric furniture, assembled locally. These are editable concept models, not generated product matches. */
export function furniture(item: Furniture): THREE.Group {
  const group = new THREE.Group();
  const metal = item.finish === "gold" || item.finish === "chrome";
  const base = new THREE.MeshStandardMaterial({ color: item.finish === "gold" ? 0xeac25c : item.finish === "chrome" ? 0xd5dce4 : item.finish === "wood" ? 0x93613f : item.color, metalness: metal ? .92 : .05, roughness: metal ? .22 : .62 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x292722, roughness: .8 });
  const add = (geometry: THREE.BufferGeometry, x: number, y: number, z: number, material = base) => {
    const mesh = new THREE.Mesh(geometry, material); mesh.position.set(x, y, z); group.add(mesh); return mesh;
  };
  const box = (w: number, h: number, d: number, x: number, y: number, z: number, material = base) => add(new THREE.BoxGeometry(w, h, d), x, y, z, material);
  const cyl = (r: number, h: number, x: number, y: number, z: number, material = base) => add(new THREE.CylinderGeometry(r, r, h, 28), x, y, z, material);
  const legs = (w: number, d: number, h: number) => { for (const x of [-w / 2, w / 2]) for (const z of [-d / 2, d / 2]) box(.055, h, .055, x, h / 2, z); };
  if (item.kind === "toilet") {
    add(new THREE.LatheGeometry([new THREE.Vector2(.13, 0), new THREE.Vector2(.17, .06), new THREE.Vector2(.13, .22), new THREE.Vector2(.25, .36), new THREE.Vector2(.25, .40), new THREE.Vector2(.20, .40), new THREE.Vector2(.13, .30)], 48), 0, 0, .08).scale.z = 1.3;
    const seat = add(new THREE.TorusGeometry(.235, .028, 16, 64), 0, .415, .08); seat.rotation.x = Math.PI / 2; seat.scale.y = 1.3;
    box(.43, .42, .19, 0, .60, -.27); box(.46, .035, .22, 0, .825, -.27);
    cyl(.025, .025, .15, .84, -.27, dark);
  } else if (item.kind === "chair") {
    legs(.43, .43, .44); box(.55, .09, .55, 0, .47, 0); box(.55, .55, .07, 0, .78, -.24);
  } else if (item.kind === "sofa") {
    legs(1.55, .65, .18); box(1.8, .28, .85, 0, .34, 0); box(1.8, .55, .18, 0, .70, -.35);
    for (const x of [-.82, .82]) box(.20, .48, .85, x, .55, 0);
    for (const x of [-.39, .39]) box(.75, .12, .65, x, .52, .05);
  } else if (item.kind === "table") {
    legs(1.05, .65, .72); box(1.25, .08, .85, 0, .76, 0);
  } else if (item.kind === "bed") {
    legs(1.3, 1.65, .24); box(1.5, .22, 2, 0, .33, 0); box(1.5, .75, .08, 0, .65, -.97);
    const linen = new THREE.MeshStandardMaterial({ color: item.color, roughness: .95 });
    box(1.45, .19, 1.9, 0, .53, 0, linen); for (const x of [-.37, .37]) box(.60, .12, .4, x, .69, -.65, linen);
  } else if (item.kind === "lamp") {
    cyl(.23, .045, 0, .025, 0); cyl(.025, 1.4, 0, .72, 0);
    add(new THREE.CylinderGeometry(.16, .32, .40, 32, 1, true), 0, 1.48, 0);
    const bulb = new THREE.MeshStandardMaterial({ color: 0xffe5a0, emissive: 0xffc465, emissiveIntensity: .7 }); add(new THREE.SphereGeometry(.06, 16, 12), 0, 1.4, 0, bulb);
  } else {
    add(new THREE.CylinderGeometry(.22, .15, .42, 28), 0, .21, 0);
    const leaf = new THREE.MeshStandardMaterial({ color: 0x447b3d, roughness: .85 });
    cyl(.025, .8, 0, .75, 0, dark);
    for (let i = 0; i < 9; i++) { const a = i * 2.4; const m = add(new THREE.SphereGeometry(1, 16, 12), Math.sin(a) * .22, .65 + i * .055, Math.cos(a) * .22, leaf); m.scale.set(.14, .29, .055); m.rotation.set(.5, a, .6); }
  }
  group.position.set(item.x, -1.55, item.z); group.rotation.y = item.rotation; group.scale.setScalar(item.scale);
  return group;
}

export function disposeObject(object: THREE.Object3D) {
  const materials = new Set<THREE.Material>();
  object.traverse(node => { if (node instanceof THREE.Mesh) { node.geometry.dispose(); (Array.isArray(node.material) ? node.material : [node.material]).forEach(m => materials.add(m)); } });
  materials.forEach(m => m.dispose());
}
