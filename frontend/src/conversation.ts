/**
 * The conversation with Brace on the big screen. It lives outside any one page, so it carries on when the
 * forecast step changes and the building page is rebuilt underneath it.
 *
 * A page that can be talked to registers a "stage": the tools the voice may use there and the notes it
 * should be working from. The panel in the corner reads the transcript from here.
 *
 * A yes-or-no question can also be answered with the head: a nod or a shake seen by the webcam is passed on
 * as a turn of its own, but only while Brace is simply listening. See offer() for the rules.
 *
 * In a loud room the microphone can be kept off except while Space is held ("hold" mode). A conversation that
 * was on is remembered for the life of the tab, so a reload brings it back; only the End button forgets it.
 */
import { startGestures, type GestureWatch } from "./gestures";
import { refusal, SPEECH_WINS_MS, type Gesture } from "./gestures-core";
import { openVoice, type CueKind, type Moment, type ToolRunner, type Voice, type VoiceState } from "./voice";

/** `gesture` marks a line that was a nod or a shake, not words. */
export interface Turn { key: string; who: "agent" | "you"; text: string; done: boolean; gesture?: boolean }
export type Presence = "idle" | "connecting" | "listening" | "hearing" | "thinking" | "speaking";
/** "open": the microphone listens all the time. "hold": it is off except while Space, or the button on a phone, is held. */
export type TalkMode = "open" | "hold";

export interface ConversationState {
  on: boolean;
  voice: VoiceState;
  presence: Presence;
  turns: Turn[];
  muted: boolean;
  /** False when there is no microphone, so the only way to reply is to type. */
  canHear: boolean;
  /** Whether the webcam is being watched for nods and shakes. "unavailable": it was refused or could not be read. */
  gestures: "off" | "watching" | "unavailable";
  /** How the microphone is used. Kept across conversations and reloads. */
  talk: TalkMode;
  /** The microphone is being held open right now. Only ever true in hold mode, and never while muted. */
  holding: boolean;
  /** The line dropped and is being reopened. The transcript stays as it was. */
  reconnecting: boolean;
  /** The browser will not play Brace's voice until the page is clicked or a key is pressed once, as after a reload. */
  soundBlocked: boolean;
}

export interface Stage {
  /** Changes when what the voice should know changes, such as another forecast step. */
  key: string;
  sessionUrl: string;
  notesUrl: string;
  greeting: string;
  run: ToolRunner;
  /** False where nothing on the page is answered yes or no: the camera is then never opened for nods. */
  nods?: boolean;
  /** What to suggest saying on this page, shown before anything has been said. */
  hint?: string;
}

const KEEP = 60;
/** Space must stay down this long in open mode before it counts as a hold; a tap changes nothing. */
const HOLD_AFTER_MS = 300;
/** The microphone stays open this long after a hold is let go, so the end of the last word is not cut off. */
const RELEASE_MS = 200;
/** A remembered conversation is brought back this long after a page registers, so a page that mounts twice opens one session. */
const RESUME_AFTER_MS = 50;

/** Remembered in sessionStorage, so for this tab only. "talk" or "listen-only" while a conversation should be on; absent once the owner ends it. */
const RESUME_KEY = "brace.conversation";
/** "open" or "hold". */
const TALK_KEY = "brace.talk";
function stored(key: string): string | null {
  try { return window.sessionStorage.getItem(key); } catch { return null; }   // storage can be blocked, or absent
}
function store(key: string, value: string | null) {
  try { if (value === null) window.sessionStorage.removeItem(key); else window.sessionStorage.setItem(key, value); } catch { /* not remembered */ }
}

let state: ConversationState = {
  on: false, voice: "off", presence: "idle", turns: [], muted: false, canHear: true, gestures: "off",
  talk: stored(TALK_KEY) === "hold" ? "hold" : "open", holding: false, reconnecting: false, soundBlocked: false,
};
const listeners = new Set<() => void>();
let voice: Voice | null = null;
let stage: Stage | null = null;
let briefed: string | null = null;   // the stage the voice was last told about
let starting = false;
let asks = 0;                        // goes up whenever a conversation is started or stopped, so one that finishes opening late knows it is stale
let resuming = 0;                    // timer: a conversation remembered from before a reload is about to be brought back
let chose = false;                   // the owner picked a talk mode with the button, so Space no longer switches it for them
let tail = 0;                        // timer: the microphone stays open a moment after a hold is let go
let offered = 0;                     // timer: Space is down in open mode; if it is still down when this fires, hold mode begins
let keys = false;                    // the key listeners are attached
let typed = 0;
let heard = false;                   // the owner is mid-sentence: from "hearing" until their turn ends
let camera: GestureWatch | null = null;
let cameraAsks = 0;                  // goes up whenever the camera is started or let go, so a start that finishes late knows it is stale
let cameraOpening = false;
let waiting: { timer: number; settle: (outcome: string) => void } | null = null;   // a gesture seen but not yet delivered

const set = (patch: Partial<ConversationState>) => {
  state = { ...state, ...patch };
  // Speech wins: a gesture still waiting is dropped the moment Brace is no longer simply listening.
  const why = waiting && refusal(state);
  if (why) drop(why);
  for (const l of listeners) l();
};

/** Add a line, or change the one already shown under the same key. An empty finished line is removed. */
function line(who: Turn["who"], text: string, key: string, done: boolean, gesture = false) {
  const at = state.turns.findIndex((t) => t.key === key);
  if (done && !text) { if (at >= 0) set({ turns: state.turns.filter((_, i) => i !== at) }); return; }
  const next: Turn = gesture ? { key, who, text, done, gesture } : { key, who, text, done };
  set({ turns: at >= 0 ? state.turns.map((t, i) => (i === at ? next : t)) : [...state.turns, next].slice(-KEEP) });
}

const PRESENCE: Record<Moment, Presence> = { hearing: "hearing", thinking: "thinking", speaking: "speaking", listening: "listening" };

/** How a gesture reads in the transcript, and what the voice is told. */
const GESTURE: Record<Gesture, { shown: string; told: string }> = {
  nod: { shown: "Nodded: yes", told: "[gesture] The owner nodded: yes." },
  shake: { shown: "Shook head: no", told: "[gesture] The owner shook their head: no." },
};

function drop(why: string) {
  if (!waiting) return;
  window.clearTimeout(waiting.timer);
  const { settle } = waiting;
  waiting = null;
  settle(`dropped: ${why}`);
}

/**
 * A nod or a shake, from the camera or from the test hook. Resolves to what became of it.
 *
 * It must never interrupt Brace, so it is taken only while a live conversation is simply listening; in any
 * other state it is dropped, not kept for later. Speech wins over the camera, so even then it waits a moment:
 * if the owner starts to speak, or Brace does, before the wait is over, it is dropped.
 */
function offer(gesture: Gesture): Promise<string> {
  const why = refusal(state);
  if (why) return Promise.resolve(`dropped: ${why}`);
  if (waiting) return Promise.resolve("dropped: another gesture is waiting");
  return new Promise((settle) => {
    const timer = window.setTimeout(() => {
      waiting = null;
      // set() drops a waiting gesture on any change that rules it out; this is the same check once more, at the last moment.
      const late = refusal(state) ?? (voice ? null : "no conversation");
      if (late || !voice) { settle(`dropped: ${late}`); return; }
      line("you", GESTURE[gesture].shown, `gesture-${++typed}`, true, true);
      voice.text(GESTURE[gesture].told);
      settle("delivered");
    }, SPEECH_WINS_MS);
    waiting = { timer, settle };
  });
}

/** Start watching the webcam. A refused camera or a model that will not load leaves the conversation as it was. */
async function watchHead() {
  if (camera || cameraOpening) return;
  const mine = ++cameraAsks;
  cameraOpening = true;
  // The camera looks only while a gesture could be acted on: the same test that decides whether one is taken.
  const got = await startGestures({ eligible: () => refusal(state) === null, onGesture: (g) => void offer(g) });
  if (mine !== cameraAsks) { got?.stop(); return; }   // the conversation ended, or the camera was switched off, while it was opening
  cameraOpening = false;
  camera = got;
  set({ gestures: got ? "watching" : "unavailable" });
}

/** Let go of the camera, and forget a gesture that had not been delivered yet. */
function unwatchHead() {
  cameraAsks++;
  cameraOpening = false;
  camera?.stop();
  camera = null;
  drop("camera off");
}

const gesturesPossible = () => state.on && state.voice === "live" && voice?.canHear === true && stage?.nods !== false;

/** A live voice with a microphone: the only time there is one to open and close. */
const canTalk = () => state.on && state.voice === "live" && state.canHear;
/** Mute wins over everything; otherwise the microphone is on in open mode, while held, and for a moment after. */
const micOpen = () => !state.muted && (state.talk === "open" || state.holding || tail !== 0);
const applyMic = () => voice?.setMuted(!micOpen());

function switchTalk(mode: TalkMode) {
  if (mode === state.talk) return;
  window.clearTimeout(tail); tail = 0;
  store(TALK_KEY, mode);
  set({ talk: mode, holding: false });
  applyMic();
}

/** Open the microphone for as long as the hold lasts. Ignored outside hold mode, while muted, and when nothing can hear. */
function press(on: boolean) {
  if (on) {
    if (!canTalk() || state.talk !== "hold" || state.muted || state.holding) return;
    window.clearTimeout(tail); tail = 0;
    set({ holding: true });
  } else {
    if (!state.holding) return;
    window.clearTimeout(tail);
    tail = window.setTimeout(() => { tail = 0; applyMic(); }, RELEASE_MS);
    set({ holding: false });
  }
  applyMic();
}

const isSpace = (e: KeyboardEvent) => e.code === "Space" || e.key === " ";
/** Space typed into a field, or pressing a focused button, is not a hold. */
function elsewhere(target: EventTarget | null): boolean {
  const el = target as { tagName?: string; isContentEditable?: boolean } | null;
  return !!el && (/^(INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(el.tagName ?? "") || el.isContentEditable === true);
}
function letGo() {
  window.clearTimeout(offered); offered = 0;
  press(false);
}
function onKeyDown(e: KeyboardEvent) {
  if (!isSpace(e) || e.metaKey || e.ctrlKey || e.altKey || elsewhere(e.target) || !canTalk()) return;
  if (state.talk === "hold") {
    e.preventDefault();   // or the page would scroll under the conversation
    if (!e.repeat) press(true);
    return;
  }
  // Open mode: Space held down (not tapped) is taken as wanting hold mode, unless the owner chose open with the button.
  if (chose) return;
  e.preventDefault();
  if (e.repeat || offered) return;
  offered = window.setTimeout(() => {
    offered = 0;
    if (!canTalk() || state.talk !== "open" || chose) return;
    switchTalk("hold");
    press(true);
  }, HOLD_AFTER_MS);
}
function onKeyUp(e: KeyboardEvent) { if (isSpace(e)) letGo(); }
/** The keys are listened for only while a conversation is on. A window that loses focus never sends the key coming up, so that lets go too. */
function listen(on: boolean) {
  if (on === keys || typeof window.addEventListener !== "function") return;
  keys = on;
  if (on) { window.addEventListener("keydown", onKeyDown); window.addEventListener("keyup", onKeyUp); window.addEventListener("blur", letGo); }
  else { window.removeEventListener("keydown", onKeyDown); window.removeEventListener("keyup", onKeyUp); window.removeEventListener("blur", letGo); }
}

/** Bring back a conversation that was on before a reload, once the page under it has settled. */
function resumeSoon() {
  if (resuming || state.on || starting || !stored(RESUME_KEY)) return;
  // Not at once: in development React mounts a page, unmounts it and mounts it again, and only the last mount should open a session.
  resuming = window.setTimeout(() => {
    resuming = 0;
    const how = stored(RESUME_KEY);
    if (how && stage && !state.on && !starting) void conversation.start(how === "listen-only");
  }, RESUME_AFTER_MS);
}

/** Tell a conversation that is already under way about the page it is now over. */
async function brief() {
  if (!voice || !stage || briefed === stage.key) return;
  const wanted = stage;
  try {
    const { instructions } = (await fetch(wanted.notesUrl).then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })) as { instructions: string };
    if (voice && stage === wanted) { voice.brief(instructions); briefed = wanted.key; }
  } catch { /* the old notes stay in force; the next change tries again */ }
}

export const conversation = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  get: () => state,
  /** Whether the page under the conversation takes nods and shakes at all. */
  nodsAllowed: () => stage?.nods !== false,
  hint: () => stage?.hint ?? null,

  /** The page under the conversation. Null while there is none. */
  setStage(next: Stage | null) {
    stage = next;
    if (!next) { window.clearTimeout(resuming); resuming = 0; return; }
    if (voice) void brief(); else resumeSoon();
  },

  /**
   * Best called from a click or key press: the browser only plays sound freely after one. A conversation brought
   * back after a reload has had none, so its sound may wait for a click (see `soundBlocked`).
   */
  async start(listenOnly = false) {
    if (state.on || starting || !stage) return;
    starting = true;
    const mine = ++asks;
    const opened = stage;
    heard = false; chose = false;
    let wasLive = false;
    store(RESUME_KEY, listenOnly ? "listen-only" : "talk");
    listen(true);
    set({ on: true, presence: "connecting", turns: [], muted: false, gestures: "off", holding: false, reconnecting: false, soundBlocked: false });
    try {
      const got = await openVoice({
        sessionUrl: opened.sessionUrl,
        // Tools always go to whichever page is under the conversation now, not the one it started on.
        run: (name, args) => stage?.run(name, args) ?? { ok: false, say: "That screen is not open." },
        onState: (v) => {
          if (mine !== asks) return;   // from a conversation that has been ended since
          // A voice that is no longer live cannot be answered with a nod, so the camera is let go.
          const lost = v !== "live" && v !== "connecting";
          if (lost) unwatchHead();
          // "connecting" after the voice has been live is the line being reopened; "live" after that is the line back.
          const back = v === "live" && state.reconnecting;
          if (v === "live") wasLive = true;
          if (back) heard = false;
          set({
            voice: v, presence: v === "connecting" ? "connecting" : back ? "listening" : state.presence,
            reconnecting: v === "connecting" && wasLive,
            ...(v === "live" ? {} : { holding: false }), ...(lost ? { gestures: "off" as const } : {}),
          });
          if (back) applyMic();   // the same microphone is on the new line; a hold cut off by the drop is not left open
        },
        onSound: (blocked) => { if (mine === asks) set({ soundBlocked: blocked }); },
        onCaption: (who, text, id) => { if (mine === asks) line(who, text, id ?? `said-${++typed}`, true); },
        onPartial: (who, text, id) => { if (mine === asks) line(who, text, id, false); },
        onMoment: (m) => {
          if (mine !== asks) return;
          if (m === "hearing") heard = true; else if (m !== "listening") heard = false;
          // Talking over Brace cuts its sound off, which is reported as "listening" while the owner is still
          // mid-sentence. They are being heard, not waited for, so that report is passed over.
          if (m === "listening" && heard) return;
          set({ presence: PRESENCE[m] });
        },
        greeting: opened.greeting,
        listenOnly,
      }, true);
      if (mine !== asks) { got.close(); return; }   // ended while it was opening: it must not be left talking to nobody
      voice = got;
      briefed = opened.key;
      set({ canHear: voice.canHear, presence: state.presence === "connecting" ? "listening" : state.presence });
      applyMic();   // in hold mode the microphone starts off
      if (stage && stage !== opened) void brief();
      // The camera is for answering a voice that can also hear: not for listen-only, and not when the steps are only read aloud.
      if (gesturesPossible()) void watchHead();
    } finally {
      if (mine === asks) starting = false;
    }
  },

  /** Close the conversation because its page is going away. It is still remembered, so the next page, or a reload, brings it back. */
  stop() {
    asks++; starting = false;
    unwatchHead();
    window.clearTimeout(tail); tail = 0;
    window.clearTimeout(offered); offered = 0;
    listen(false);
    voice?.close();
    voice = null; briefed = null;
    set({ on: false, voice: "off", presence: "idle", gestures: "off", holding: false, reconnecting: false, soundBlocked: false });
  },

  /** The owner ends the conversation: close it and forget it, so a reload does not bring it back. For the End button. */
  end() {
    store(RESUME_KEY, null);
    conversation.stop();
  },

  /** Something the agent is doing or has found, to be said aloud. Ignored when no conversation is on. */
  cue(kind: CueKind, text: string, plain?: string) { voice?.cue(kind, text, plain); },
  /** What the owner is looking at now, so "this one" means something. */
  note(text: string) { voice?.note(`[on screen] ${text}`); },
  /** A typed turn, for a room too loud to be heard in or a computer with no microphone. */
  say(text: string) {
    const words = text.trim();
    if (!voice || !words) return;
    line("you", words, `typed-${++typed}`, true);
    voice.text(words);
  },
  /** Mute wins over a hold: while muted the microphone is never on. */
  toggleMute() {
    const muted = !state.muted;
    if (muted) { window.clearTimeout(tail); tail = 0; }
    set(muted ? { muted, holding: false } : { muted });
    applyMic();
  },
  /** Choose how the microphone is used. Once chosen here, Space no longer switches the mode by itself in this conversation. */
  setTalk(mode: TalkMode) {
    chose = true;
    window.clearTimeout(offered); offered = 0;
    switchTalk(mode);
  },
  toggleTalk() { conversation.setTalk(state.talk === "hold" ? "open" : "hold"); },
  /** Press and hold, for a button on a phone: true while it is down. Space does the same on a keyboard. */
  hold(on: boolean) { press(on); },
  /** Turn head gestures off, which lets go of the camera, or on again. After a refusal this asks once more. */
  toggleGestures() {
    if (camera || cameraOpening) { unwatchHead(); set({ gestures: "off" }); }
    else if (gesturesPossible()) void watchHead();
  },
};

declare global {
  interface Window { __braceGesture?: (gesture: Gesture) => Promise<string> }
}
// For checking the rules without a camera, in development only: await __braceGesture("nod") in the console.
// It goes through offer(), exactly as a gesture from the camera does, and resolves to what became of it.
if (import.meta.env.DEV && typeof window !== "undefined") {
  window.__braceGesture = (gesture) => (gesture === "nod" || gesture === "shake" ? offer(gesture) : Promise.resolve("dropped: not a gesture"));
}
