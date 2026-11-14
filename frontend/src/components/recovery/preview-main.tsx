// Dev-only entry for preview.html: mounts the fixture preview with the real app's global styles (read, not edited).
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../styles.css";
import { RecoveryPreview } from "./RecoveryPreview";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RecoveryPreview />
  </StrictMode>,
);
