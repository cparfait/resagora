import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

const racine = document.getElementById("racine");
if (racine) {
  createRoot(racine).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

// MOB-01 : application installable qui s'ouvre sans réseau ; une nouvelle version s'active au retour du réseau.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").then((inscription) => {
      inscription.addEventListener("updatefound", () => {
        const nouveau = inscription.installing;
        nouveau?.addEventListener("statechange", () => {
          if (nouveau.state === "installed" && navigator.serviceWorker.controller) nouveau.postMessage("activer", { transfer: [] });
        });
      });
    });
  });
}
