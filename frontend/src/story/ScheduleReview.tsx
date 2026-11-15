import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Schedule } from "./ScheduleTree";
import { reviewMoney, reviewQuestions, sourceLink } from "./schedule-review";
import "./schedule-review.css";

export function ScheduleReview({ data, captured, onClose, onContinue }: { data: Schedule; captured: string; onClose: () => void; onContinue?: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const document = useRef<HTMLElement>(null);
  const [status, setStatus] = useState("");
  const previousScroll = useRef(0);
  const continued = useRef(false);
  const continueAtBottom = (el: HTMLDialogElement) => {
    if (!onContinue || continued.current || el.scrollHeight - el.clientHeight - el.scrollTop > 4) return;
    continued.current = true;
    onContinue();
  };
  const units = useMemo(() => [...new Map(data.buildings.flatMap(b => b.units).map(u => [u.scan_id, u])).values()], [data]);
  const questions = useMemo(() => reviewQuestions(data), [data]);
  useEffect(() => {
    const previous = window.document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    window.document.body.classList.add("printing-schedule");
    return () => { window.document.body.classList.remove("printing-schedule"); previous?.focus(); };
  }, []);
  async function copy() {
    try { await navigator.clipboard.writeText(document.current?.innerText ?? ""); setStatus("Review document copied."); }
    catch { setStatus("Copy unavailable. Use Print / Save PDF instead."); }
  }
  return createPortal(<dialog data-lenis-prevent ref={dialog} className="sr-dialog" aria-labelledby="sr-title" onCancel={onClose}
    onScroll={e => {
      const el = e.currentTarget, down = el.scrollTop > previousScroll.current;
      previousScroll.current = el.scrollTop;
      if (down) continueAtBottom(el);
    }}
    onWheel={e => { if (e.deltaY > 0) continueAtBottom(e.currentTarget); }}
    onKeyDown={e => { if (["PageDown", "ArrowDown", "End"].includes(e.key)) continueAtBottom(e.currentTarget); }}
  >
    <nav className="sr-toolbar" aria-label="Review document actions"><button onClick={() => window.print()}>Print / Save PDF</button><button onClick={copy}>Copy document</button><span role="status">{status}</span><button onClick={onClose}>Close</button></nav>
    <article ref={document} className="sr-document">
      <header><p>BRACE · OWNER REVIEW DOCUMENT</p><h1 id="sr-title">Interior replacement-cost schedule</h1><h2>{data.property.name}</h2><p>{data.property.address}</p><p>Property {data.property.id} · Snapshot {captured} · Scan date: {data.property.scan_date ?? "unavailable"}</p></header>
      <section><h2>What we found</h2><p className="sr-amount">{reviewMoney(data.total)}</p><p>Estimated property rollup for the inventoried interior scope, using {data.property.homes} homes. {data.total.lines_priced ?? 0} of {data.total.lines ?? 0} scanned-home schedule lines have confirmed source pricing. Missing prices are excluded.</p><p>This home: {data.home.name} · {reviewMoney(data.home.total)}</p><p>{data.numbers.scans_read} scan(s) read · {data.numbers.rooms_read} rooms · {data.numbers.views_looked_at} views inspected · {data.numbers.items_named} items recorded.</p><p><strong>Hypothetical scope:</strong> {data.property.scenario}. This schedule does not establish that damage occurred, predict a loss, value the whole building, or determine insurance coverage.</p></section>
      <section><h2>What the owner should confirm</h2><ol>{questions.map((q,i)=><li key={i}>{q}</li>)}</ol></section>
      <section><h2>How the property total was calculated</h2><table><thead><tr><th>Floor plan</th><th>Homes</th><th>Per home</th><th>Subtotal</th><th>Basis</th></tr></thead><tbody>{data.kinds_of_home.map((k,i)=><tr key={i}><td>{k.name}</td><td>{k.homes}</td><td>{reviewMoney(k.per_home)}</td><td>{reviewMoney(k)}</td><td>{k.basis}</td></tr>)}</tbody></table><p>Counts and floor-plan mix come from the schedule's CoStar / Apartments.com records. Unscanned plans are extrapolated; they are not additional observations.</p></section>
      <section><h2>Room quantities and price evidence</h2>{!units.length && <p>The schedule did not include room-level evidence. Obtain the scanned-home breakdown before relying on this total.</p>}{units.map(unit=><div key={unit.scan_id}><h3>{unit.name}</h3><p>Matterport scan {unit.scan_id} · {unit.scan_date ?? "date unavailable"}</p>{unit.rooms.map((room,ri)=><section key={ri}><h4>{room.name} · {reviewMoney(room.total)}</h4><table><thead><tr><th>Item</th><th>Quantity</th><th>Unit price</th><th>Line total</th><th>Evidence</th></tr></thead><tbody>{room.items.map((line,i)=><tr key={i}><td>{line.what}</td><td>{line.quantity} {line.unit}</td><td>{reviewMoney({ low: line.price_low, high: line.price_high }, 2)}</td><td>{reviewMoney(line)}</td><td>{line.from}{line.seen && <p>{line.seen}</p>}{line.at && <p>View: {line.at.standpoint} · {line.at.direction}</p>}{line.match ? <><p><strong>{line.match.label}</strong> · Matched by appearance; not an identification. Product prices exclude delivery and fitting.</p>{line.match.candidates.map((candidate, ci) => <p key={ci}>{candidate.make} {candidate.model || candidate.name} · {reviewMoney({low: candidate.price, high: candidate.price}, 2)}<br />{sourceLink(candidate.url) ? <a href={sourceLink(candidate.url)} target="_blank" rel="noopener noreferrer">{candidate.url}</a> : "No usable product-source link."}</p>)}</> : sourceLink(line.source_url) ? <p><a href={sourceLink(line.source_url)} target="_blank" rel="noopener noreferrer">{line.source_url}</a></p> : <p>No usable price-source link.</p>}</td></tr>)}</tbody></table>{(room.left_out ?? []).length > 0 && <p>Left out by the agent: {room.left_out.map(x=>`${x.saw} (${x.why})`).join("; ")}</p>}</section>)}<p>Agent decisions: {unit.decisions?.merged ?? 0} duplicate sightings merged; {unit.decisions?.left_out ?? 0} items left out; {unit.decisions?.doubts ?? 0} unresolved questions.</p>{(unit.rechecks ?? []).map((r,i)=><p key={i}>Second look at {r.room_name}: {r.changed.length ? r.changed.join("; ") : "No recorded changes."}</p>)}</div>)}</section>
      <section><h2>Building allocation</h2><table><thead><tr><th>Building</th><th>Assumed homes</th><th>Allocated range</th><th>Exterior ordering</th></tr></thead><tbody>{data.buildings.map(b=><tr key={b.id}><td>{b.id}</td><td>{b.homes_assumed}</td><td>{reviewMoney(b.total)}</td><td>Rank {b.exposure_rank}; vegetation within 5 ft: {b.brush_within_5ft_percent == null ? "unknown" : `${b.brush_within_5ft_percent}%`}</td></tr>)}</tbody></table><p>Vexcel supplies the exterior context. Allocation by roof area and vegetation ordering do not establish actual unit locations or probability of fire.</p></section>
      <section><h2>Assumptions and exclusions</h2><ul>{data.assumptions.map((a,i)=><li key={i}>{a}</li>)}</ul><h3>Not counted</h3><ul>{data.not_counted.map(x=><li key={x}>{x}</li>)}</ul></section>
      <footer>Prepared from the schedule displayed when this document was opened. Subsequent room rechecks do not change this snapshot; close and reopen to capture an updated schedule. Review with your estimator or broker before use.</footer>
      {onContinue && <div className="sr-next"><p>Keep scrolling to return to the home.</p><button className="sr-continue" onClick={onContinue}>Return to the home →</button></div>}
    </article>
  </dialog>, window.document.body);
}
