/**
 * Request support: pick what kind of help, say what is needed, send once.
 *
 * - A request is not a booking: the note says so before sending.
 * - Collects only category + description (no names, phone numbers, medical details).
 * - One idempotency key per intended request; a retry of the same text reuses it.
 * - Never sends in the background: nothing goes out unless the person presses Send.
 */
import { useRef, useState, type ReactNode } from "react";
import type { SupportInput } from "../contract";
import { SUPPORT_CATEGORIES } from "../lib/status";
import { toResidentError, type ResidentError } from "../lib/errors";
import { useDictation } from "../lib/useDictation";
import { ActionBar, Choice, Message, ScreenHead } from "../ui";
import { IconAccess, IconChat, IconHousing, IconMic, IconOther, IconRetry, IconStop } from "../icons";
import type { SupportDraft, SupportFlowProps } from "./types";

const CATEGORY_ICON: Record<SupportInput["category"], ReactNode> = {
  housing: <IconHousing size={28} />,
  access: <IconAccess size={28} />,
  communication: <IconChat size={28} />,
  other: <IconOther size={28} />,
};

const PROMPT: Record<SupportInput["category"] | "none", { label: string; hint: string }> = {
  housing: { label: "Who needs somewhere to stay, and from when?", hint: "For example: two adults and a child, from tonight." },
  access: { label: "What do you need help getting into or around?", hint: "For example: the lift is out and I can't manage the stairs." },
  communication: { label: "What would make updates easier for you?", hint: "For example: updates in Spanish, or larger text." },
  other: { label: "What do you need?", hint: "A few words is enough." },
  none: { label: "What do you need?", hint: "A few words is enough." },
};

type Phase = { kind: "idle" } | { kind: "sending" } | { kind: "error"; error: ResidentError };

export function SupportFlow({ api, connection, draft, set_draft, keeper: sharedKeeper, on_submitted, on_expired }: SupportFlowProps) {
  const keeper = useRef(sharedKeeper);
  const pending = useRef(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [attempted, setAttempted] = useState(false);
  const categoryRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const edit = (update: (d: SupportDraft) => SupportDraft) => {
    set_draft(update);
    // An old error no longer describes what is on screen once the person changes it.
    setPhase((p) => (p.kind === "error" ? { kind: "idle" } : p));
  };

  const dictation = useDictation((text) =>
    edit((d) => ({ ...d, description: d.description.trim() ? `${d.description.trimEnd()} ${text}` : text })),
  );

  const description = draft.description.trim();
  const categoryMissing = attempted && !draft.category;
  const descriptionMissing = attempted && !description;
  const sending = phase.kind === "sending";
  const offline = connection === "offline";
  const prompt = PROMPT[draft.category ?? "none"];

  async function send() {
    if (pending.current || offline) return;
    setAttempted(true);
    if (!draft.category) {
      categoryRef.current?.querySelector<HTMLElement>("[role=radio]")?.focus();
      return;
    }
    if (!description) {
      textRef.current?.focus();
      return;
    }
    if (dictation.listening) dictation.stop();

    const input: SupportInput = { category: draft.category, description };
    const key = keeper.current.keyFor(input);
    pending.current = true;
    setPhase({ kind: "sending" });
    try {
      const receipt = await api.request_support(input, key);
      keeper.current.succeeded();
      pending.current = false;
      setPhase({ kind: "idle" });
      on_submitted(receipt);
    } catch (e) {
      pending.current = false;
      const error = toResidentError(e);
      if (error.kind === "expired") {
        on_expired();
        return;
      }
      setPhase({ kind: "error", error });
    }
  }

  const error = phase.kind === "error" ? phase.error : null;
  const canRetry = !!error && error.kind !== "invalid" && error.retryable && !offline;

  return (
    <>
      <main className="r-main has-actionbar" aria-busy={sending}>
        <ScreenHead
          title="Request support"
          lede="Ask the property team for help. They'll reply here, under My updates."
        />

        <div className="r-section">
          <p id="support-cat-label" className="r-label">What do you need help with?</p>
          <div
            ref={categoryRef}
            className="r-choices"
            role="radiogroup"
            aria-labelledby="support-cat-label"
            aria-describedby={categoryMissing ? "support-cat-error" : undefined}
            aria-invalid={categoryMissing || undefined}
          >
            {SUPPORT_CATEGORIES.map((c) => (
              <Choice
                key={c.value}
                role="radio"
                icon={CATEGORY_ICON[c.value]}
                title={c.label}
                sub={c.hint}
                selected={draft.category === c.value}
                onClick={() => edit((d) => ({ ...d, category: c.value }))}
              />
            ))}
          </div>
          {categoryMissing ? (
            <p id="support-cat-error" className="r-field-error">Choose what you need help with.</p>
          ) : null}
        </div>

        <div className="r-field">
          <label htmlFor="support-desc" className="r-label">{prompt.label}</label>
          <p id="support-desc-hint" className="r-hint">
            {prompt.hint} Please don't include phone numbers or medical details.
          </p>
          <textarea
            id="support-desc"
            ref={textRef}
            className="r-textarea"
            value={draft.description}
            onChange={(e) => {
              const value = e.target.value;
              edit((d) => ({ ...d, description: value }));
            }}
            aria-invalid={descriptionMissing || undefined}
            aria-describedby={`support-desc-hint${descriptionMissing ? " support-desc-error" : ""}`}
            rows={4}
          />
          {descriptionMissing ? (
            <p id="support-desc-error" className="r-field-error">Say what you need in a few words.</p>
          ) : null}
          {dictation.supported ? (
            <button
              type="button"
              className="r-btn r-dictate"
              onClick={dictation.listening ? dictation.stop : dictation.start}
              aria-pressed={dictation.listening}
              disabled={sending}
            >
              {dictation.listening ? <IconStop size={20} /> : <IconMic size={20} />}
              {dictation.listening ? "Stop listening" : "Speak instead of typing"}
            </button>
          ) : null}
          {dictation.error ? <p className="r-field-error">{dictation.error}</p> : null}
        </div>

        <Message tone="info">
          This sends a request to the property team. It isn't a booking or a reservation, and nothing is
          confirmed until they reply here.
        </Message>

        {error ? (
          <Message
            tone="bad"
            action={
              canRetry ? (
                <button type="button" className="r-btn" onClick={send} disabled={sending}>
                  <IconRetry size={20} /> Try again
                </button>
              ) : null
            }
          >
            {error.kind === "network"
              ? "Your request wasn't sent: no connection. What you wrote is still here. Try again when you have signal."
              : error.message}
          </Message>
        ) : null}

        {offline ? (
          <p id="support-offline" className="r-hint">
            You're offline. What you wrote is kept on this screen; send it when you have signal.
          </p>
        ) : null}
      </main>

      <ActionBar>
        <button
          type="button"
          className="r-btn primary"
          onClick={send}
          disabled={sending || offline}
          aria-busy={sending}
          aria-describedby={offline ? "support-offline" : undefined}
        >
          {sending ? "Sending…" : offline ? "Offline — can't send yet" : "Send request"}
        </button>
      </ActionBar>
    </>
  );
}
