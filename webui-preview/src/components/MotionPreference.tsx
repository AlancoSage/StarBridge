import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
} from "react";
import type { ReactNode } from "react";
import { MotionConfig, useReducedMotion } from "motion/react";

const storageKey = "vexbot.cdk.preview.motion";
type Preference = "enabled" | "disabled" | "system";
type MotionPreference = {
  enabled: boolean;
  reduced: boolean;
  toggleMotion: () => void;
};
const MotionPreferenceContext = createContext<MotionPreference | null>(null);
const parsePreference = (value: string | null): Preference =>
  value === "enabled" || value === "disabled" ? value : "system";

export function MotionPreferenceProvider({
  children,
}: {
  children: ReactNode;
}) {
  const systemReduced = useReducedMotion();
  const [preference, setPreference] = useState<Preference>(() => {
    try {
      return parsePreference(localStorage.getItem(storageKey));
    } catch {
      return "system";
    }
  });
  const enabled =
    preference === "enabled" || (preference === "system" && !systemReduced);

  useLayoutEffect(() => {
    document.documentElement.dataset.motion = enabled ? "full" : "reduced";
  }, [enabled]);

  useEffect(() => {
    const syncPreference = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null)
        setPreference(parsePreference(event.newValue));
    };
    addEventListener("storage", syncPreference);
    return () => removeEventListener("storage", syncPreference);
  }, []);

  const toggleMotion = () => {
    const next: Preference = enabled ? "disabled" : "enabled";
    setPreference(next);
    try {
      localStorage.setItem(storageKey, next);
    } catch {
      /* The current tab still follows the choice. */
    }
  };

  return (
    <MotionPreferenceContext.Provider
      value={{ enabled, reduced: !enabled, toggleMotion }}
    >
      <MotionConfig reducedMotion={enabled ? "never" : "always"}>
        {children}
      </MotionConfig>
    </MotionPreferenceContext.Provider>
  );
}

export function useMotionPreference() {
  const preference = useContext(MotionPreferenceContext);
  if (!preference) throw new Error("MotionPreferenceProvider is required");
  return preference;
}
