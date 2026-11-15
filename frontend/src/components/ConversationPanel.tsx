import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { FormEvent, MouseEvent } from "react";
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

/** A phone or tablet: there is no Space bar to hold, so hold mode gets a button to press. */
const touch = () => typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
/** A button clicked with the mouse lets go of the focus, so the next Space is a hold and not another press of the button. */
const letGo = (e: MouseEvent<HTMLButtonElement>) => { if (e.detail) e.currentTarget.blur(); };

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
  const [coarse] = useState(touch);
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
  const live = c.voice === "live" || c.reconnecting;
  const holdMode = c.talk === "hold" && c.canHear && live;
  const nod = watching ? " · nod or shake to answer" : "";
  const status = c.voice === "narration" ? "Live voice is not connected" : c.voice === "silent" ? "Captions only"
    : c.reconnecting ? "Reconnecting…"
    : c.soundBlocked ? (coarse ? "Tap once to hear Brace" : "Click once to hear Brace")
    : c.holding ? "Hearing you"
    : c.muted && c.presence === "listening" ? `Microphone off${nod}`
    : holdMode && c.presence === "listening" ? `${coarse ? "Hold to talk" : "Hold space to talk"}${nod}`
    : c.presence === "listening" ? `Listening${nod}` : STATUS[c.presence];
  const showField = typing || !c.canHear;
  return (
    <aside className={compact && !history ? "talk talk-compact" : "talk"} data-presence={c.holding ? "hearing" : c.presence} aria-label="Conversation with Brace">
      <header>
        <span className="talk-orb" aria-hidden="true"><i /><i /><i /><i /></span>
        <strong className="talk-name-of">Brace</strong>
        <div className="talk-acts">
          {/* Only where a nod could be acted on: a live voice that can also hear. */}
          {c.canHear && c.voice === "live" && conversation.nodsAllowed() && (
            <button type="button" className="talk-quiet talk-camera" aria-pressed={watching} onClick={(e) => { letGo(e); conversation.toggleGestures(); }}
                    title={`${c.gestures === "unavailable" ? "The camera could not be used. Press to try again. " : ""}${CAMERA_NOTE}`}>
              Camera
            </button>
          )}
          {/* For a loud room: the microphone stays off except while Space, or the button on a phone, is held. */}
          {c.canHear && live && (
            <button type="button" className="talk-quiet" aria-pressed={c.talk === "hold"} onClick={(e) => { letGo(e); conversation.toggleTalk(); }}
                    title={c.talk === "hold" ? "The microphone is on only while you hold. Press for an open microphone."
                      : "The microphone is always on. Press to talk only while you hold, for a loud room."}>
              {coarse ? "Hold to talk" : "Hold space"}
            </button>
          )}
          {c.canHear && (
            <button type="button" className="talk-quiet" aria-pressed={c.muted} onClick={(e) => { letGo(e); conversation.toggleMute(); }}>
              {c.muted ? "Unmute" : "Mute"}
            </button>
          )}
          {compact && (
            <button type="button" className="talk-quiet" aria-pressed={history} onClick={(e) => { letGo(e); setHistory((h) => !h); }}>History</button>
          )}
          {/* End forgets the conversation; a page that only unmounts calls stop(), and a reload then brings it back. */}
          <button type="button" className="talk-quiet" onClick={() => conversation.end()}>End</button>
        </div>
        {/* On a row of its own, under the name and the buttons, so the longer wording fits on one line. */}
        <span className="talk-status" aria-live="polite">{status}</span>
      </header>

      <ol className="talk-lines" ref={lines} aria-live="polite">
        {c.turns.length === 0 && <li className="talk-hint">{c.canHear ? (conversation.hint() ?? "Say what you want to know: “What should I fix first?”") : "No microphone was found. Type to Brace below."}</li>}
        {(compact && !history ? c.turns.slice(-1) : c.turns).map((t, i, shown) => (
          <li key={t.key} className={`talk-line ${t.who}${t.done ? "" : " live"}${t.gesture ? " gesture" : ""}`}>
            {(i === 0 || shown[i - 1].who !== t.who) && <span className="talk-name">{t.who === "agent" ? "Brace" : "You"}</span>}
            <p>{t.text || "…"}</p>
          </li>
        ))}
      </ol>

      {/* No Space bar on a phone: a round button to press and hold. Sliding off it, or the touch being taken away, lets go. */}
      {holdMode && coarse && !c.muted && (
        <button type="button" className="talk-hold" aria-pressed={c.holding} aria-label="Hold to talk" disabled={c.reconnecting}
                onPointerDown={() => conversation.hold(true)} onPointerUp={() => conversation.hold(false)}
                onPointerCancel={() => conversation.hold(false)} onPointerLeave={() => conversation.hold(false)}
                onContextMenu={(e) => e.preventDefault()}>
          {c.holding ? "Hearing you" : "Hold to talk"}
        </button>
      )}

      {showField ? (
        <form className="talk-type" onSubmit={send}>
          <input ref={field} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Type to Brace" aria-label="Type to Brace" />
        </form>
      ) : (
        <p className="talk-foot">{c.muted ? "The microphone is off." : !holdMode ? "Just speak." : coarse ? "Hold the button and speak." : "Hold space and speak."}{" "}
          <button type="button" className="talk-link" onClick={() => setTyping(true)}>Type instead</button></p>
      )}
    </aside>
  );
}
