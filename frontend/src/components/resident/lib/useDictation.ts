/**
 * Optional speech-to-text into a text field, via the Web Speech API.
 *
 * `supported` is false when the browser has no SpeechRecognition (Firefox, most in-app webviews,
 * SSR/tests), and the caller hides the mic. Each final transcript chunk is passed to `onText`; the
 * caller appends it. `start()` must be called directly from a tap: iOS only grants the microphone
 * inside a user gesture, so recognition starts synchronously inside `start()`.
 *
 * The state machine lives in `createDictationController` (no React) so it can be unit tested.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export interface Dictation {
  supported: boolean;
  listening: boolean;
  error: string | null;
  start: () => void;
  stop: () => void;
}

// ---- Local typing for the Web Speech API (not in every TS DOM lib) ----

interface SpeechAlternativeLike {
  readonly transcript: string;
}
interface SpeechResultLike {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: SpeechAlternativeLike | undefined;
}
export interface SpeechResultEventLike {
  readonly resultIndex: number;
  readonly results: { readonly length: number; readonly [index: number]: SpeechResultLike | undefined };
}
export interface SpeechErrorEventLike {
  readonly error: string;
}
export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechResultEventLike) => void) | null;
  onerror: ((event: SpeechErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
export type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

/** The browser's SpeechRecognition constructor, or null (also null outside a browser). */
export function getSpeechRecognition(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const DICTATION_MESSAGES = {
  denied: "Microphone access is off. You can type instead.",
  noSpeech: "Didn't catch that. Try again or type.",
  network: "Voice typing needs a connection. You can type instead.",
  noMic: "No microphone was found. You can type instead.",
  generic: "Voice typing stopped. You can type instead.",
} as const;

/** Resident wording for a SpeechRecognition error code; null when it should not be shown. */
export function dictationErrorMessage(code: string): string | null {
  switch (code) {
    case "aborted":
      return null; // we (or the OS) cancelled it; not the resident's problem
    case "not-allowed":
    case "service-not-allowed":
      return DICTATION_MESSAGES.denied;
    case "no-speech":
      return DICTATION_MESSAGES.noSpeech;
    case "network":
      return DICTATION_MESSAGES.network;
    case "audio-capture":
      return DICTATION_MESSAGES.noMic;
    default:
      return DICTATION_MESSAGES.generic;
  }
}

export interface DictationState {
  listening: boolean;
  error: string | null;
}

export interface DictationController {
  start(): void;
  stop(): void;
  dispose(): void;
}

/** If a browser never fires `end` after stop() (seen on iOS), give up waiting after this long. */
export const STOP_GRACE_MS = 2500;

export function createDictationController(
  Ctor: SpeechRecognitionCtor,
  opts: { lang: string; onText: (text: string) => void; onChange: (state: DictationState) => void },
): DictationController {
  let rec: SpeechRecognitionLike | null = null;
  let state: DictationState = { listening: false, error: null };
  let stopTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  const set = (next: Partial<DictationState>) => {
    state = { ...state, ...next };
    if (!disposed) opts.onChange(state);
  };
  const clearTimer = () => {
    if (stopTimer !== null) clearTimeout(stopTimer);
    stopTimer = null;
  };
  const finish = (r: SpeechRecognitionLike) => {
    if (rec !== r) return;
    rec = null;
    clearTimer();
    set({ listening: false });
  };

  return {
    start() {
      if (disposed || rec) return; // already listening: no-op
      let r: SpeechRecognitionLike;
      try {
        r = new Ctor();
      } catch {
        set({ error: DICTATION_MESSAGES.generic });
        return;
      }
      r.lang = opts.lang;
      r.continuous = false;
      r.interimResults = false;
      r.maxAlternatives = 1;
      r.onresult = (event) => {
        if (disposed) return;
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (!result || !result.isFinal) continue;
          const text = result[0]?.transcript.trim();
          if (text) opts.onText(text);
        }
      };
      r.onerror = (event) => {
        if (rec !== r) return;
        const message = dictationErrorMessage(event.error);
        if (message) set({ error: message });
      };
      r.onend = () => finish(r);
      rec = r;
      set({ listening: true, error: null });
      try {
        r.start(); // synchronous, inside the tap handler
      } catch {
        rec = null;
        set({ listening: false, error: DICTATION_MESSAGES.generic });
      }
    },
    stop() {
      const r = rec;
      if (!r) return;
      try {
        r.stop(); // final results still arrive before `end`
      } catch {
        finish(r);
        return;
      }
      clearTimer();
      stopTimer = setTimeout(() => {
        if (rec !== r) return;
        try {
          r.abort();
        } catch {
          /* already gone */
        }
        finish(r);
      }, STOP_GRACE_MS);
    },
    dispose() {
      disposed = true;
      clearTimer();
      const r = rec;
      rec = null;
      if (!r) return;
      r.onresult = null;
      r.onerror = null;
      r.onend = null;
      try {
        r.abort();
      } catch {
        /* already gone */
      }
    },
  };
}

export function useDictation(onText: (text: string) => void): Dictation {
  const Ctor = useMemo(getSpeechRecognition, []);
  const [state, setState] = useState<DictationState>({ listening: false, error: null });
  const onTextRef = useRef(onText);
  const controllerRef = useRef<DictationController | null>(null);

  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  useEffect(() => {
    if (!Ctor) return;
    const lang = (typeof navigator !== "undefined" && navigator.language) || "en-US";
    const controller = createDictationController(Ctor, { lang, onText: (t) => onTextRef.current(t), onChange: setState });
    controllerRef.current = controller;
    return () => {
      controller.dispose(); // aborts any live recognition on unmount
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [Ctor]);

  const start = useCallback(() => controllerRef.current?.start(), []);
  const stop = useCallback(() => controllerRef.current?.stop(), []);

  return { supported: Ctor !== null, listening: state.listening, error: state.error, start, stop };
}
