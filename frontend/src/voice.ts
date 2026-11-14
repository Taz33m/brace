/**
 * Brace's voice. A two-way realtime session when one can be opened; otherwise the browser's own
 * voice reads each line; otherwise silence, with the same lines still shown as text.
 *
 * The session is opened with a short-lived key issued by our server, so the real key never reaches the browser.
 */
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
}

const CALLS_URL = "https://api.openai.com/v1/realtime/calls";

function wait<T>(promise: Promise<T>, ms: number, what: string): Promise<T> {
  return Promise.race([promise, new Promise<T>((_, no) => window.setTimeout(() => no(new Error(`${what} timed out`)), ms))]);
}

async function microphone(skip: boolean): Promise<MediaStream | null> {
  if (skip || typeof navigator.mediaDevices?.getUserMedia !== "function") return null;
  try {
    // If nobody answers the microphone prompt, carry on without it instead of waiting for ever.
    return await wait(navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }), 25_000, "microphone permission");
  } catch (problem) {
    console.warn("No microphone; the agent will speak and can be typed to.", problem);
    return null;
  }
}

async function live(o: VoiceOptions): Promise<Voice> {
  const grant = await wait(fetch(o.sessionUrl, { method: "POST" }), 12_000, "voice session");
  if (!grant.ok) throw new Error(`voice session refused (${grant.status})`);
  const { value } = (await grant.json()) as { value: string };

  const mic = await microphone(o.listenOnly === true);
  const pc = new RTCPeerConnection();
  const speaker = document.createElement("audio");
  speaker.autoplay = true;
  speaker.setAttribute("playsinline", "");
  document.body.appendChild(speaker);
  pc.ontrack = (e) => { speaker.srcObject = e.streams[0]; void speaker.play().catch(() => {}); };
  if (mic) for (const track of mic.getTracks()) pc.addTrack(track, mic);
  else pc.addTransceiver("audio", { direction: "recvonly" });
  const channel = pc.createDataChannel("oai-events");

  let closed = false, busy = false, hearing = false, owed = false;
  let playing = false;   // the agent's voice is still coming out of the speaker, which lasts longer than the response that made it
  const findings: string[] = [];
  let latest: string | null = null;
  const partial = new Map<string, string>();   // words so far, by the line's id
  const send = (event: object) => { if (channel.readyState === "open") channel.send(JSON.stringify(event)); };
  const item = (role: "system" | "user", text: string) =>
    send({ type: "conversation.item.create", item: { type: "message", role, content: [{ type: "input_text", text }] } });
  const respond = () => { busy = true; o.onMoment?.("thinking"); send({ type: "response.create" }); };
  /** Say the next waiting line once the agent is neither talking nor being talked to. */
  const flush = () => {
    if (closed || busy || hearing) return;
    const next = findings.shift() ?? latest;
    if (next === latest) latest = null;
    if (next) { item("system", next); respond(); }
  };
  const close = () => {
    if (closed) return;
    closed = true;
    for (const track of mic?.getTracks() ?? []) track.stop();
    try { channel.close(); pc.close(); } catch { /* already gone */ }
    speaker.remove();
  };

  channel.onmessage = async (message) => {
    let e: { type: string; [key: string]: unknown };
    try { e = JSON.parse(message.data); } catch { return; }
    const id = String(e.item_id ?? "");
    if (e.type === "response.created") busy = true;
    else if (e.type === "input_audio_buffer.speech_started") { hearing = true; o.onMoment?.("hearing"); o.onPartial?.("you", "", id); }
    else if (e.type === "input_audio_buffer.speech_stopped") { hearing = false; o.onMoment?.("thinking"); }
    else if (e.type === "output_audio_buffer.started") { playing = true; o.onMoment?.("speaking"); }
    else if (e.type === "output_audio_buffer.stopped" || e.type === "output_audio_buffer.cleared") { playing = false; o.onMoment?.("listening"); }
    else if (e.type === "response.output_audio_transcript.delta" || e.type === "conversation.item.input_audio_transcription.delta") {
      const who = e.type.startsWith("response") ? "agent" : "you";
      const words = (partial.get(id) ?? "") + String(e.delta ?? "");
      partial.set(id, words);
      o.onPartial?.(who, words, id);
    } else if (e.type === "response.output_audio_transcript.done" || e.type === "response.audio_transcript.done") {
      partial.delete(id);
      if (typeof e.transcript === "string" && e.transcript.trim()) o.onCaption("agent", e.transcript.trim(), id);
    } else if (e.type === "conversation.item.input_audio_transcription.completed") {
      partial.delete(id);
      o.onCaption("you", typeof e.transcript === "string" ? e.transcript.trim() : "", id);
    } else if (e.type === "response.function_call_arguments.done") {
      // Run the tool now; the spoken follow-up is asked for once this response has finished.
      let result: unknown;
      try {
        const args = typeof e.arguments === "string" && e.arguments ? JSON.parse(e.arguments) : {};
        result = await o.run(String(e.name), args);
      } catch (problem) {
        result = { ok: false, say: "That did not work. Try again.", detail: problem instanceof Error ? problem.message : "unknown" };
      }
      send({ type: "conversation.item.create", item: { type: "function_call_output", call_id: e.call_id, output: JSON.stringify(result ?? {}) } });
      if (busy) owed = true; else respond();
    } else if (e.type === "response.done") {
      busy = false;
      // A response is finished well before its sound is; "listening" waits for the sound, so nothing answers a sentence still being spoken.
      if (owed) { owed = false; respond(); } else { if (!playing) o.onMoment?.("listening"); flush(); }
    }
  };
  pc.onconnectionstatechange = () => {
    if (!closed && (pc.connectionState === "failed" || pc.connectionState === "closed")) { close(); o.onState("silent"); }
  };

  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const answer = await wait(fetch(CALLS_URL, { method: "POST", headers: { Authorization: `Bearer ${value}`, "Content-Type": "application/sdp" }, body: offer.sdp }), 15_000, "voice connection");
    if (!answer.ok) throw new Error(`voice connection refused (${answer.status})`);
    await pc.setRemoteDescription({ type: "answer", sdp: await answer.text() });
    await wait(new Promise<void>((yes) => { if (channel.readyState === "open") yes(); else channel.onopen = () => yes(); }), 12_000, "voice channel");
  } catch (problem) {
    close();
    throw problem;
  }
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
      item("user", words.trim());
      if (busy) owed = true; else respond();
    },
    note(words) { if (!closed) item("system", words); },
    brief(instructions) { if (!closed) send({ type: "session.update", session: { type: "realtime", instructions } }); },
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
    text() { say("Two-way voice is not connected, so I can only read out the inspection."); },
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
