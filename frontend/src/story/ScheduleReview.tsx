import { ConversationPanel } from "../components/ConversationPanel";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Schedule } from "./ScheduleTree";
import { reviewMoney, reviewQuestions, sourceLink } from "./schedule-review";
import "./schedule-review.css";

export function ScheduleReview({ data, captured, onClose, aftermath = false, voiceReady = false }: { data: Schedule; captured: string; onClose: () => void; aftermath?: boolean; voiceReady?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const document = useRef<HTMLElement>(null);
  const [status, setStatus] = useState("");
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
  return createPortal(<dialog data-lenis-prevent ref={dialog} className="sr-dialog" aria-labelledby="sr-title" onCancel={onClose}>
    <nav className="sr-toolbar" aria-label="Review document actions"><button onClick={() => window.print()}>Print / Save PDF</button><button onClick={copy}>Copy document</button><span role="status">{status}</span><button onClick={onClose}>Close</button></nav>
    <div className="sr-conversation"><ConversationPanel ready={voiceReady} compact /></div>
    <article ref={document} className="sr-document">
      <header><p>BRACE · OWNER REVIEW DOCUMENT</p><h1 id="sr-title">{aftermath ? "After-fire recovery file" : "Interior replacement-cost schedule"}</h1><h2>{data.property.name}</h2><p>{data.property.address}</p><p>Property {data.property.id} · Snapshot {captured} · Scan date: {data.property.scan_date ?? "unavailable"}</p></header>
      {aftermath && <section className="sr-aftermath">
        <h2>The aftermath scenario</h2>
        <p>A hypothetical wildfire affects all {data.buildings.length} buildings in the illustrated community. The estimate covers the {data.property.homes} homes described by the listing and the inventoried owner-owned interior scope, assuming total loss of that scope. It is not an observed loss assessment.</p>
        <div className="sr-aftermath-views"><figure><img src="/aftermath/verdugo/fire.png" alt="Generated kitchen fire aftermath panorama" /><figcaption>Kitchen · AI-generated scenario</figcaption></figure><figure><img src="/aftermath/verdugo/bathroom-fire.png" alt="Generated bathroom fire aftermath panorama" /><figcaption>Bathroom · AI-generated scenario</figcaption></figure></div>
        <p>The generated views illustrate fire damage and removed contents. They do not establish which items were damaged or change the measured quantities and price evidence below.</p>
        <h3>Recovery planning basis</h3>
        <p>Interior replacement allowance: {reviewMoney(data.total)}. {data.lost_rent_per_month ? `Asking-rent exposure per month if all listed homes are unavailable: ${reviewMoney(data.lost_rent_per_month)}. This is not actual lost rent; verify leases, occupancy and downtime.` : "Actual rent interruption and recovery duration remain unverified."}</p>
        <ol><li>Obtain an on-site damage assessment and qualified re-entry clearance before interior work.</li><li>Record affected rooms and items against the original home inventory; confirm which can be repaired or salvaged.</li><li>Obtain contractor quotes that separate materials, labor, debris removal and smoke remediation. Product prices alone exclude delivery and fitting.</li><li>Confirm unavailable units and recovery duration with the owner; prepare resident relocation and return plans.</li></ol>
        <p>Pending: verified damage extent, structural condition, remediation costs, actual rent interruption, contractor schedule and insurance determination. None is established by this visualization.</p>
      </section>}
      <section><h2>What we found</h2><p className="sr-amount">{reviewMoney(data.total)}</p><p>Estimated property rollup for the inventoried interior scope, using {data.property.homes} homes. {data.total.lines_priced ?? 0} of {data.total.lines ?? 0} scanned-home schedule lines have confirmed source pricing. Missing prices are excluded.</p><p>This home: {data.home.name} · {reviewMoney(data.home.total)}</p><p>{data.numbers.scans_read} scan(s) read · {data.numbers.rooms_read} rooms · {data.numbers.views_looked_at} views inspected · {data.numbers.items_named} items recorded.</p><p><strong>Hypothetical scope:</strong> {data.property.scenario}. This schedule does not establish that damage occurred, predict a loss, value the whole building, or determine insurance coverage.</p></section>
      <section><h2>What the owner should confirm</h2><ol>{questions.map((q,i)=><li key={i}>{q}</li>)}</ol></section>
      <section><h2>How the property total was calculated</h2><table><thead><tr><th>Floor plan</th><th>Homes</th><th>Per home</th><th>Subtotal</th><th>Basis</th></tr></thead><tbody>{data.kinds_of_home.map((k,i)=><tr key={i}><td>{k.name}</td><td>{k.homes}</td><td>{reviewMoney(k.per_home)}</td><td>{reviewMoney(k)}</td><td>{k.basis}</td></tr>)}</tbody></table><p>Counts and floor-plan mix come from the schedule's CoStar / Apartments.com records. Unscanned plans are extrapolated; they are not additional observations.</p></section>
      <section><h2>Room quantities and price evidence</h2>{!units.length && <p>The schedule did not include room-level evidence. Obtain the scanned-home breakdown before relying on this total.</p>}{units.map(unit=><div key={unit.scan_id}><h3>{unit.name}</h3><p>Matterport scan {unit.scan_id} · {unit.scan_date ?? "date unavailable"}</p>{unit.rooms.map((room,ri)=><section key={ri}><h4>{room.name} · {reviewMoney(room.total)}</h4><table><thead><tr><th>Item</th><th>Quantity</th><th>Unit price</th><th>Line total</th><th>Evidence</th></tr></thead><tbody>{room.items.map((line,i)=><tr key={i}><td>{line.what}</td><td>{line.quantity} {line.unit}</td><td>{reviewMoney({ low: line.price_low, high: line.price_high }, 2)}</td><td>{reviewMoney(line)}</td><td>{line.from}{line.seen && <p>{line.seen}</p>}{line.at && <p>View: {line.at.standpoint} · {line.at.direction}</p>}{line.match ? <><p><strong>{line.match.label}</strong> · Matched by appearance; not an identification. Product prices exclude delivery and fitting.</p>{line.match.candidates.map((candidate, ci) => <p key={ci}>{candidate.make} {candidate.model || candidate.name} · {reviewMoney({low: candidate.price, high: candidate.price}, 2)}<br />{sourceLink(candidate.url) ? <a href={sourceLink(candidate.url)} target="_blank" rel="noopener noreferrer">{candidate.url}</a> : "No usable product-source link."}</p>)}</> : sourceLink(line.source_url) ? <p><a href={sourceLink(line.source_url)} target="_blank" rel="noopener noreferrer">{line.source_url}</a></p> : <p>No usable price-source link.</p>}</td></tr>)}</tbody></table>{(room.left_out ?? []).length > 0 && <p>Left out by the agent: {room.left_out.map(x=>`${x.saw} (${x.why})`).join("; ")}</p>}</section>)}<p>Agent decisions: {unit.decisions?.merged ?? 0} duplicate sightings merged; {unit.decisions?.left_out ?? 0} items left out; {unit.decisions?.doubts ?? 0} unresolved questions.</p>{(unit.rechecks ?? []).map((r,i)=><p key={i}>Second look at {r.room_name}: {r.changed.length ? r.changed.join("; ") : "No recorded changes."}</p>)}</div>)}</section>
      <section><h2>Building allocation</h2><table><thead><tr><th>Building</th><th>Assumed homes</th><th>Allocated range</th><th>Exterior ordering</th></tr></thead><tbody>{data.buildings.map(b=><tr key={b.id}><td>{b.id}</td><td>{b.homes_assumed}</td><td>{reviewMoney(b.total)}</td><td>Rank {b.exposure_rank}; vegetation within 5 ft: {b.brush_within_5ft_percent == null ? "unknown" : `${b.brush_within_5ft_percent}%`}</td></tr>)}</tbody></table><p>Vexcel supplies the exterior context. Allocation by roof area and vegetation ordering do not establish actual unit locations or probability of fire.</p></section>
      <section><h2>Assumptions and exclusions</h2><ul>{data.assumptions.map((a,i)=><li key={i}>{a}</li>)}</ul><h3>Not counted</h3><ul>{data.not_counted.map(x=><li key={x}>{x}</li>)}</ul></section>
      <footer>Prepared from the schedule displayed when this document was opened. Subsequent room rechecks do not change this snapshot; close and reopen to capture an updated schedule. Review with your estimator or broker before use.</footer>
    </article>
  </dialog>, window.document.body);
}
