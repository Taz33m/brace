import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { FormEvent } from "react";
import { conversation, type Presence } from "../conversation";
import "./conversation.css";

const STATUS: Record<Presence, string> = {
  idle: "Ready to talk",
  connecting: "Connecting…",
  listening: "Listening",
  hearing: "Hearing you",
  thinking: "Thinking",
  speaking: "Speaking",
};

const CAMERA_NOTE = "Head nods and shakes are read on this computer. No video is stored or sent.";

/**
 * The conversation with Brace, in the top right corner of the big screen: who is speaking now, and a quiet
 * running transcript of both sides. Not a chat box: the way in is the voice. Typing is there for a room too
 * loud to be heard in, and opens with the "/" key.
 */
export function ConversationPanel({ ready, compact = false }: { ready: boolean; compact?: boolean }) {
  const [history, setHistory] = useState(false);
  const c = useSyncExternalStore(conversation.subscribe, conversation.get);
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const lines = useRef<HTMLOListElement>(null);
  const field = useRef<HTMLInputElement>(null);

  // Keep the newest words in view as they arrive.
  useEffect(() => { if (lines.current) lines.current.scrollTop = lines.current.scrollHeight; }, [c.turns]);
  useEffect(() => { if (typing) field.current?.focus(); }, [typing]);
  useEffect(() => {
    if (!c.on) { setTyping(false); return; }
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.key === "/" && !(el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) { e.preventDefault(); setTyping(true); }
      else if (e.key === "Escape") setTyping(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [c.on]);

  const send = (e: FormEvent) => {
    e.preventDefault();
    conversation.say(draft);
    setDraft("");
  };

  if (!c.on) {
    return (
      <aside className="talk talk-closed" aria-label="Conversation with Brace">
        {/* Shift-click starts without the microphone: Brace still speaks and is typed to. For a hall too loud to be heard in. */}
        <button type="button" className="talk-start" disabled={!ready} onClick={(e) => void conversation.start(e.shiftKey)}
                title={ready ? "Start talking with Brace" : "Two-way voice is not set up on this computer"}>
          <span className="talk-orb" aria-hidden="true"><i /><i /><i /><i /></span>
          {ready ? "Talk with Brace" : "Voice is not set up"}
        </button>
      </aside>
    );
  }

  const watching = c.gestures === "watching";
  const status = c.voice === "narration" ? "Reading the steps aloud" : c.voice === "silent" ? "Captions only"
    : c.muted && c.presence === "listening" ? (watching ? "Microphone off · nod or shake to answer" : "Microphone off")
    : watching && c.presence === "listening" ? "Listening · nod or shake to answer" : STATUS[c.presence];
  const showField = typing || !c.canHear;
  return (
    <aside className={compact && !history ? "talk talk-compact" : "talk"} data-presence={c.presence} aria-label="Conversation with Brace">
      <header>
        <span className="talk-orb" aria-hidden="true"><i /><i /><i /><i /></span>
        <strong className="talk-name-of">Brace</strong>
        <div className="talk-acts">
          {/* Only where a nod could be acted on: a live voice that can also hear. */}
          {c.canHear && c.voice === "live" && (
            <button type="button" className="talk-quiet talk-camera" aria-pressed={watching} onClick={() => conversation.toggleGestures()}
                    title={`${c.gestures === "unavailable" ? "The camera could not be used. Press to try again. " : ""}${CAMERA_NOTE}`}>
              Camera
            </button>
          )}
          {c.canHear && (
            <button type="button" className="talk-quiet" aria-pressed={c.muted} onClick={() => conversation.toggleMute()}>
              {c.muted ? "Unmute" : "Mute"}
            </button>
          )}
          {compact && (
            <button type="button" className="talk-quiet" aria-pressed={history} onClick={() => setHistory((h) => !h)}>History</button>
          )}
          <button type="button" className="talk-quiet" onClick={() => conversation.stop()}>End</button>
        </div>
        {/* On a row of its own, under the name and the buttons, so the longer wording fits on one line. */}
        <span className="talk-status" aria-live="polite">{status}</span>
      </header>

      <ol className="talk-lines" ref={lines} aria-live="polite">
        {c.turns.length === 0 && <li className="talk-hint">{c.canHear ? "Say what you want to know: “What should I fix first?”" : "No microphone was found. Type to Brace below."}</li>}
        {(compact && !history ? c.turns.slice(-1) : c.turns).map((t, i, shown) => (
          <li key={t.key} className={`talk-line ${t.who}${t.done ? "" : " live"}${t.gesture ? " gesture" : ""}`}>
            {(i === 0 || shown[i - 1].who !== t.who) && <span className="talk-name">{t.who === "agent" ? "Brace" : "You"}</span>}
            <p>{t.text || "…"}</p>
          </li>
        ))}
      </ol>

      {showField ? (
        <form className="talk-type" onSubmit={send}>
          <input ref={field} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Type to Brace" aria-label="Type to Brace" />
        </form>
      ) : (
        <p className="talk-foot">Just speak. <button type="button" className="talk-link" onClick={() => setTyping(true)}>Type instead</button></p>
      )}
    </aside>
  );
}
