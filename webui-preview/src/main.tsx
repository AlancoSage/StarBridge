import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ConsoleAuthProvider } from "./components/ConsoleAuth";
import { MotionPreferenceProvider } from "./components/MotionPreference";
import "./theme.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionPreferenceProvider>
      <ConsoleAuthProvider>
        <App />
      </ConsoleAuthProvider>
    </MotionPreferenceProvider>
  </StrictMode>,
);
