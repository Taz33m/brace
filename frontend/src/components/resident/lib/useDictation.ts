/**
 * PLACEHOLDER — replaced by the mobile-hardening builder.
 * Contract for callers: optional speech-to-text into a text field. `supported` false hides the mic.
 */
export interface Dictation {
  supported: boolean;
  listening: boolean;
  error: string | null;
  start: () => void;
  stop: () => void;
}

export function useDictation(_onText: (text: string) => void): Dictation {
  return { supported: false, listening: false, error: null, start: () => {}, stop: () => {} };
}
