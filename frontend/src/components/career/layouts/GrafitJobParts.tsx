"use client";

import { useEffect, useState } from "react";

import styles from "./grafitJob.module.css";

interface GrafitApplyBarProps {
  /** Kontener formularza (`#aplikuj`). */
  targetId: string;
  /** Przycisk „Aplikuj” w nagłówku strony — dopóki widać go, pasek jest zbędny. */
  heroId: string;
}

/**
 * Przyklejony dolny pasek „Aplikuj — 2 minuty” na telefonie (CSS chowa go od
 * 641 px). Znika, gdy na ekranie jest przycisk z pierwszego ekranu albo
 * formularz — dwa takie same przyciski naraz tylko zasłaniają treść.
 */
export function GrafitApplyBar({ targetId, heroId }: GrafitApplyBarProps) {
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    const targets = [heroId, targetId]
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (targets.length === 0 || typeof IntersectionObserver === "undefined") {
      setHidden(false);
      return;
    }
    const visible = new Set<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target);
          else visible.delete(entry.target);
        }
        setHidden(visible.size > 0);
      },
      { rootMargin: "0px 0px -20% 0px" },
    );
    targets.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [targetId, heroId]);

  return (
    <div className={styles.applyBar} data-hidden={hidden ? "" : undefined} inert={hidden}>
      <a href={`#${targetId}`} className={styles.applyBarBtn}>
        Aplikuj — 2 minuty
      </a>
    </div>
  );
}
