interface MatterportSdk {
  connect: (iframe: HTMLIFrameElement, key: string, version: string) => Promise<any>;
}
declare global { interface Window { MP_SDK?: MatterportSdk } }

let pending: Promise<MatterportSdk> | null = null;

/** Importing this module does not download the SDK. Only an actual tour requests it. */
export function loadMatterportSdk(): Promise<MatterportSdk> {
  if (typeof window.MP_SDK?.connect === "function") return Promise.resolve(window.MP_SDK);
  if (pending) return pending;
  const attempt = new Promise<MatterportSdk>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://static.matterport.com/showcase-sdk/latest.js";
    script.async = true;
    const cleanup = () => {
      window.clearTimeout(timer);
      script.onload = null;
      script.onerror = null;
    };
    const fail = () => {
      cleanup();
      script.remove();
      reject(new Error("The Matterport viewer could not be loaded."));
    };
    const timer = window.setTimeout(fail, 20000);
    script.onload = () => {
      if (typeof window.MP_SDK?.connect !== "function") { fail(); return; }
      cleanup();
      resolve(window.MP_SDK);
    };
    script.onerror = fail;
    try { document.head.appendChild(script); } catch { fail(); }
  });
  pending = attempt;
  void attempt.catch(() => { if (pending === attempt) pending = null; });
  return attempt;
}
