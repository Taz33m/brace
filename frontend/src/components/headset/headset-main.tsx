/** Dev entry for headset.html. Reads ?site= and ?scan=; defaults to the lead home (Verdugo Mesa). */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HeadsetView } from "./HeadsetView";

const q = new URLSearchParams(window.location.search);
const site = Number(q.get("site")) || 9519837;
const scan = /^[A-Za-z0-9]+$/.test(q.get("scan") ?? "") ? (q.get("scan") as string) : "CaSLe7ZwnfF";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <HeadsetView site={site} scan={scan} />
  </StrictMode>,
);
