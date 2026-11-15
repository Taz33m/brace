/**
 * Look around by turning the phone: device orientation to a camera rotation.
 *
 * iPhone Safari only reports motion after a tap that calls DeviceOrientationEvent.requestPermission(),
 * and only on HTTPS. The maths is the usual one for a phone held in front of the face: alpha/beta/gamma
 * as Euler angles (YXZ), then a quarter turn about X so "looking ahead" is the phone upright, then the
 * screen's own rotation so landscape works.
 */
import * as THREE from "three";

type PermissionRequest = () => Promise<"granted" | "denied">;

export type MotionState = "unsupported" | "needs-tap" | "denied" | "on";

export function motionSupport(): MotionState {
  if (typeof window === "undefined" || !("DeviceOrientationEvent" in window)) return "unsupported";
  const req = (DeviceOrientationEvent as unknown as { requestPermission?: PermissionRequest }).requestPermission;
  return typeof req === "function" ? "needs-tap" : "on";
}

/** Must be called from a tap on iPhone. Resolves to the state after asking. */
export async function askForMotion(): Promise<MotionState> {
  const req = (DeviceOrientationEvent as unknown as { requestPermission?: PermissionRequest }).requestPermission;
  if (typeof req !== "function") return motionSupport();
  try {
    return (await req()) === "granted" ? "on" : "denied";
  } catch {
    return "denied";
  }
}

const zee = new THREE.Vector3(0, 0, 1);
const euler = new THREE.Euler();
const q0 = new THREE.Quaternion();
const q1 = new THREE.Quaternion(-Math.sqrt(0.5), 0, 0, Math.sqrt(0.5)); // -90 degrees about X

function screenAngle(): number {
  const o = (screen as Screen & { orientation?: { angle?: number } }).orientation;
  if (o && typeof o.angle === "number") return o.angle;
  const legacy = (window as unknown as { orientation?: number }).orientation;
  return typeof legacy === "number" ? legacy : 0;
}

/** Keeps the latest device orientation and writes it into a quaternion on demand. */
export function createOrientationReader() {
  let last: { alpha: number; beta: number; gamma: number } | null = null;
  const onOrient = (e: DeviceOrientationEvent) => {
    if (e.alpha == null || e.beta == null || e.gamma == null) return;
    last = { alpha: e.alpha, beta: e.beta, gamma: e.gamma };
  };
  window.addEventListener("deviceorientation", onOrient);
  return {
    /** True once a real reading has arrived (desktop browsers often never send one). */
    ready: () => last !== null,
    /** Write the phone's rotation into q. Returns false if there is no reading yet. */
    read(q: THREE.Quaternion): boolean {
      if (!last) return false;
      const d = Math.PI / 180;
      euler.set(last.beta * d, last.alpha * d, -last.gamma * d, "YXZ");
      q.setFromEuler(euler);
      q.multiply(q1);
      q.multiply(q0.setFromAxisAngle(zee, -screenAngle() * d));
      return true;
    },
    stop: () => window.removeEventListener("deviceorientation", onOrient),
  };
}

/** The compass yaw (radians, three.js rotation.y) a camera quaternion is looking along. */
export function yawOf(q: THREE.Quaternion): number {
  return new THREE.Euler().setFromQuaternion(q, "YXZ").y;
}
