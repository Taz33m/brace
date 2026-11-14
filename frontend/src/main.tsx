import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

// A page playing inside the show is a shot: it says so before anything is drawn, so its own navigation never appears.
try { if (window.frameElement?.hasAttribute("data-shot")) document.documentElement.dataset.show = window.frameElement.getAttribute("data-shot") ?? ""; } catch { /* a frame from elsewhere: not the show */ }

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
