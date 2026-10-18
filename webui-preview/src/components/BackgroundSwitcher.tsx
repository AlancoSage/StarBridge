import { useEffect, useLayoutEffect, useState } from "react";
import { Check, Palette } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

const STORAGE_KEY = "vexbot.cdk.preview.background";
const backgrounds = [
  { id: "plain", name: "纯净" },
  { id: "mist", name: "雾蓝" },
  { id: "mint", name: "薄荷" },
  { id: "sand", name: "暖砂" },
  { id: "dots", name: "点阵" },
] as const;

type Background = (typeof backgrounds)[number]["id"];

function normalizeBackground(value: string | null): Background {
  return (
    backgrounds.find((background) => background.id === value)?.id ?? "plain"
  );
}

function readBackground(): Background {
  try {
    return normalizeBackground(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return "plain";
  }
}

export default function BackgroundSwitcher() {
  const [background, setBackground] = useState<Background>(readBackground);

  useLayoutEffect(() => {
    document.documentElement.dataset.background = background;
    try {
      window.localStorage.setItem(STORAGE_KEY, background);
    } catch {
      // The selected background still works when browser storage is unavailable.
    }
  }, [background]);

  useEffect(() => {
    function syncBackground(event: StorageEvent) {
      if (event.key === STORAGE_KEY || event.key === null) {
        setBackground(normalizeBackground(event.newValue));
      }
    }
    window.addEventListener("storage", syncBackground);
    return () => window.removeEventListener("storage", syncBackground);
  }, []);

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          className="background-toggle"
          aria-label="切换背景"
          title="切换背景"
        >
          <Palette aria-hidden="true" />
          <span className="background-toggle-label">背景</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="background-picker max-h-[90dvh] overflow-y-auto p-6 sm:max-w-lg">
        <DialogTitle className="pr-8">切换背景</DialogTitle>
        <DialogDescription className="mt-2 leading-relaxed">
          选择你喜欢的背景，设置会保存在此浏览器。
        </DialogDescription>
        <div
          className="background-options mt-5"
          role="group"
          aria-label="背景预设"
        >
          {backgrounds.map((option) => (
            <button
              type="button"
              className="background-option"
              key={option.id}
              aria-pressed={background === option.id}
              onClick={() => setBackground(option.id)}
            >
              <span
                className={`background-swatch background-swatch-${option.id}`}
                aria-hidden="true"
              />
              <span className="background-option-name">{option.name}</span>
              {background === option.id && (
                <span className="background-selected-check" aria-hidden="true">
                  <Check size={14} />
                </span>
              )}
            </button>
          ))}
        </div>
        <div className="mt-5 flex justify-end">
          <DialogClose asChild>
            <Button>完成</Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}
