// Head gestures: the classifier on made-up head angles, and the rules for when a gesture may be acted on.
// The conversation is loaded with a pretend voice and a pretend camera, so no browser is needed.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const js = async (file) => ts.transpileModule(await readFile(new URL(`../src/${file}`, import.meta.url), "utf8"),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const asUrl = (code) => `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;

const coreUrl = asUrl(await js("gestures-core.ts"));
const { classify, headAngles, refusal, WINDOW_MS, SPEECH_WINS_MS } = await import(coreUrl);

// ---- the classifier ---------------------------------------------------------------------------

const FRAME = 66;   // the camera is read about 15 times a second
const series = (ms, at) => Array.from({ length: Math.floor(ms / FRAME) + 1 }, (_, i) => ({ t: i * FRAME, yaw: 0, pitch: 0, ...at(i * FRAME, i) }));
const wave = (degrees, perSecond, t) => degrees * Math.sin((2 * Math.PI * perSecond * t) / 1000);
const ramp = (t, from, to, start, end) => (t <= start ? from : t >= end ? to : from + ((to - from) * (t - start)) / (end - start));
const noise = (i, salt) => 1.5 * Math.sin(i * 12.9898 + salt * 78.233);   // small, repeatable, never more than 1.5 degrees

/** Feed the samples one at a time, as the camera does, and return everything that was ever recognised. */
function watched(samples) {
  const seen = new Set(), held = [];
  for (const s of samples) {
    held.push(s);
    while (s.t - held[0].t > WINDOW_MS) held.shift();
    const g = classify(held);
    if (g) seen.add(g);
  }
  return [...seen];
}

test("a clean nod is a nod", () => {
  const nod = series(1200, (t) => ({ pitch: wave(10, 2, t) }));
  assert.equal(classify(nod), "nod");
  assert.deepEqual(watched(nod), ["nod"]);
});

test("a clean shake is a shake", () => {
  const shake = series(1200, (t) => ({ yaw: wave(15, 2, t) }));
  assert.equal(classify(shake), "shake");
  assert.deepEqual(watched(shake), ["shake"]);
});

test("a nod with a little sideways noise is still a nod", () => {
  assert.deepEqual(watched(series(1200, (t, i) => ({ pitch: wave(10, 2, t), yaw: noise(i, 1) }))), ["nod"]);
});

test("a slow turn towards something, staying there, is nothing", () => {
  assert.deepEqual(watched(series(3000, (t) => ({ yaw: ramp(t, 0, 35, 200, 1700) }))), []);
});

test("one glance and slowly back is nothing", () => {
  const glance = series(3000, (t) => ({ yaw: t < 1000 ? ramp(t, 0, 25, 0, 700) : ramp(t, 25, 0, 1000, 1700) }));
  assert.deepEqual(watched(glance), []);
});

test("one quick glance and back, or one dip of the head, is nothing: it reverses only once", () => {
  assert.deepEqual(watched(series(2000, (t) => ({ yaw: t < 500 ? ramp(t, 0, 25, 250, 500) : ramp(t, 25, 0, 500, 750) }))), []);
  assert.deepEqual(watched(series(2000, (t) => ({ pitch: t < 500 ? ramp(t, 0, -14, 250, 500) : ramp(t, -14, 0, 500, 750) }))), []);
});

test("small jitter is nothing", () => {
  assert.deepEqual(watched(series(4000, (_, i) => ({ yaw: noise(i, 2), pitch: noise(i, 3) }))), []);
});

test("a diagonal wobble is nothing", () => {
  assert.deepEqual(watched(series(1500, (t) => ({ yaw: wave(12, 2, t), pitch: wave(12, 2, t) }))), []);
  // Still nothing when one axis leads a little, but not by enough to be clearly a nod.
  assert.deepEqual(watched(series(1500, (t) => ({ yaw: wave(10, 2, t), pitch: wave(13, 2, t) }))), []);
});

test("the gesture's axis must clearly lead: a nod mixed with too much sideways movement is nothing", () => {
  // The sideways part is too small to be a shake of its own, yet too large beside so small a nod.
  assert.deepEqual(watched(series(1500, (t) => ({ pitch: wave(5, 2, t), yaw: wave(3.9, 2, t) }))), []);
  // Nodding while turning away briskly: the nod is real, but the head travelled about as far sideways.
  assert.deepEqual(watched(series(1200, (t) => ({ pitch: wave(10, 2, t), yaw: ramp(t, 0, 48, 0, 1200) }))), []);
  // The same nod with a sway well under the limit is still a nod.
  assert.deepEqual(watched(series(1200, (t) => ({ pitch: wave(10, 2, t), yaw: wave(3.9, 2, t) }))), ["nod"]);
});

test("a faint nod is missed rather than guessed at", () => {
  assert.deepEqual(watched(series(1500, (t) => ({ pitch: wave(3, 2, t) }))), []);
});

test("an empty or too-short series is nothing", () => {
  assert.equal(classify([]), null);
  assert.equal(classify(series(150, (t) => ({ pitch: wave(10, 2, t) }))), null);
  assert.equal(classify([{ t: 0, yaw: 0, pitch: 0 }, { t: 66, yaw: 0, pitch: 12 }, { t: 132, yaw: 0, pitch: -12 }]), null);
});

test("a nod that ended a while ago is not found again", () => {
  const then = series(3200, (t) => ({ pitch: t <= 1000 ? wave(10, 2, t) : 0 }));
  assert.equal(classify(then), null);
});

test("the tracker jumping for single frames is not a gesture", () => {
  const glitchy = series(1500, (_, i) => ({ pitch: i === 5 || i === 9 || i === 13 ? 14 : 0 }));
  assert.deepEqual(watched(glitchy), []);
});

test("a movement does not carry on across a hole where the face was lost", () => {
  const nod = series(1200, (t) => ({ pitch: wave(10, 2, t) }));
  const broken = [...nod.filter((s) => s.t < 330), ...nod.filter((s) => s.t >= 330).map((s) => ({ ...s, t: s.t + 600 }))].filter((s) => s.t < 1300);
  assert.deepEqual(watched(broken), []);
});

test("head angles are read from the third column of the matrix, whatever the size of the face", () => {
  const turned = (yaw, pitch, scale = 1) => {
    const y = (yaw * Math.PI) / 180, p = (pitch * Math.PI) / 180, m = new Array(16).fill(0);
    m[8] = scale * Math.sin(y) * Math.cos(p); m[9] = scale * Math.sin(p); m[10] = scale * Math.cos(y) * Math.cos(p); m[15] = 1;
    return m;
  };
  const near = (got, want) => assert.ok(Math.abs(got - want) < 1e-6, `${got} is not ${want}`);
  near(headAngles(turned(0, 0)).yaw, 0); near(headAngles(turned(0, 0)).pitch, 0);
  near(headAngles(turned(20, 0)).yaw, 20); near(headAngles(turned(20, 0)).pitch, 0);
  near(headAngles(turned(0, -15)).pitch, -15);
  near(headAngles(turned(-12, 9, 7.5)).yaw, -12); near(headAngles(turned(-12, 9, 7.5)).pitch, 9);
  assert.equal(headAngles(new Array(16).fill(0)), null);
  assert.equal(headAngles([]), null);
});

test("a gesture may be acted on only in a live conversation that is simply listening", () => {
  const c = (presence, voice = "live", on = true) => refusal({ on, voice, presence });
  assert.equal(c("listening"), null);
  for (const p of ["speaking", "thinking", "hearing", "connecting", "idle"]) assert.equal(c(p), p);
  assert.equal(c("listening", "narration"), "voice is narration");
  assert.equal(c("listening", "silent"), "voice is silent");
  assert.equal(c("listening", "live", false), "no conversation");
});

// ---- the conversation: a pretend voice and a pretend camera -------------------------------------

globalThis.window = globalThis;   // the conversation asks the window for its timers
const fakes = (globalThis.__fakes = {});
const voiceUrl = asUrl("export const openVoice = (o, live) => globalThis.__fakes.openVoice(o, live);");
const cameraUrl = asUrl("export const startGestures = (o) => globalThis.__fakes.startGestures(o);");
const { conversation } = await import(asUrl((await js("conversation.ts"))
  .replaceAll('"./gestures-core"', JSON.stringify(coreUrl))
  .replaceAll('"./gestures"', JSON.stringify(cameraUrl))
  .replaceAll('"./voice"', JSON.stringify(voiceUrl))
  .replaceAll("import.meta.env.DEV", "true")));
const gesture = globalThis.__braceGesture;   // the development hook: the same path a gesture from the camera takes

const pause = (ms) => new Promise((yes) => setTimeout(yes, ms));
const settled = SPEECH_WINS_MS + 120;

/** Start a conversation. Returns what the pretend voice was sent, and handles on the pretend voice and camera. */
async function begin({ live = true, canHear = true, listenOnly = false, cameraWorks = true } = {}) {
  conversation.stop();
  const told = [], rig = { told, voice: null, camera: null, cameraStarts: 0, cameraStops: 0, voiceClosed: false };
  fakes.openVoice = async (o) => {
    rig.voice = o;
    if (live) { o.onState("connecting"); o.onState("live"); } else o.onState("narration");
    return { canHear: live && canHear && !listenOnly, text: (words) => told.push(words), cue() {}, note() {}, brief() {}, setMuted() {}, close() { rig.voiceClosed = true; } };
  };
  fakes.startGestures = async (o) => {
    rig.cameraStarts++;
    if (!cameraWorks) return null;
    rig.camera = o;
    return { stop() { rig.cameraStops++; } };
  };
  conversation.setStage({ key: "k", sessionUrl: "/session", notesUrl: "/notes", greeting: "", run: () => ({}) });
  await conversation.start(listenOnly);
  await pause(0);   // let the camera finish opening
  return rig;
}
const gestureLines = () => conversation.get().turns.filter((t) => t.gesture).map((t) => t.text);

test("a nod while Brace is listening is delivered, after the short wait, as a turn of its own", async () => {
  const rig = await begin();
  assert.equal(conversation.get().presence, "listening");
  assert.equal(conversation.get().gestures, "watching");
  assert.equal(rig.camera.eligible(), true);
  const outcome = gesture("nod");
  await pause(SPEECH_WINS_MS - 150);
  assert.deepEqual(rig.told, [], "nothing is sent before the wait is over");
  assert.equal(await outcome, "delivered");
  assert.deepEqual(rig.told, ["[gesture] The owner nodded: yes."]);
  assert.deepEqual(gestureLines(), ["Nodded: yes"]);
  assert.equal(conversation.get().turns.at(-1).who, "you");
});

test("a shake seen by the camera is delivered the same way", async () => {
  const rig = await begin();
  rig.camera.onGesture("shake");
  await pause(settled);
  assert.deepEqual(rig.told, ["[gesture] The owner shook their head: no."]);
  assert.deepEqual(gestureLines(), ["Shook head: no"]);
});

test("a gesture never interrupts: while Brace speaks or thinks, or the owner is heard, it is dropped and not kept", async () => {
  const rig = await begin();
  for (const moment of ["speaking", "thinking", "hearing"]) {
    rig.voice.onMoment(moment);
    assert.equal(rig.camera.eligible(), false, `the camera does not look while ${moment}`);
    assert.equal(await gesture("nod"), `dropped: ${moment}`);
    rig.camera.onGesture("shake");
    if (moment === "hearing") rig.voice.onMoment("thinking");   // the owner's turn ends
    rig.voice.onMoment("listening");
    await pause(settled);
    assert.deepEqual(rig.told, [], `nothing arrives late after ${moment}`);
    assert.deepEqual(gestureLines(), []);
  }
});

test("speech wins: a gesture is dropped if the owner starts to speak during the wait", async () => {
  const rig = await begin();
  const outcome = gesture("nod");
  await pause(200);
  rig.voice.onMoment("hearing");
  assert.equal(await outcome, "dropped: hearing");
  rig.voice.onMoment("thinking");
  rig.voice.onMoment("listening");   // back to listening before the wait would have ended: still dropped
  await pause(settled);
  assert.deepEqual(rig.told, []);
  assert.deepEqual(gestureLines(), []);
});

test("a gesture is dropped if Brace starts to speak during the wait", async () => {
  const rig = await begin();
  const outcome = gesture("shake");
  await pause(100);
  rig.voice.onMoment("speaking");
  assert.equal(await outcome, "dropped: speaking");
  await pause(settled);
  assert.deepEqual(rig.told, []);
});

test("talking over Brace is being heard, not listened for, until the owner's turn ends", async () => {
  const rig = await begin();
  rig.voice.onMoment("speaking");
  rig.voice.onMoment("hearing");
  rig.voice.onMoment("listening");   // Brace's sound was cut off; the owner is still mid-sentence
  assert.equal(conversation.get().presence, "hearing");
  assert.equal(rig.camera.eligible(), false);
  assert.equal(await gesture("shake"), "dropped: hearing");
});

test("only one gesture waits at a time", async () => {
  const rig = await begin();
  const first = gesture("nod");
  assert.equal(await gesture("shake"), "dropped: another gesture is waiting");
  assert.equal(await first, "delivered");
  assert.deepEqual(rig.told, ["[gesture] The owner nodded: yes."]);
});

test("ending the conversation lets go of the camera and drops a waiting gesture", async () => {
  const rig = await begin();
  const outcome = gesture("nod");
  conversation.stop();
  assert.equal(await outcome, "dropped: camera off");
  assert.equal(rig.cameraStops, 1);
  assert.equal(conversation.get().gestures, "off");
  assert.equal(await gesture("nod"), "dropped: no conversation");
  await pause(settled);
  assert.deepEqual(rig.told, []);
});

test("the camera is not opened for listen-only, with no microphone, or when the steps are only read aloud", async () => {
  for (const how of [{ listenOnly: true }, { canHear: false }, { live: false }]) {
    const rig = await begin(how);
    assert.equal(rig.cameraStarts, 0, JSON.stringify(how));
    assert.equal(conversation.get().gestures, "off");
    conversation.toggleGestures();
    await pause(0);
    assert.equal(rig.cameraStarts, 0, "the button cannot open it either");
  }
  assert.equal(await gesture("nod"), "dropped: voice is narration");
});

test("a refused camera leaves the conversation working", async () => {
  const rig = await begin({ cameraWorks: false });
  assert.equal(conversation.get().gestures, "unavailable");
  assert.equal(conversation.get().on, true);
  assert.equal(conversation.get().presence, "listening");
  conversation.say("What should I fix first?");
  assert.deepEqual(rig.told, ["What should I fix first?"]);
});

test("the button turns the camera off and on again", async () => {
  const rig = await begin();
  conversation.toggleGestures();
  assert.equal(conversation.get().gestures, "off");
  assert.equal(rig.cameraStops, 1);
  conversation.toggleGestures();
  await pause(0);
  assert.equal(conversation.get().gestures, "watching");
  assert.equal(rig.cameraStarts, 2);
});

test("a camera that finishes opening after the conversation ended is let go at once", async () => {
  const rig = await begin();
  conversation.toggleGestures();   // off
  let open;
  fakes.startGestures = () => new Promise((yes) => { open = () => yes({ stop() { rig.cameraStops++; } }); });
  conversation.toggleGestures();   // opening, and slow
  conversation.stop();
  open();
  await pause(0);
  assert.equal(rig.cameraStops, 2);
  assert.equal(conversation.get().gestures, "off");
});

test("a voice that drops out lets go of the camera", async () => {
  const rig = await begin();
  rig.voice.onState("silent");
  assert.equal(rig.cameraStops, 1);
  assert.equal(conversation.get().gestures, "off");
  assert.equal(await gesture("nod"), "dropped: voice is silent");
  conversation.stop();
});
