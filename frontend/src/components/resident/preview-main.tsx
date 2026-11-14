/** Dev-only entry for preview.html. Mounts the fixture preview; not imported by the app. */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ResidentPreview } from "./ResidentPreview";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ResidentPreview />
  </StrictMode>,
);
