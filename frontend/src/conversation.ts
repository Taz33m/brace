/**
 * The conversation with Brace on the big screen. It lives outside any one page, so it carries on when the
 * forecast step changes and the building page is rebuilt underneath it.
 *
 * A page that can be talked to registers a "stage": the tools the voice may use there and the notes it
 * should be working from. The panel in the corner reads the transcript from here.
 *
 * A yes-or-no question can also be answered with the head: a nod or a shake seen by the webcam is passed on
 * as a turn of its own, but only while Brace is simply listening. See offer() for the rules.
 */
import { startGestures, type GestureWatch } from "./gestures";
import { refusal, SPEECH_WINS_MS, type Gesture } from "./gestures-core";
import { openVoice, type CueKind, type Moment, type ToolRunner, type Voice, type VoiceState } from "./voice";

/** `gesture` marks a line that was a nod or a shake, not words. */
export interface Turn { key: string; who: "agent" | "you"; text: string; done: boolean; gesture?: boolean }
export type Presence = "idle" | "connecting" | "listening" | "hearing" | "thinking" | "speaking";

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
}

export interface Stage {
  /** Changes when what the voice should know changes, such as another forecast step. */
  key: string;
  sessionUrl: string;
  notesUrl: string;
  greeting: string;
  run: ToolRunner;
}

const KEEP = 60;
let state: ConversationState = { on: false, voice: "off", presence: "idle", turns: [], muted: false, canHear: true, gestures: "off" };
const listeners = new Set<() => void>();
let voice: Voice | null = null;
let stage: Stage | null = null;
let briefed: string | null = null;   // the stage the voice was last told about
let starting = false;
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

const gesturesPossible = () => state.on && state.voice === "live" && voice?.canHear === true;

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

  /** The page under the conversation. Null while there is none. */
  setStage(next: Stage | null) {
    stage = next;
    if (next && voice) void brief();
  },

  /** Must be called from a click or key press: the browser only opens the microphone and plays sound after one. */
  async start(listenOnly = false) {
    if (state.on || starting || !stage) return;
    starting = true;
    const opened = stage;
    heard = false;
    set({ on: true, presence: "connecting", turns: [], muted: false, gestures: "off" });
    try {
      voice = await openVoice({
        sessionUrl: opened.sessionUrl,
        // Tools always go to whichever page is under the conversation now, not the one it started on.
        run: (name, args) => stage?.run(name, args) ?? { ok: false, say: "That screen is not open." },
        onState: (v) => {
          // A voice that is no longer live cannot be answered with a nod, so the camera is let go.
          const lost = v !== "live" && v !== "connecting";
          if (lost) unwatchHead();
          set({ voice: v, presence: v === "connecting" ? "connecting" : state.presence, ...(lost ? { gestures: "off" as const } : {}) });
        },
        onCaption: (who, text, id) => line(who, text, id ?? `said-${++typed}`, true),
        onPartial: (who, text, id) => line(who, text, id, false),
        onMoment: (m) => {
          if (m === "hearing") heard = true; else if (m !== "listening") heard = false;
          // Talking over Brace cuts its sound off, which is reported as "listening" while the owner is still
          // mid-sentence. They are being heard, not waited for, so that report is passed over.
          if (m === "listening" && heard) return;
          set({ presence: PRESENCE[m] });
        },
        greeting: opened.greeting,
        listenOnly,
      }, true);
      briefed = opened.key;
      set({ canHear: voice.canHear, presence: state.presence === "connecting" ? "listening" : state.presence });
      if (stage && stage !== opened) void brief();
      // The camera is for answering a voice that can also hear: not for listen-only, and not when the steps are only read aloud.
      if (gesturesPossible()) void watchHead();
    } finally {
      starting = false;
    }
  },

  stop() {
    unwatchHead();
    voice?.close();
    voice = null; briefed = null;
    set({ on: false, voice: "off", presence: "idle", gestures: "off" });
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
  toggleMute() {
    const muted = !state.muted;
    voice?.setMuted(muted);
    set({ muted });
  },
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
