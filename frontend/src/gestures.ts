/**
 * Watching the owner's head through the webcam, so a nod or a shake can answer a yes-or-no question.
 *
 * Frames never leave the browser. Each one is read by a model running in this page, reduced to two angles and
 * thrown away: nothing is recorded, uploaded or shown. The model and the code that runs it are served by this
 * app itself (public/mediapipe), so this works on a network with no internet.
 */
import type { FaceLandmarker } from "@mediapipe/tasks-vision";
import { classify, headAngles, WINDOW_MS, type Gesture, type HeadSample } from "./gestures-core";

export interface GestureOptions {
  /** True only while a gesture could be acted on. While it is false no frame is analysed at all. */
  eligible: () => boolean;
  onGesture: (gesture: Gesture) => void;
}
export interface GestureWatch { stop(): void }

/** The least time between two looks at the camera: about 15 a second, plenty for a head and light on the computer. */
const FRAME_MS = 60;
/** After a gesture is reported nothing is looked at for this long, so one long nod is not read twice. */
const COOLDOWN_MS = 2000;
/** How long to wait for someone to answer the camera prompt before carrying on without it. */
const PERMISSION_MS = 25_000;
const SERVED_FROM = `${import.meta.env.BASE_URL}mediapipe`;

/** The webcam, picture only. Null when there is none, it is refused, or nobody answers the prompt. */
async function camera(): Promise<MediaStream | null> {
  if (typeof navigator.mediaDevices?.getUserMedia !== "function") return null;
  let gaveUp = false, timer = 0;
  const asked = navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240, facingMode: "user" } });
  // A prompt answered after we stopped waiting would leave the camera on with nobody using it.
  asked.then((late) => { if (gaveUp) for (const track of late.getTracks()) track.stop(); }, () => {});
  try {
    return await Promise.race([asked, new Promise<never>((_, no) => {
      timer = window.setTimeout(() => { gaveUp = true; no(new Error("camera permission timed out")); }, PERMISSION_MS);
    })]);
  } catch (problem) {
    console.warn("No camera; head gestures are off and the conversation carries on by voice.", problem);
    return null;
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * Start watching for nods and shakes. Resolves to null, never throws, when the camera is refused or the
 * model cannot be loaded: the conversation must work the same without it.
 */
export async function startGestures(o: GestureOptions): Promise<GestureWatch | null> {
  let stream: MediaStream | null = null;
  let landmarker: FaceLandmarker | null = null;
  try {
    // Loaded here and not at the top of the file: the page does not carry the library unless the camera
    // is used, and if it fails to load only gestures are lost.
    const vision = await import("@mediapipe/tasks-vision");
    const files = await vision.FilesetResolver.forVisionTasks(`${SERVED_FROM}/wasm`);
    // The model is loaded before the camera is asked for, so a missing model never costs a permission prompt.
    landmarker = await vision.FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: `${SERVED_FROM}/face_landmarker.task`, delegate: "CPU" },
      runningMode: "VIDEO",
      numFaces: 1,
      outputFacialTransformationMatrixes: true,
    });
    stream = await camera();
    if (!stream) { landmarker.close(); return null; }
    // Never added to the page: the picture is for the model only, and there is no preview.
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    await video.play();
    return watch(o, video, stream, landmarker);
  } catch (problem) {
    console.warn("Head gestures are unavailable; the conversation carries on by voice.", problem);
    for (const track of stream?.getTracks() ?? []) track.stop();
    try { landmarker?.close(); } catch { /* never opened */ }
    return null;
  }
}

function watch(o: GestureOptions, video: HTMLVideoElement, stream: MediaStream, landmarker: FaceLandmarker): GestureWatch {
  const samples: HeadSample[] = [];
  let stopped = false, frame = 0, looked = 0, quietUntil = 0, warned = false;

  const look = (now: number) => {
    if (stopped) return;
    frame = requestAnimationFrame(look);
    // While a gesture could not be acted on, or one was just reported, nothing is analysed and what was
    // seen so far is forgotten: a movement made then can never be read as an answer later.
    if (now < quietUntil || !o.eligible()) { samples.length = 0; return; }
    if (now - looked < FRAME_MS || video.readyState < 2) return;
    looked = now;
    let matrix: number[] | undefined;
    try {
      matrix = landmarker.detectForVideo(video, now).facialTransformationMatrixes?.[0]?.data;
    } catch (problem) {
      if (!warned) { warned = true; console.warn("A camera frame could not be read.", problem); }
    }
    const angles = matrix ? headAngles(matrix) : null;
    // No face in this frame: a gesture cannot carry on across the gap, so start again.
    if (!angles) { samples.length = 0; return; }
    samples.push({ t: now, ...angles });
    while (samples.length && now - samples[0].t > WINDOW_MS) samples.shift();
    const gesture = classify(samples);
    if (!gesture) return;
    samples.length = 0;
    quietUntil = now + COOLDOWN_MS;
    o.onGesture(gesture);
  };
  frame = requestAnimationFrame(look);

  return {
    stop() {
      if (stopped) return;
      stopped = true;
      cancelAnimationFrame(frame);
      // Stopping the tracks is what lets go of the camera and puts its light out.
      for (const track of stream.getTracks()) track.stop();
      video.srcObject = null;
      try { landmarker.close(); } catch { /* already closed */ }
    },
  };
}
