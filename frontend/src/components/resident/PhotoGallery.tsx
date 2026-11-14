import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import "./photo-gallery.css";

export interface GalleryPhoto { id: string; url: string; alt: string }
export interface PhotoGalleryProps { photos: GalleryPhoto[]; label: string; compact?: boolean }

function Thumbnail({ photo, number }: { photo: GalleryPhoto; number: number }) {
  const [failed, setFailed] = useState(false);
  return failed ? <span className="r-gallery-thumb-error">Photo {number}<br />Open to retry</span>
    : <img src={photo.url} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

function FullPhoto({ photo }: { photo: GalleryPhoto }) {
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  return <div className="r-gallery-image-area">
    {status === "loading" && <p className="r-gallery-loading" role="status">Loading photo…</p>}
    {status === "failed" ? <div className="r-gallery-error" role="alert">
      <p>This photo could not be loaded.</p>
      <button type="button" onClick={() => { setStatus("loading"); setAttempt(value => value + 1); }}>Retry photo</button>
    </div> : <img key={attempt} src={photo.url} alt={photo.alt || "Submitted photo"}
      onLoad={() => setStatus("ready")} onError={() => setStatus("failed")} />}
  </div>;
}

/** Uses only caller-supplied media URLs; opening a photo never submits a report. */
export function PhotoGallery({ photos, label, compact = false }: PhotoGalleryProps) {
  const headingId = useId();
  const captionId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const gallery = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const scope = JSON.stringify(photos.map(photo => [photo.id, photo.url]));
  const [selection, setSelection] = useState<{ scope: string; id: string } | null>(null);
  const index = selection?.scope === scope ? photos.findIndex(photo => photo.id === selection.id) : -1;
  const active = index >= 0 ? photos[index] : null;

  useEffect(() => {
    const node = dialog.current;
    if (active && node && !node.open) node.showModal();
    else if (!active && node?.open) node.close();
  }, [active?.id, scope]);

  function closed() {
    setSelection(null);
    if (opener.current?.isConnected) opener.current.focus({ preventScroll: true });
    else if (gallery.current?.isConnected) gallery.current.focus({ preventScroll: true });
    opener.current = null;
  }
  function move(delta: number) {
    const next = photos[index + delta];
    if (active && next) setSelection({ scope, id: next.id });
  }
  function keyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      move(event.key === "ArrowLeft" ? -1 : 1);
    }
    // Escape is handled by the native modal dialog, including its focus trap.
  }

  if (!photos.length) return null;
  return <div ref={gallery} className={`r-gallery${compact ? " is-compact" : ""}`} tabIndex={-1}>
    <ul className="r-gallery-thumbnails" aria-label={label}>
      {photos.map((photo, photoIndex) => <li key={`${photo.id}:${photo.url}`}>
        <button type="button" className="r-gallery-thumbnail" aria-haspopup="dialog"
          aria-label={`Open photo ${photoIndex + 1} of ${photos.length}: ${photo.alt || label}`}
          onClick={event => { event.stopPropagation(); opener.current = event.currentTarget; setSelection({ scope, id: photo.id }); }}>
          <Thumbnail photo={photo} number={photoIndex + 1} />
          <span className="r-gallery-expand" aria-hidden="true">↗</span>
        </button>
      </li>)}
    </ul>
    <dialog ref={dialog} className="r-gallery-dialog" aria-labelledby={headingId} aria-describedby={captionId}
      onClose={closed} onKeyDown={keyDown} onClick={event => event.stopPropagation()}>
      <header className="r-gallery-header"><h2 id={headingId}>{label}</h2>
        <button type="button" autoFocus onClick={() => dialog.current?.close()}>Close</button>
      </header>
      {active && <FullPhoto key={`${active.id}:${active.url}`} photo={active} />}
      <footer className="r-gallery-footer">
        <button type="button" aria-label="Previous photo" disabled={index <= 0} onClick={() => move(-1)}>← Previous</button>
        <div className="r-gallery-caption" id={captionId} aria-live="polite" aria-atomic="true">
          <span>Photo {index + 1} of {photos.length}</span>
          {active?.alt && <span>{active.alt}</span>}
        </div>
        <button type="button" aria-label="Next photo" disabled={index < 0 || index >= photos.length - 1} onClick={() => move(1)}>Next →</button>
      </footer>
    </dialog>
  </div>;
}
