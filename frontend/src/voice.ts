/**
 * Brace's voice. A two-way realtime session when one can be opened; otherwise the browser's own
 * voice reads each line; otherwise silence, with the same lines still shown as text.
 *
 * The session is opened with a short-lived key issued by our server, so the real key never reaches the browser.
 */
import { ALREADY_RESPONDING, backoffMs, DISCONNECTED_MS, ending, fault, nextAttempt, OFFLINE_WAIT_MS, recall, rejoin, TOOL_MS, UNCONFIRMED_MS, type Said } from "./voice-core";

/** "connecting" after "live" means a dropped line is being reopened; "live" again means it is back. */
export type VoiceState = "off" | "connecting" | "live" | "narration" | "silent";
export type CueKind = "inspection" | "finding" | "say";
export type ToolRunner = (name: string, args: Record<string, unknown>) => Promise<unknown> | unknown;
/** What is happening in the conversation right now. */
export type Moment = "hearing" | "thinking" | "speaking" | "listening";

export interface Voice {
  /**
   * Something to say aloud. `inspection` is what the agent is doing now (only the newest waits);
   * `finding` is an action added to the plan (never dropped); `say` is a fixed sentence to speak as written.
   * `plain` is the wording used when there is no live session to phrase it.
   */
  cue(kind: CueKind, text: string, plain?: string): void;
  /** A typed turn from the person, for when speaking is not possible. */
  text(words: string): void;
  /** Something the agent should know but not answer, such as what is on screen now. */
  note(words: string): void;
  /** Replace what the agent knows, for example when the forecast step changes. */
  brief(instructions: string): void;
  setMuted(muted: boolean): void;
  /** False when there is no microphone: the agent can still speak and be typed to. */
  canHear: boolean;
  close(): void;
}

export interface VoiceOptions {
  sessionUrl: string;
  run: ToolRunner;
  onState: (state: VoiceState) => void;
  /** A finished line. `id` matches the partial lines that led up to it. */
  onCaption: (who: "agent" | "you", text: string, id?: string) => void;
  /** A line still being spoken or transcribed: the words so far. */
  onPartial?: (who: "agent" | "you", text: string, id: string) => void;
  onMoment?: (moment: Moment) => void;
  greeting?: string;
  /** Skip the microphone and connect to listen only. */
  listenOnly?: boolean;
  /** True when the browser would not play sound without a click; false once a click or key press has let it through. */
  onSound?: (blocked: boolean) => void;
}

const CALLS_URL = "https://api.openai.com/v1/realtime/calls";

function wait<T>(promise: Promise<T>, ms: number, what: string): Promise<T> {
  let timer = 0;
  const late = new Promise<T>((_, no) => { timer = window.setTimeout(() => no(new Error(`${what} timed out`)), ms); });
  return Promise.race([promise, late]).finally(() => window.clearTimeout(timer));   // the timer is not left running once the wait is over
}

declare global {
  interface Window { __braceMic?: () => MediaStream | Promise<MediaStream> }
}

async function microphone(skip: boolean): Promise<MediaStream | null> {
  if (skip) return null;
  // For tests, in development only: window.__braceMic returns the stream to use as the microphone, such as recorded speech.
  if (import.meta.env.DEV && typeof window.__braceMic === "function") {
    try {
      return await wait(Promise.resolve(window.__braceMic()), 25_000, "test microphone");
    } catch (problem) {
      console.warn("The test microphone could not be opened; the agent will speak and can be typed to.", problem);
      return null;
    }
  }
  if (typeof navigator.mediaDevices?.getUserMedia !== "function") return null;
  const asking = navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  try {
    // If nobody answers the microphone prompt, carry on without it instead of waiting for ever.
    return await wait(asking, 25_000, "microphone permission");
  } catch (problem) {
    // A prompt answered after we stopped waiting would leave a microphone open with nobody listening: let it go.
    asking.then((late) => { for (const track of late.getTracks()) track.stop(); }, () => {});
    console.warn("No microphone; the agent will speak and can be typed to.", problem);
    return null;
  }
}

async function live(o: VoiceOptions): Promise<Voice> {
  // The microphone and the speaker last for the whole conversation; the line (connection and channel) can be reopened under them.
  let mic: MediaStream | null = null;
  let pc: RTCPeerConnection | null = null, channel: RTCDataChannel | null = null;
  const speaker = document.createElement("audio");
  speaker.autoplay = true;
  speaker.setAttribute("playsinline", "");
  document.body.appendChild(speaker);
  let blocked = false;   // the browser refused to play sound because nothing has been clicked yet
  const GESTURES = ["pointerdown", "pointerup", "keydown", "click"] as const;
  const unblock = (on: boolean) => { for (const g of GESTURES) { if (on) window.addEventListener(g, play, true); else window.removeEventListener(g, play, true); } };
  /** Start the sound. A session opened with no click (after a reload) may be refused: it is kept, and the next click or key press tries again. */
  function play() {
    speaker.play().then(() => {
      if (!blocked) return;
      blocked = false; unblock(false); o.onSound?.(false);
    }, (problem: unknown) => {
      if (closed || blocked || (problem as { name?: string } | null)?.name !== "NotAllowedError") return;
      blocked = true; unblock(true); o.onSound?.(true);
    });
  }

  let closed = false, busy = false, hearing = false, owed = false;
  let playing = false;   // the agent's voice is still coming out of the speaker, which lasts longer than the response that made it
  let up = false;        // the line is open and can be sent on; false while it is being opened or reopened
  let since = 0;         // when the line last came up
  let tries = 0;         // reconnects made since the line last held steady
  let limbo = 0;         // timer: the connection reports "disconnected", which may yet mend itself
  let unanswered = false;   // the person has said something that no finished response has followed
  let typedOwed = false;    // the response that is owed is for a typed turn, which does not wait for the room to go quiet
  let running = 0;          // tools that have been called and have not answered yet
  let asked = 0;            // timer: a response has been asked for and the service has not confirmed it
  let retried = false;      // a failed response has already been asked for once more
  let briefing: string | null = null, onScreen: string | null = null;   // sent again after a reconnect: the new session starts without them
  const unsent: string[] = [];   // typed turns that arrived while the line was down
  const said: Said[] = [];       // the last finished lines, to remind the model with after a reconnect
  const findings: string[] = [];
  let latest: string | null = null;
  const partial = new Map<string, { who: "agent" | "you"; words: string }>();   // lines still being said, by the line's id
  const send = (event: object) => {
    try { if (channel?.readyState === "open") channel.send(JSON.stringify(event)); } catch { /* the line is going; the drop is dealt with where it is noticed */ }
  };
  const item = (role: "system" | "user", text: string) =>
    send({ type: "conversation.item.create", item: { type: "message", role, content: [{ type: "input_text", text }] } });
  const respond = () => {
    busy = true; o.onMoment?.("thinking"); send({ type: "response.create" });
    // Fix: a request the service never confirms (an error, a line gone quiet) used to leave `busy` set for ever, and nothing was said again.
    window.clearTimeout(asked);
    asked = window.setTimeout(() => {
      asked = 0;
      if (closed || !up) return;
      console.warn("The voice service did not confirm a response; carrying on without it.");
      busy = false; settle();
    }, UNCONFIRMED_MS);
  };
  /** A finished line: shown, and kept for the reminder after a reconnect. */
  const caption = (who: "agent" | "you", text: string, id?: string) => { recall(said, who, text); o.onCaption(who, text, id); };
  /** Say the next waiting line once the agent is neither talking nor being talked to. Lines wait while the line is down. */
  const flush = () => {
    // Fix: a line sent while a tool is still running would get its response before the tool's answer is in the conversation.
    if (closed || !up || busy || hearing || running > 0) return;
    const next = findings.shift() ?? latest;
    if (next === latest) latest = null;
    if (next) { item("system", next); respond(); }
  };
  /** A response or a tool has ended: ask for the response that is owed, or else say the next waiting line. */
  const settle = () => {
    if (closed || !up || busy || running > 0) return;
    // Fix: a tool's result used to be spoken over a person who had started talking; it now waits until they stop (a typed turn does not wait).
    if (owed && (!hearing || typedOwed)) { owed = typedOwed = false; respond(); return; }
    // A response is finished well before its sound is; "listening" waits for the sound, so nothing answers a sentence still being spoken.
    if (!playing) o.onMoment?.("listening");
    flush();
  };
  /** Let go of the line only; the conversation itself may carry on over a new one. */
  const shut = () => {
    window.clearTimeout(limbo); limbo = 0;
    const [oldPc, oldChannel] = [pc, channel];
    pc = null; channel = null;   // first, so that the closing below is not taken for a drop
    try { oldChannel?.close(); } catch { /* already gone */ }
    try { oldPc?.close(); } catch { /* already gone */ }
  };
  const close = () => {
    if (closed) return;
    closed = true; up = false;
    window.clearTimeout(asked); asked = 0;
    for (const track of mic?.getTracks() ?? []) track.stop();
    shut();
    unblock(false);
    speaker.srcObject = null;
    speaker.remove();
  };

  const hear = async (data: string, line: RTCDataChannel) => {
    let e: { type: string; [key: string]: unknown };
    try { e = JSON.parse(data); } catch { return; }
    const id = String(e.item_id ?? "");
    if (e.type === "response.created") {
      // Fix: a response the service starts by itself, after the person has spoken, already has the tool result or typed turn in front of it, so asking again would say it twice.
      if (!asked) owed = typedOwed = false;
      busy = true; window.clearTimeout(asked); asked = 0;
    }
    else if (e.type === "input_audio_buffer.speech_started") { hearing = true; o.onMoment?.("hearing"); partial.set(id, { who: "you", words: "" }); o.onPartial?.("you", "", id); }
    else if (e.type === "input_audio_buffer.speech_stopped") { hearing = false; unanswered = true; o.onMoment?.("thinking"); }
    else if (e.type === "output_audio_buffer.started") { playing = true; o.onMoment?.("speaking"); }
    else if (e.type === "output_audio_buffer.stopped" || e.type === "output_audio_buffer.cleared") { playing = false; o.onMoment?.("listening"); }
    else if (e.type === "response.output_audio_transcript.delta" || e.type === "conversation.item.input_audio_transcription.delta") {
      const who = e.type.startsWith("response") ? "agent" : "you";
      const words = (partial.get(id)?.words ?? "") + String(e.delta ?? "");
      partial.set(id, { who, words });
      o.onPartial?.(who, words, id);
    } else if (e.type === "response.output_audio_transcript.done" || e.type === "response.audio_transcript.done") {
      partial.delete(id);
      if (typeof e.transcript === "string" && e.transcript.trim()) caption("agent", e.transcript.trim(), id);
    } else if (e.type === "conversation.item.input_audio_transcription.completed") {
      partial.delete(id);
      caption("you", typeof e.transcript === "string" ? e.transcript.trim() : "", id);
    } else if (e.type === "conversation.item.input_audio_transcription.failed") {
      // Fix: speech that could not be written down left an empty "…" line in the transcript for good.
      partial.delete(id);
      o.onCaption("you", "", id);
    } else if (e.type === "response.function_call_arguments.done") {
      // Run the tool now; the spoken follow-up is asked for once this response, and any other tool it called, has finished.
      running++;
      let output: string;
      try {
        const args = typeof e.arguments === "string" && e.arguments ? JSON.parse(e.arguments) : {};
        // Fix: a tool that never answered left the conversation waiting for ever; after about 20 s it is reported as failed.
        output = JSON.stringify((await wait(Promise.resolve(o.run(String(e.name), args)), TOOL_MS, "the tool")) ?? {});
      } catch (problem) {
        output = JSON.stringify({ ok: false, say: "That did not work. Try again.", detail: problem instanceof Error ? problem.message : "unknown" });
      }
      if (closed || channel !== line) return;   // the line this call came over has gone, and its answer has nowhere to go
      running--;
      send({ type: "conversation.item.create", item: { type: "function_call_output", call_id: e.call_id, output } });
      // Fix: with two tools in one response, the follow-up used to be asked for when the first finished, before the second had answered.
      owed = true; settle();
    } else if (e.type === "response.done") {
      busy = false;
      const end = ending(e);
      if (end.status === "completed") { retried = false; if (!owed && running === 0) unanswered = false; }
      else if (end.status === "failed") {
        // Fix: a response that failed was treated as said. It is logged and asked for once more; a second failure is left alone.
        console.warn("A response from the voice service failed.", end.why ?? "");
        if (!retried) { retried = true; owed = true; }
      }
      // "cancelled" is the person talking over Brace, and "incomplete" a cut-off answer: neither is asked for again.
      settle();
    } else if (e.type === "error") {
      // Fix: errors from the service were ignored, and one that refused a response left `busy` set for ever.
      const { code, message } = fault(e);
      console.warn("The voice service reported an error.", code, message);
      if (code === ALREADY_RESPONDING) { owed = true; }   // ours lost to a response the service had started: ask again when that one is done
      else if (asked) { window.clearTimeout(asked); asked = 0; busy = false; settle(); }
    }
  };

  /** Open a line: a fresh key, a connection, the event channel. The first time it also asks for the microphone. */
  const connect = async (again: boolean) => {
    const grant = await wait(fetch(o.sessionUrl, { method: "POST" }), 12_000, "voice session");
    if (!grant.ok) throw new Error(`voice session refused (${grant.status})`);
    const { value } = (await grant.json()) as { value: string };

    if (!again) mic = await microphone(o.listenOnly === true);
    if (closed) throw new Error("the conversation was ended");
    const mine = new RTCPeerConnection();
    pc = mine;
    mine.ontrack = (e) => { speaker.srcObject = e.streams[0]; play(); };
    if (mic) for (const track of mic.getTracks()) mine.addTrack(track, mic);
    else mine.addTransceiver("audio", { direction: "recvonly" });
    const events = mine.createDataChannel("oai-events");
    channel = events;
    events.onmessage = (message) => { if (channel === events) void hear(message.data, events); };
    // The line can go three ways: the channel closes, the connection fails, or it stays "disconnected" too long to be a blip.
    events.onclose = () => { if (channel === events) dropped("the event channel closed"); };
    mine.onconnectionstatechange = () => {
      if (pc !== mine) return;
      window.clearTimeout(limbo); limbo = 0;
      if (mine.connectionState === "failed" || mine.connectionState === "closed") dropped(`the connection ${mine.connectionState}`);
      else if (mine.connectionState === "disconnected") limbo = window.setTimeout(() => { if (pc === mine) dropped("the connection stayed disconnected"); }, DISCONNECTED_MS);
    };

    try {
      const offer = await mine.createOffer();
      await mine.setLocalDescription(offer);
      const answer = await wait(fetch(CALLS_URL, { method: "POST", headers: { Authorization: `Bearer ${value}`, "Content-Type": "application/sdp" }, body: offer.sdp }), 15_000, "voice connection");
      if (!answer.ok) throw new Error(`voice connection refused (${answer.status})`);
      await mine.setRemoteDescription({ type: "answer", sdp: await answer.text() });
      await wait(new Promise<void>((yes) => { if (events.readyState === "open") yes(); else events.onopen = () => yes(); }), 12_000, "voice channel");
      if (closed || pc !== mine) throw new Error("the conversation was ended");
    } catch (problem) {
      if (pc === mine) shut();
      throw problem;
    }
  };

  /** The line went while the conversation was on: finish what was half said, then try to reopen it. */
  function dropped(why: string) {
    if (closed || !up) return;   // ended by the person, or already being reopened
    up = false;
    console.warn(`The voice line dropped (${why}).`);
    const held = Date.now() - since;
    shut();
    for (const [id, p] of partial) caption(p.who, p.words.trim(), id);
    partial.clear();
    busy = hearing = owed = typedOwed = playing = false;   // nothing is left waiting on a line that has gone
    running = 0; window.clearTimeout(asked); asked = 0;
    void reopen(held);
  }
  const pause = (ms: number) => new Promise<void>((yes) => window.setTimeout(yes, ms));
  /** With no network at all there is no point spending an attempt: wait for it to come back, though not for ever. */
  const online = () => new Promise<void>((yes) => {
    if (typeof navigator === "undefined" || navigator.onLine !== false) { yes(); return; }
    const done = () => { window.removeEventListener("online", done); window.clearTimeout(timer); yes(); };
    const timer = window.setTimeout(done, OFFLINE_WAIT_MS);
    window.addEventListener("online", done);
  });
  /** Up to two attempts, a little apart. The transcript, the waiting lines and the microphone are kept; if both fail the voice goes silent, as before. */
  async function reopen(held: number) {
    o.onState("connecting");
    for (let n = nextAttempt(tries, held); n !== null && !closed; n = nextAttempt(tries, 0)) {
      tries = n;
      await pause(backoffMs(n));
      await online();
      if (closed) return;
      try { await connect(true); } catch (problem) { console.warn(`Reopening the voice line failed (attempt ${n}).`, problem); continue; }
      rejoined();
      return;
    }
    if (closed) return;
    close();
    o.onState("silent");
  }
  /** The line is back on a new session, which knows nothing: tell it where things stood, and send what waited. */
  function rejoined() {
    up = true; since = Date.now();
    o.onState("live");
    if (briefing) send({ type: "session.update", session: { type: "realtime", instructions: briefing } });
    item("system", rejoin(said, unanswered));   // no second greeting: the model is told this is the same conversation
    if (onScreen) item("system", onScreen);
    for (const words of unsent.splice(0)) { recall(said, "you", words); item("user", words); }
    if (unanswered) respond(); else { o.onMoment?.("listening"); flush(); }
  }

  try {
    await connect(false);
  } catch (problem) {
    close();
    throw problem;
  }
  up = true; since = Date.now();
  if (o.greeting) { item("system", `[inspection] ${o.greeting}`); respond(); }

  return {
    canHear: mic !== null,
    cue(kind, text) {
      if (closed) return;
      if (kind === "inspection") latest = `[inspection] ${text}`;
      else findings.push(kind === "finding" ? `[finding] ${text}` : `Say exactly this and nothing else: "${text}"`);
      flush();
    },
    text(words) {
      if (closed || !words.trim()) return;
      unanswered = true;
      if (!up) { unsent.push(words.trim()); return; }   // typed while the line was down: sent as soon as it is back
      recall(said, "you", words.trim());
      item("user", words.trim());
      // A typed turn waits for a response in flight or a tool still running, never for a noisy room to go quiet.
      if (busy || running > 0) owed = typedOwed = true; else respond();
    },
    note(words) { if (closed) return; onScreen = words; if (up) item("system", words); },
    brief(instructions) { if (closed) return; briefing = instructions; if (up) send({ type: "session.update", session: { type: "realtime", instructions } }); },
    setMuted(muted) { for (const track of mic?.getAudioTracks() ?? []) track.enabled = !muted; },
    close,
  };
}

/** No live session: the browser's own voice, or text alone when the browser has none. */
function narrator(o: VoiceOptions): Voice {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
  let latest: string | null = null;
  const say = (text: string) => {
    o.onCaption("agent", text);
    if (!synth) return;
    const line = new SpeechSynthesisUtterance(text);
    line.rate = 1.05;
    line.onstart = () => o.onMoment?.("speaking");
    line.onend = () => { o.onMoment?.("listening"); if (latest) { const next = latest; latest = null; say(next); } };
    synth.speak(line);
  };
  o.onState(synth ? "narration" : "silent");
  return {
    canHear: false,
    cue(kind, text, plain) {
      const words = plain ?? text;
      // A step that arrives while a line is still being spoken waits; only the newest step is kept.
      if (kind === "inspection" && synth?.speaking) latest = words; else say(words);
    },
    text() { say("Two-way voice is not connected, so I cannot answer."); },
    note() { /* nothing to tell */ },
    brief() { /* nothing to update */ },
    setMuted() { /* there is no microphone to mute */ },
    close() { synth?.cancel(); },
  };
}

export async function openVoice(options: VoiceOptions, wantLive: boolean): Promise<Voice> {
  if (wantLive && typeof RTCPeerConnection !== "undefined") {
    options.onState("connecting");
    try {
      const voice = await live(options);
      options.onState("live");
      return voice;
    } catch (problem) {
      console.warn("Live voice unavailable; reading the steps aloud instead.", problem);
    }
  }
  return narrator(options);
}
