import {
  animate,
  useInView,
  useMotionValue,
  useReducedMotion,
} from "motion/react";
import { useEffect, useRef, useState } from "react";

const formatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

export function AnimatedNumber({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  const target = Number.isFinite(value) ? Math.round(value) : 0;
  const reduceMotion = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const amount = useMotionValue(0);
  const [display, setDisplay] = useState(reduceMotion ? target : 0);

  useEffect(() => {
    // Hidden pages stay mounted. Start counting only when the number is visible.
    if (!inView && !reduceMotion) return;
    let disposed = false;
    const start = amount.get();
    const publish = (next: number) => {
      if (disposed) return;
      // Keep spring overshoot from briefly reporting more players than exist.
      const clamped = Math.min(
        Math.max(next, Math.min(start, target)),
        Math.max(start, target),
      );
      setDisplay(Math.round(clamped));
    };
    const unsubscribe = amount.on("change", publish);

    if (reduceMotion || document.hidden) {
      amount.set(target);
      setDisplay(target);
      return unsubscribe;
    }

    const finish = () => {
      if (disposed) return;
      amount.set(target);
      setDisplay(target);
    };
    const animation = animate(amount, target, {
      type: "spring",
      duration: 1.15,
      bounce: 0.12,
      onComplete: finish,
    });
    // A suspended animation frame loop must not leave a stale count behind.
    const finalize = () => {
      animation.stop();
      finish();
    };
    const timeout = window.setTimeout(finalize, 1600);
    const handleVisibility = () => {
      if (document.hidden) finalize();
    };
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      disposed = true;
      animation.stop();
      unsubscribe();
      window.clearTimeout(timeout);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [amount, inView, reduceMotion, target]);

  return (
    <span
      ref={ref}
      className={className}
      aria-label={formatter.format(target)}
      aria-live="off"
      data-animated-number="true"
      data-value={target}
    >
      {formatter.format(reduceMotion ? target : display)}
    </span>
  );
}

export default AnimatedNumber;
