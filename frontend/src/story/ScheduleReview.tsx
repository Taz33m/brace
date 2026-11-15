import { ConversationPanel } from "../components/ConversationPanel";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ScheduleDocument, type PaperProps } from "./ScheduleDocument";
import "./schedule-review.css";

export function ScheduleReview({ data, captured, onClose, aftermath = false, voiceReady = false }: PaperProps & { onClose: () => void; voiceReady?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null), document = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("");
  useEffect(() => {
    const previous = window.document.activeElement as HTMLElement | null;
    dialog.current?.showModal(); window.document.body.classList.add("printing-schedule");
    return () => { window.document.body.classList.remove("printing-schedule"); previous?.focus(); };
  }, []);
  async function copy() {
    try { await navigator.clipboard.writeText(document.current?.innerText ?? ""); setStatus("Review document copied."); }
    catch { setStatus("Copy unavailable. Use Print / Save PDF instead."); }
  }
  return createPortal(<dialog data-lenis-prevent ref={dialog} className="sr-dialog" aria-labelledby="sr-title" onCancel={onClose}>
    <nav className="sr-toolbar" aria-label="Review document actions"><button onClick={() => window.print()}>Print / Save PDF</button><button onClick={copy}>Copy document</button><span role="status">{status}</span><button onClick={onClose}>Close</button></nav>
    <div className="sr-conversation"><ConversationPanel ready={voiceReady} compact /></div>
    <div ref={document}><ScheduleDocument data={data} captured={captured} aftermath={aftermath} /></div>
  </dialog>, window.document.body);
}
