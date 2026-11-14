/**
 * Resident phone experience (Person 3). Mounted by the lead after the invitation/session
 * bootstrap; receives the network adapter as `api`. Never reads owner/preparation data.
 *
 * Owns: screen navigation, in-memory drafts, connection/expired presentation.
 * Server state (snapshot, permissions, statuses) always comes from `api`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReportReceipt, ResidentApi, ResidentHome, SupportReceipt } from "./contract";
import { useResidentSession, type Connection } from "./useResidentSession";
import { emptyReportDraft, emptySupportDraft, type ReportDraft, type Screen, type SupportDraft } from "./screens/types";
import { HomeScreen } from "./screens/HomeScreen";
import { ReportFlow } from "./screens/ReportFlow";
import { ReceiptScreen } from "./screens/ReceiptScreen";
import { SupportFlow } from "./screens/SupportFlow";
import { UpdatesScreen } from "./screens/UpdatesScreen";
import { IconAlert, IconBack, IconInfo, IconLock, IconRetry, IconWifiOff } from "./icons";
import "./resident.css";

export type ResidentExperienceProps = {
  api: ResidentApi;
  on_session_expired: () => void;
};

const SCREEN_TITLES: Record<Screen["name"], string> = {
  home: "Home",
  report: "Report a problem",
  report_receipt: "Report received",
  support: "Request support",
  support_receipt: "Request received",
  updates: "My updates",
};

export function ResidentExperience({ api, on_session_expired }: ResidentExperienceProps) {
  const session = useResidentSession(api, on_session_expired);
  const [screen, setScreen] = useState<Screen>({ name: "home" });
  const [reportDraft, setReportDraft] = useState<ReportDraft>(emptyReportDraft);
  const [supportDraft, setSupportDraft] = useState<SupportDraft>(emptySupportDraft);
  const mainRef = useRef<HTMLDivElement>(null);

  const go = useCallback((next: Screen) => {
    setScreen(next);
    window.scrollTo({ top: 0 });
  }, []);

  // Move focus to the new screen's heading so screen readers announce the change.
  useEffect(() => {
    const h = mainRef.current?.querySelector<HTMLElement>("[data-screen-title]");
    h?.focus({ preventScroll: true });
  }, [screen.name]);

  // Revoke thumbnail URLs when photos leave the draft (e.g. after a successful submit).
  const clearReportDraft = useCallback(() => {
    setReportDraft((d) => {
      d.photos.forEach((p) => p.preview_url && URL.revokeObjectURL(p.preview_url));
      return emptyReportDraft();
    });
  }, []);

  const onReportSubmitted = useCallback((receipt: ReportReceipt) => {
    clearReportDraft();
    void session.refresh();
    go({ name: "report_receipt", receipt });
  }, [clearReportDraft, go, session]);

  const onSupportSubmitted = useCallback((receipt: SupportReceipt) => {
    setSupportDraft(emptySupportDraft());
    void session.refresh();
    go({ name: "support_receipt", receipt });
  }, [go, session]);

  const setReport = useCallback((u: (d: ReportDraft) => ReportDraft) => setReportDraft(u), []);
  const setSupport = useCallback((u: (d: SupportDraft) => SupportDraft) => setSupportDraft(u), []);

  if (session.connection === "expired") return <Expired />;

  const { home } = session;
  if (!home) {
    return (
      <div className="brace-resident">
        <div className="r-shell">
          {session.load_state === "error" ? (
            <LoadFailed message={session.load_error?.message ?? "Couldn't load your home."} retry={session.refresh} />
          ) : (
            <Loading />
          )}
        </div>
      </div>
    );
  }

  const onHome = screen.name === "home";
  return (
    <div className="brace-resident">
      <div className="r-shell">
        <TopBar home={home} back={onHome ? null : () => go({ name: "home" })} screenTitle={SCREEN_TITLES[screen.name]} />
        <ModeStrip home={home} />
        <ConnectionStrip connection={session.connection} />
        <div ref={mainRef} key={screen.name} className="r-screen">
          {screen.name === "home" && <HomeScreen home={home} fresh_ids={session.fresh_ids} go={go} />}
          {screen.name === "report" && (
            <ReportFlow
              api={api}
              home={home}
              connection={session.connection}
              draft={reportDraft}
              set_draft={setReport}
              on_submitted={onReportSubmitted}
              on_cancel={() => go({ name: "home" })}
              on_expired={session.expire}
            />
          )}
          {screen.name === "report_receipt" && (
            <ReceiptScreen home={home} receipt={{ kind: "report", receipt: screen.receipt }} go={go} />
          )}
          {screen.name === "support" && (
            <SupportFlow
              api={api}
              home={home}
              connection={session.connection}
              draft={supportDraft}
              set_draft={setSupport}
              on_submitted={onSupportSubmitted}
              on_cancel={() => go({ name: "home" })}
              on_expired={session.expire}
            />
          )}
          {screen.name === "support_receipt" && (
            <ReceiptScreen home={home} receipt={{ kind: "support", receipt: screen.receipt }} go={go} />
          )}
          {screen.name === "updates" && <UpdatesScreen home={home} fresh_ids={session.fresh_ids} go={go} />}
        </div>
      </div>
    </div>
  );
}

function TopBar({ home, back, screenTitle }: { home: ResidentHome; back: (() => void) | null; screenTitle: string }) {
  return (
    <header className={`r-topbar${back ? "" : " no-back"}`}>
      {back ? (
        <button type="button" className="r-back" onClick={back} aria-label={`Back to home from ${screenTitle}`}>
          <IconBack />
        </button>
      ) : null}
      <div className="r-where">
        <div className="r-property">{home.property_name}</div>
        {home.unit_confirmed && home.unit_label ? (
          <div className="r-unit">Unit {home.unit_label}</div>
        ) : (
          <div className="r-unit unconfirmed">
            {home.unit_label ? `Unit ${home.unit_label} — not confirmed` : "Unit not confirmed"}
          </div>
        )}
      </div>
    </header>
  );
}

/** Exercises and replays are always labelled so nobody mistakes them for a live event. */
function ModeStrip({ home }: { home: ResidentHome }) {
  if (home.mode === "observed_recovery") return null;
  return (
    <div className="r-strip exercise" role="note">
      <IconInfo size={18} />
      <span>
        <strong>{home.mode_label || (home.mode === "scenario_exercise" ? "Practice exercise" : "Historical replay")}</strong>
        {home.mode === "scenario_exercise" ? " — reports here are part of an exercise, not a real event." : " — based on a past event."}
      </span>
    </div>
  );
}

function ConnectionStrip({ connection }: { connection: Connection }) {
  if (connection === "offline") {
    return (
      <div className="r-strip offline" role="status">
        <IconWifiOff size={18} />
        <span><strong>Offline.</strong> You can keep filling things in. Nothing is sent until you're back online.</span>
      </div>
    );
  }
  if (connection === "reconnecting") {
    return (
      <div className="r-strip reconnecting" role="status">
        <IconRetry size={18} />
        <span><strong>Reconnecting…</strong> Updates may be a little behind.</span>
      </div>
    );
  }
  return null;
}

function Loading() {
  return (
    <div aria-busy="true" aria-label="Loading your home">
      <div className="r-topbar no-back" style={{ minHeight: 68 }} />
      <main className="r-main">
        <div className="r-head">
          <div className="r-skel" style={{ height: 30, width: "70%" }} />
          <div className="r-skel" style={{ height: 18, width: "50%" }} />
        </div>
        {[0, 1, 2].map((i) => (
          <div key={i} className="r-skel" style={{ height: 76 }} />
        ))}
      </main>
    </div>
  );
}

function LoadFailed({ message, retry }: { message: string; retry: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <main className="r-main">
      <header className="r-head">
        <h1 className="r-title">Couldn't load your home</h1>
        <p className="r-lede">{message}</p>
      </header>
      <button
        type="button"
        className="r-btn primary block"
        disabled={busy}
        aria-busy={busy}
        onClick={async () => {
          setBusy(true);
          await retry();
          setBusy(false);
        }}
      >
        <IconRetry size={20} /> {busy ? "Trying again…" : "Try again"}
      </button>
    </main>
  );
}

function Expired() {
  return (
    <div className="brace-resident">
      <div className="r-shell">
        <main className="r-main">
          <header className="r-head">
            <span style={{ color: "var(--r-bad)" }}><IconLock size={32} /></span>
            <h1 className="r-title">This link has expired</h1>
            <p className="r-lede">
              For your privacy, access links stop working after a while. Ask your property team for a new link or QR code.
            </p>
          </header>
          <div className="r-msg warn" role="note">
            <IconAlert size={20} />
            <div className="r-msg-body">Anything you hadn't sent yet was not saved.</div>
          </div>
        </main>
      </div>
    </div>
  );
}

export default ResidentExperience;
