// The live voice and the conversation, without a browser: a pretend connection stands in for the voice service,
// and a pretend voice stands in under the conversation. Run with: node --test tests/voice.test.mjs
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const js = async (file) => ts.transpileModule(await readFile(new URL(`../src/${file}`, import.meta.url), "utf8"),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const asUrl = (code) => `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
const pause = (ms) => new Promise((yes) => setTimeout(yes, ms));
const swap = (code, from, to) => { assert.ok(code.includes(from), `the source no longer contains: ${from}`); return code.replaceAll(from, to); };

// ---- the small decisions ------------------------------------------------------------------------

const coreJs = await js("voice-core.ts");
const core = await import(asUrl(coreJs));

test("a dropped line is reopened twice at most, and a line that held steady starts counting again", () => {
  assert.equal(core.RECONNECTS, 2);
  assert.equal(core.nextAttempt(0, 0), 1);
  assert.equal(core.nextAttempt(1, 0), 2);
  assert.equal(core.nextAttempt(2, 0), null);
  assert.equal(core.nextAttempt(2, core.STEADY_MS), 1, "a new fault, not the same one again");
  assert.equal(core.nextAttempt(2, core.STEADY_MS - 1), null, "a line that keeps falling over is given up on");
  assert.ok(core.backoffMs(1) < core.backoffMs(2));
  assert.equal(core.backoffMs(9), core.backoffMs(2));
  assert.equal(core.DISCONNECTED_MS, 4000);
  assert.equal(core.TOOL_MS, 20_000);
});

test("after a reconnect the model is told not to greet again, and what was last said", () => {
  const said = [];
  core.recall(said, "agent", "  The Parker has six jobs.  ");
  core.recall(said, "you", "");
  core.recall(said, "you", "Approve the first one.");
  assert.deepEqual(said, [{ who: "agent", text: "The Parker has six jobs." }, { who: "you", text: "Approve the first one." }]);
  const waiting = core.rejoin(said, true);
  assert.match(waiting, /Do not greet them again/);
  assert.match(waiting, /You said: The Parker has six jobs\.\nThey said: Approve the first one\./);
  assert.match(waiting, /Answer it now/);
  assert.match(core.rejoin(said, false), /Wait for them to speak/);
  assert.match(core.rejoin([], false), /Nothing had been said yet/);
  for (let i = 0; i < 20; i++) core.recall(said, "agent", `line ${i}`);
  assert.equal(said.length, core.RECALL);
  assert.equal(said.at(-1).text, "line 19");
  assert.ok(core.rejoin([{ who: "agent", text: "x".repeat(5000) }], false).length < 1000, "a long line is cut short");
});

test("how a response ended, and what an error says, are read without trusting their shape", () => {
  assert.deepEqual(core.ending({ response: { status: "completed" } }), { status: "completed", why: null });
  assert.deepEqual(core.ending({}), { status: "completed", why: null });
  assert.deepEqual(core.ending({ response: { status: "cancelled", status_details: { reason: "turn_detected" } } }), { status: "cancelled", why: "turn_detected" });
  assert.deepEqual(core.ending({ response: { status: "failed", status_details: { error: { code: "rate_limit_exceeded", message: "slow down" } } } }), { status: "failed", why: "rate_limit_exceeded" });
  assert.deepEqual(core.fault({ error: { code: "x", message: "y" } }), { code: "x", message: "y" });
  assert.deepEqual(core.fault({ error: { type: "invalid_request_error" } }), { code: "invalid_request_error", message: "" });
  assert.deepEqual(core.fault(null), { code: "unknown", message: "" });
});

// ---- a pretend browser --------------------------------------------------------------------------

globalThis.window = globalThis;
const handlers = new Map();   // what has been attached to the window, by event name
globalThis.addEventListener = (type, fn) => { if (!handlers.has(type)) handlers.set(type, new Set()); handlers.get(type).add(fn); };
globalThis.removeEventListener = (type, fn) => { handlers.get(type)?.delete(fn); };
const fire = (type, event = {}) => { for (const fn of [...(handlers.get(type) ?? [])]) fn(event); };
const store = new Map();
globalThis.sessionStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); }, removeItem: (k) => { store.delete(k); } };
console.warn = () => {};   // drops and failures are warned about on purpose; the test output stays readable

// ---- the live voice over a pretend line ---------------------------------------------------------

const net = { sessions: 0, calls: 0, refuseSession: false, refuseCall: false, pcs: [], playRefused: false, plays: 0, removed: 0 };
class Channel {
  readyState = "connecting"; sent = [];
  send(text) { this.sent.push(JSON.parse(text)); }
  close() { this.readyState = "closed"; }
  /** The service sends an event. */
  say(event) { this.onmessage?.({ data: JSON.stringify(event) }); }
  /** The service, or the network, takes the channel away. */
  drop() { this.readyState = "closed"; this.onclose?.(); }
}
globalThis.RTCPeerConnection = class {
  connectionState = "new"; tracks = [];
  constructor() { net.pcs.push(this); }
  addTrack(track) { this.tracks.push(track); }
  addTransceiver() {}
  createDataChannel() { return (this.channel = new Channel()); }
  async createOffer() { return { type: "offer", sdp: "offer" }; }
  async setLocalDescription() {}
  async setRemoteDescription() { this.channel.readyState = "open"; this.connectionState = "connected"; this.ontrack?.({ streams: [{}] }); }
  close() { this.connectionState = "closed"; this.closedByUs = true; }
  state(now) { this.connectionState = now; this.onconnectionstatechange?.(); }
};
globalThis.document = {
  body: { appendChild() {} },
  createElement: () => ({
    setAttribute() {}, remove() { net.removed++; },
    play() { net.plays++; return net.playRefused ? Promise.reject(Object.assign(new Error("no click yet"), { name: "NotAllowedError" })) : Promise.resolve(); },
  }),
};
globalThis.fetch = async (url) => {
  if (String(url).startsWith("/session")) { net.sessions++; return net.refuseSession ? { ok: false, status: 503 } : { ok: true, json: async () => ({ value: `key-${net.sessions}` }) }; }
  net.calls++;
  return net.refuseCall ? { ok: false, status: 500 } : { ok: true, text: async () => "answer" };
};

// The same code, with the waits shortened so the tests do not take a minute.
const fastCore = [["BACKOFF_MS = [600, 2000]", "BACKOFF_MS = [5, 10]"], ["DISCONNECTED_MS = 4000", "DISCONNECTED_MS = 40"],
  ["TOOL_MS = 20_000", "TOOL_MS = 60"], ["UNCONFIRMED_MS = 10_000", "UNCONFIRMED_MS = 80"]].reduce((code, [from, to]) => swap(code, from, to), coreJs);
const { openVoice } = await import(asUrl(swap(swap(await js("voice.ts"), '"./voice-core"', JSON.stringify(asUrl(fastCore))), "import.meta.env.DEV", "true")));

/** Open a live voice. `line()` is the channel in use now; `types()` is what has been sent on it. */
async function open({ greeting = "", run = () => ({ ok: true }), listenOnly = false } = {}) {
  Object.assign(net, { refuseSession: false, refuseCall: false, playRefused: net.playRefused, pcs: [] });
  const rig = { states: [], captions: [], moments: [], sounds: [] };
  rig.voice = await openVoice({
    sessionUrl: "/session", run, greeting, listenOnly,
    onState: (s) => rig.states.push(s), onCaption: (who, text, id) => rig.captions.push({ who, text, id }),
    onMoment: (m) => rig.moments.push(m), onSound: (b) => rig.sounds.push(b),
  }, true);
  rig.line = () => net.pcs.at(-1).channel;
  rig.types = () => rig.line().sent.map((e) => e.type === "conversation.item.create" ? `item:${e.item.type === "message" ? e.item.role : e.item.type}` : e.type);
  rig.texts = () => rig.line().sent.filter((e) => e.item?.type === "message").map((e) => e.item.content[0].text);
  /** One whole response from the service. */
  rig.answer = (status = "completed") => { rig.line().say({ type: "response.created" }); rig.line().say({ type: "response.done", response: { status } }); };
  return rig;
}

test("a live voice opens, greets once, and closes cleanly", async () => {
  const rig = await open({ greeting: "Greet the owner." });
  assert.deepEqual(rig.states, ["connecting", "live"]);
  assert.equal(rig.voice.canHear, false, "no microphone in this pretend browser");
  assert.deepEqual(rig.types(), ["item:system", "response.create"]);
  assert.match(rig.texts()[0], /Greet the owner/);
  rig.voice.close();
  assert.equal(net.pcs[0].closedByUs, true);
  await pause(30);
  assert.equal(net.pcs.length, 1, "a voice the person ended is not reopened");
  assert.deepEqual(rig.states, ["connecting", "live"]);
});

test("in development a test can supply the microphone", async () => {
  const track = { enabled: true, stopped: false, stop() { this.stopped = true; } };
  globalThis.__braceMic = async () => ({ getTracks: () => [track], getAudioTracks: () => [track] });
  try {
    const rig = await open();
    assert.equal(rig.voice.canHear, true);
    assert.deepEqual(net.pcs[0].tracks, [track]);
    rig.voice.setMuted(true);
    assert.equal(track.enabled, false);
    rig.voice.setMuted(false);
    assert.equal(track.enabled, true);
    const listenOnly = await open({ listenOnly: true });
    assert.equal(listenOnly.voice.canHear, false, "listen-only still means no microphone");
    listenOnly.voice.close();
    rig.voice.close();
    assert.equal(track.stopped, true);
  } finally { delete globalThis.__braceMic; }
});

test("a tool's result is spoken once the response that called it is done", async () => {
  const rig = await open({ run: (name, args) => ({ ok: true, name, args }) });
  rig.line().say({ type: "response.created" });
  rig.line().say({ type: "response.function_call_arguments.done", name: "approve", call_id: "c1", arguments: '{"id":"A1"}' });
  await pause(5);
  assert.deepEqual(rig.types(), ["item:function_call_output"], "the follow-up waits for the response in flight");
  assert.deepEqual(JSON.parse(rig.line().sent[0].item.output), { ok: true, name: "approve", args: { id: "A1" } });
  rig.line().say({ type: "response.done", response: { status: "completed" } });
  assert.deepEqual(rig.types(), ["item:function_call_output", "response.create"]);
  rig.voice.close();
});

test("with two tools in one response the follow-up waits for both, and a waiting line waits for the tools", async () => {
  let finishSlow;
  const rig = await open({ run: (name) => (name === "slow" ? new Promise((yes) => { finishSlow = () => yes({ ok: true }); }) : { ok: true }) });
  rig.line().say({ type: "response.created" });
  rig.line().say({ type: "response.function_call_arguments.done", name: "quick", call_id: "c1", arguments: "{}" });
  rig.line().say({ type: "response.function_call_arguments.done", name: "slow", call_id: "c2", arguments: "{}" });
  await pause(5);
  rig.line().say({ type: "response.done", response: { status: "completed" } });
  rig.voice.cue("finding", "A1 Trim the pine");
  assert.deepEqual(rig.types(), ["item:function_call_output"], "nothing is asked for while a tool is still running");
  finishSlow();
  await pause(5);
  assert.deepEqual(rig.types(), ["item:function_call_output", "item:function_call_output", "response.create"]);
  rig.answer();
  assert.deepEqual(rig.types().slice(3), ["item:system", "response.create"], "then the waiting line is said");
  rig.voice.close();
});

test("a tool that never answers is reported as failed, and one that throws is too", async () => {
  const rig = await open({ run: (name) => { if (name === "broken") throw new Error("no such action"); return new Promise(() => {}); } });
  rig.line().say({ type: "response.function_call_arguments.done", name: "stuck", call_id: "c1", arguments: "{}" });
  rig.line().say({ type: "response.function_call_arguments.done", name: "broken", call_id: "c2", arguments: "not json" });
  await pause(120);
  const outputs = rig.line().sent.filter((e) => e.item?.type === "function_call_output").map((e) => JSON.parse(e.item.output));
  assert.equal(outputs.length, 2);
  assert.ok(outputs.every((o) => o.ok === false && o.say === "That did not work. Try again."));
  assert.ok(outputs.some((o) => /timed out/.test(o.detail)));
  assert.equal(rig.types().filter((t) => t === "response.create").length, 1, "one follow-up for both");
  rig.voice.close();
});

test("a tool's result is not spoken over a person who has started talking", async () => {
  const rig = await open();
  rig.line().say({ type: "response.created" });
  rig.line().say({ type: "response.function_call_arguments.done", name: "approve", call_id: "c1", arguments: "{}" });
  await pause(5);
  rig.line().say({ type: "input_audio_buffer.speech_started", item_id: "u1" });
  rig.line().say({ type: "response.done", response: { status: "cancelled" } });
  assert.deepEqual(rig.types(), ["item:function_call_output"], "held while they are speaking");
  rig.line().say({ type: "input_audio_buffer.speech_stopped", item_id: "u1" });
  rig.answer();   // the service answers their speech by itself, with the tool's result in front of it
  assert.deepEqual(rig.types(), ["item:function_call_output"], "and not said a second time");
  rig.voice.close();
});

test("a typed turn waits for the response in flight, but not for a noisy room", async () => {
  const rig = await open();
  rig.line().say({ type: "response.created" });
  rig.voice.text("What should I fix first?");
  assert.deepEqual(rig.types(), ["item:user"]);
  rig.line().say({ type: "input_audio_buffer.speech_started", item_id: "noise" });
  rig.line().say({ type: "response.done", response: { status: "completed" } });
  assert.deepEqual(rig.types(), ["item:user", "response.create"]);
  rig.voice.close();
});

test("an error that refuses a response does not leave the voice stuck", async () => {
  const rig = await open();
  rig.voice.cue("say", "One.");
  rig.voice.cue("say", "Two.");
  assert.deepEqual(rig.types(), ["item:system", "response.create"]);
  rig.line().say({ type: "error", error: { type: "server_error", code: "boom", message: "no" } });
  assert.deepEqual(rig.types(), ["item:system", "response.create", "item:system", "response.create"], "the next line is said");
  rig.voice.close();
});

test("a response that is never confirmed is given up on after a while", async () => {
  const rig = await open();
  rig.voice.cue("say", "One.");
  rig.voice.cue("say", "Two.");
  await pause(130);
  assert.equal(rig.types().filter((t) => t === "response.create").length, 2);
  assert.equal(rig.moments.at(-1), "thinking");
  rig.voice.close();
});

test("losing to a response the service already started asks again once that one is done", async () => {
  const rig = await open();
  rig.voice.text("Approve it.");
  rig.line().say({ type: "response.created" });   // the service's own
  rig.line().say({ type: "error", error: { code: "conversation_already_has_active_response", message: "busy" } });
  assert.equal(rig.types().filter((t) => t === "response.create").length, 1);
  rig.line().say({ type: "response.done", response: { status: "completed" } });
  assert.equal(rig.types().filter((t) => t === "response.create").length, 2);
  rig.voice.close();
});

test("a failed response is asked for once more, and only once", async () => {
  const rig = await open();
  rig.voice.text("What should I fix first?");
  rig.answer("failed");
  assert.equal(rig.types().filter((t) => t === "response.create").length, 2);
  rig.answer("failed");
  assert.equal(rig.types().filter((t) => t === "response.create").length, 2, "a second failure is left alone");
  assert.equal(rig.moments.at(-1), "listening");
  rig.voice.cue("say", "Still here.");
  assert.equal(rig.types().filter((t) => t === "response.create").length, 3, "and the voice is not stuck");
  rig.voice.close();
});

test("speech that could not be written down does not leave an empty line behind", async () => {
  const rig = await open();
  rig.line().say({ type: "input_audio_buffer.speech_started", item_id: "u1" });
  rig.line().say({ type: "conversation.item.input_audio_transcription.failed", item_id: "u1" });
  assert.deepEqual(rig.captions, [{ who: "you", text: "", id: "u1" }]);
  rig.voice.close();
});

test("a dropped line is reopened: no second greeting, what was said is recalled, and what waited is sent", async () => {
  const rig = await open({ greeting: "Greet the owner." });
  rig.voice.brief("Notes for the 12 hour step.");
  rig.voice.note("[on screen] A2");
  rig.answer();
  rig.line().say({ type: "response.output_audio_transcript.done", item_id: "a1", transcript: "Welcome to The Parker." });
  rig.line().say({ type: "response.output_audio_transcript.delta", item_id: "a2", delta: "The pine is" });
  const first = rig.line();
  first.drop();
  assert.deepEqual(rig.states, ["connecting", "live", "connecting"]);
  assert.deepEqual(rig.captions.at(-1), { who: "agent", text: "The pine is", id: "a2" }, "the half-said line is finished as it stands");
  rig.voice.cue("finding", "A3 Clear the drains");
  rig.voice.text("Approve the first one.");
  assert.equal(first.sent.length, 4, "nothing is sent on the dead line");
  await pause(40);
  assert.deepEqual(rig.states, ["connecting", "live", "connecting", "live"]);
  assert.equal(net.pcs.length, 2);
  assert.notEqual(rig.line(), first);
  assert.deepEqual(rig.types(), ["session.update", "item:system", "item:system", "item:user", "response.create"]);
  assert.equal(rig.line().sent[0].session.instructions, "Notes for the 12 hour step.");
  const [recap, screen, typed] = rig.texts();
  assert.match(recap, /Do not greet them again/);
  assert.match(recap, /You said: Welcome to The Parker\.\nYou said: The pine is/);
  assert.match(recap, /Answer it now/);
  assert.ok(!rig.texts().some((t) => /Greet the owner/.test(t)), "the greeting is not asked for again");
  assert.equal(screen, "[on screen] A2");
  assert.equal(typed, "Approve the first one.");
  rig.answer();
  assert.deepEqual(rig.types().slice(5), ["item:system", "response.create"], "the line that waited through the drop is said");
  assert.match(rig.texts().at(-1), /\[finding\] A3 Clear the drains/);
  rig.voice.close();
});

test("a tool still running when the line drops does not answer on the new line", async () => {
  let finish;
  const rig = await open({ run: () => new Promise((yes) => { finish = () => yes({ ok: true }); }) });
  rig.line().say({ type: "response.function_call_arguments.done", name: "approve", call_id: "c1", arguments: "{}" });
  rig.line().drop();
  await pause(40);
  finish();
  await pause(5);
  assert.deepEqual(rig.types(), ["item:system"], "only the reminder");
  rig.voice.cue("say", "Carrying on.");
  assert.deepEqual(rig.types(), ["item:system", "item:system", "response.create"], "and the voice is not left waiting for the tool");
  rig.voice.close();
});

test("a failed connection, and one that stays disconnected, count as drops; a blip does not", async () => {
  const rig = await open();
  net.pcs[0].state("disconnected");
  await pause(10);
  net.pcs[0].state("connected");
  await pause(60);
  assert.deepEqual(rig.states, ["connecting", "live"], "a blip that mends itself is left alone");
  net.pcs[0].state("disconnected");
  await pause(90);
  assert.deepEqual(rig.states, ["connecting", "live", "connecting", "live"]);
  net.pcs.at(-1).state("failed");
  await pause(40);
  assert.equal(net.pcs.length, 3);
  assert.deepEqual(rig.states.slice(4), ["connecting", "live"], "the second attempt");
  net.pcs.at(-1).state("failed");
  await pause(40);
  assert.equal(net.pcs.length, 3, "no third attempt");
  assert.equal(rig.states.at(-1), "silent", "a line that keeps falling over is given up on");
  rig.voice.close();
});

test("if the line cannot be reopened in two attempts the voice goes silent", async () => {
  const rig = await open();
  const before = net.sessions;
  net.refuseSession = true;
  rig.line().drop();
  await pause(60);
  assert.equal(net.sessions - before, 2);
  assert.deepEqual(rig.states, ["connecting", "live", "connecting", "silent"]);
  rig.voice.cue("say", "Nobody hears this.");   // must not throw
  net.refuseSession = false;
});

test("the second attempt can succeed where the first failed", async () => {
  const rig = await open();
  net.refuseCall = true;
  rig.line().drop();
  await pause(12);
  net.refuseCall = false;
  await pause(40);
  assert.deepEqual(rig.states, ["connecting", "live", "connecting", "live"]);
  rig.voice.close();
});

test("ending the conversation while the line is being reopened stops the attempts", async () => {
  const rig = await open();
  const before = net.sessions;
  rig.line().drop();
  rig.voice.close();
  await pause(40);
  assert.equal(net.sessions, before);
  assert.deepEqual(rig.states, ["connecting", "live", "connecting"]);
});

test("sound refused for want of a click is kept, and the next click or key press lets it through", async () => {
  net.playRefused = true;
  const rig = await open();
  await pause(0);
  assert.deepEqual(rig.sounds, [true]);
  assert.deepEqual(rig.states, ["connecting", "live"], "the session is kept");
  net.playRefused = false;
  fire("keydown", {});
  await pause(0);
  assert.deepEqual(rig.sounds, [true, false]);
  const plays = net.plays;
  fire("pointerdown", {});
  assert.equal(net.plays, plays, "and nothing listens for clicks any more");
  rig.voice.close();
});

// ---- the conversation over a pretend voice ------------------------------------------------------

const fakes = (globalThis.__fakes = {});
const conversationJs = [['"./gestures-core"', JSON.stringify(asUrl(await js("gestures-core.ts")))],
  ['"./gestures"', JSON.stringify(asUrl("export const startGestures = async () => null;"))],
  ['"./voice"', JSON.stringify(asUrl("export const openVoice = (o, live) => globalThis.__fakes.openVoice(o, live);"))],
  ["import.meta.env.DEV", "true"]].reduce((code, [from, to]) => swap(code, from, to), await js("conversation.ts"));
const { conversation } = await import(asUrl(conversationJs));
const STAGE = { key: "k", sessionUrl: "/session", notesUrl: "/notes", greeting: "", run: () => ({}) };
const RESUME = 50 + 30;   // a little longer than the conversation waits before bringing itself back

/** A pretend voice under the conversation. `mic` is whether its microphone is open. */
function pretend({ canHear = true } = {}) {
  const rig = { opens: 0, closed: 0, mic: true, options: null, listenOnly: null, told: [] };
  fakes.openVoice = async (o) => {
    rig.opens++; rig.options = o; rig.listenOnly = o.listenOnly;
    o.onState("connecting"); o.onState("live");
    return { canHear: canHear && !o.listenOnly, text: (w) => rig.told.push(w), cue() {}, note() {}, brief() {}, setMuted(m) { rig.mic = !m; }, close() { rig.closed++; } };
  };
  return rig;
}
async function begin(how = {}) {
  conversation.end();
  if (conversation.get().talk !== "open") conversation.setTalk("open");
  const rig = pretend(how);
  conversation.setStage(STAGE);
  await conversation.start(how.listenOnly ?? false);
  return rig;
}
const space = (more = {}) => {
  const e = { code: "Space", key: " ", repeat: false, target: { tagName: "BODY" }, prevented: false, preventDefault() { this.prevented = true; }, ...more };
  fire("keydown", e);
  return e;
};
const release = () => fire("keyup", { code: "Space", key: " " });

test("in hold mode the microphone is on only while Space is held, with a moment's grace at the end", async () => {
  const rig = await begin();
  assert.equal(conversation.get().talk, "open");
  assert.equal(rig.mic, true);
  conversation.toggleTalk();
  assert.equal(conversation.get().talk, "hold");
  assert.equal(store.get("brace.talk"), "hold");
  assert.equal(rig.mic, false);
  const down = space();
  assert.equal(down.prevented, true, "the page must not scroll");
  assert.equal(conversation.get().holding, true);
  assert.equal(rig.mic, true);
  assert.equal(space({ repeat: true }).prevented, true);
  assert.equal(conversation.get().holding, true, "a repeat changes nothing");
  release();
  assert.equal(conversation.get().holding, false);
  assert.equal(rig.mic, true, "the end of the last word is still on its way");
  await pause(260);
  assert.equal(rig.mic, false);
  conversation.toggleTalk();
  assert.equal(rig.mic, true, "open again");
  conversation.end();
});

test("Space typed into a field or pressed on a button is not a hold", async () => {
  const rig = await begin();
  conversation.setTalk("hold");
  for (const target of [{ tagName: "INPUT" }, { tagName: "TEXTAREA" }, { tagName: "SELECT" }, { tagName: "BUTTON" }, { tagName: "DIV", isContentEditable: true }]) {
    assert.equal(space({ target }).prevented, false, target.tagName);
    assert.equal(conversation.get().holding, false);
  }
  assert.equal(space({ code: "KeyA", key: "a" }).prevented, false);
  assert.equal(space({ metaKey: true }).prevented, false);
  assert.equal(rig.mic, false);
  conversation.end();
});

test("holding Space in open mode switches to hold mode; a tap does not", async () => {
  const rig = await begin();
  space(); release();
  await pause(340);
  assert.equal(conversation.get().talk, "open", "a tap changes nothing");
  space();
  await pause(340);
  assert.equal(conversation.get().talk, "hold");
  assert.equal(conversation.get().holding, true);
  assert.equal(rig.mic, true);
  release();
  await pause(260);
  assert.equal(rig.mic, false);
  conversation.setTalk("open");   // the owner says otherwise
  const down = space();
  await pause(340);
  assert.equal(conversation.get().talk, "open", "Space no longer switches it for them");
  assert.equal(down.prevented, false);
  release();
  conversation.end();
});

test("mute wins over a hold", async () => {
  const rig = await begin();
  conversation.setTalk("hold");
  space();
  assert.equal(rig.mic, true);
  conversation.toggleMute();
  assert.equal(conversation.get().holding, false);
  assert.equal(rig.mic, false, "muted at once, with no grace");
  release();
  space();
  conversation.hold(true);
  assert.equal(conversation.get().holding, false);
  assert.equal(rig.mic, false);
  release();
  conversation.toggleMute();
  assert.equal(rig.mic, false, "unmuted in hold mode is still off until held");
  conversation.hold(true);
  assert.equal(rig.mic, true);
  conversation.hold(false);
  conversation.end();
});

test("the window losing focus lets go of a hold, and a voice that cannot hear leaves Space alone", async () => {
  const rig = await begin();
  conversation.setTalk("hold");
  space();
  fire("blur");
  assert.equal(conversation.get().holding, false);
  await pause(260);
  assert.equal(rig.mic, false);
  await begin({ listenOnly: true });
  conversation.setTalk("hold");
  assert.equal(space().prevented, false);
  assert.equal(conversation.get().holding, false);
  conversation.end();
  assert.equal(space().prevented, false, "and with no conversation the key is not listened for at all");
});

test("a conversation is remembered until the End button, and comes back by itself", async () => {
  let rig = await begin();
  assert.equal(store.get("brace.conversation"), "talk");
  conversation.setStage(null);
  conversation.stop();   // what a page does when it unmounts
  assert.equal(store.get("brace.conversation"), "talk");
  assert.equal(conversation.get().on, false);
  rig = pretend();
  conversation.setStage(STAGE);
  await pause(RESUME);
  assert.equal(rig.opens, 1);
  assert.equal(rig.listenOnly, false);
  assert.equal(conversation.get().on, true);
  conversation.end();
  assert.equal(store.has("brace.conversation"), false);
  rig = pretend();
  conversation.setStage(null);
  conversation.setStage(STAGE);
  await pause(RESUME);
  assert.equal(rig.opens, 0, "ended by the owner: it stays ended");
});

test("a conversation started without the microphone comes back without it", async () => {
  await begin({ listenOnly: true });
  assert.equal(store.get("brace.conversation"), "listen-only");
  conversation.stop();
  const rig = pretend();
  conversation.setStage(STAGE);
  await pause(RESUME);
  assert.equal(rig.listenOnly, true);
  conversation.end();
});

test("a page that mounts, unmounts and mounts again opens one session", async () => {
  await begin();
  conversation.stop();
  const rig = pretend();
  conversation.setStage(STAGE); conversation.setStage(null); conversation.stop(); conversation.setStage(STAGE);   // React's double mount in development
  conversation.setStage(STAGE);
  await pause(RESUME);
  assert.equal(rig.opens, 1);
  assert.equal(conversation.get().on, true);
  conversation.setStage(null); conversation.setStage(STAGE);   // the page registering again under a conversation that is on
  await pause(RESUME);
  assert.equal(rig.opens, 1);
  conversation.end();
});

test("a voice that finishes opening after the conversation was stopped is closed, not left talking", async () => {
  conversation.end();
  const late = { closed: 0 };
  let finish;
  fakes.openVoice = (o) => new Promise((yes) => {
    finish = () => { o.onState("live"); o.onCaption("agent", "Hello."); yes({ canHear: true, text() {}, cue() {}, note() {}, brief() {}, setMuted() {}, close() { late.closed++; } }); };
  });
  conversation.setStage(STAGE);
  const starting = conversation.start();
  conversation.stop();
  const rig = pretend();
  await conversation.start();   // a new one can begin straight away
  finish();
  await starting;
  assert.equal(late.closed, 1);
  assert.equal(rig.closed, 0);
  assert.equal(conversation.get().on, true);
  assert.deepEqual(conversation.get().turns, [], "and nothing it said reaches the new transcript");
  conversation.end();
  assert.equal(rig.closed, 1);
});

test("while the line is reopened the transcript stays, and the status can say so", async () => {
  const rig = await begin();
  conversation.setTalk("hold");
  rig.options.onCaption("agent", "Welcome to The Parker.", "a1");
  rig.options.onMoment("speaking");
  space();
  rig.options.onState("connecting");
  assert.equal(conversation.get().reconnecting, true);
  assert.equal(conversation.get().presence, "connecting");
  assert.equal(conversation.get().holding, false);
  assert.equal(conversation.get().on, true);
  assert.equal(conversation.get().turns.length, 1);
  rig.options.onState("live");
  assert.equal(conversation.get().reconnecting, false);
  assert.equal(conversation.get().presence, "listening");
  assert.equal(rig.mic, false, "a hold cut off by the drop is not left open on the new line");
  release();
  rig.options.onState("silent");
  assert.equal(conversation.get().reconnecting, false);
  assert.equal(conversation.get().voice, "silent");
  conversation.end();
});

test("sound that is waiting for a click is shown as such", async () => {
  const rig = await begin();
  rig.options.onSound(true);
  assert.equal(conversation.get().soundBlocked, true);
  rig.options.onSound(false);
  assert.equal(conversation.get().soundBlocked, false);
  rig.options.onSound(true);
  conversation.end();
  assert.equal(conversation.get().soundBlocked, false);
});

test("the talk mode is remembered across a reload", async () => {
  store.set("brace.talk", "hold");
  const again = await import(asUrl(`${conversationJs}\n// loaded a second time, as after a reload`));
  assert.equal(again.conversation.get().talk, "hold");
  store.delete("brace.talk");
});
