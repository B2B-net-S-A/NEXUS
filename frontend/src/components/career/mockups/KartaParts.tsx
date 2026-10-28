"use client";

/**
 * MAKIETA — wariant `karta`: części klienckie. Stan tylko w pamięci, nic nie
 * wysyłamy (zaznaczenia „Znam to” widzi wyłącznie kandydat).
 */
import { useEffect, useState } from "react";

import s from "./karta.module.css";

export function MustList({ items }: { items: { name: string; note: string | null }[] }) {
  const [known, setKnown] = useState<boolean[]>(() => items.map(() => false));
  const count = known.filter(Boolean).length;
  const total = items.length;
  /** Długa lista (np. 20 technologii) jako przyciski-kafelki, żeby nie zajęła trzech ekranów telefonu. */
  const compact = total > 6;
  const toggle = (i: number) => setKnown((prev) => prev.map((v, j) => (j === i ? !v : v)));
  const tally =
    count === 0 ? "Zaznacz, co znasz" : count === total ? `Masz ${count} z ${total} — komplet` : `Masz ${count} z ${total}`;

  return (
    <>
      <div className={s.mustHead}>
        <h2 className={s.h2}>Wymagane</h2>
        <span className={s.tally} data-on={count > 0 ? "" : undefined} aria-live="polite">
          {tally}
        </span>
      </div>
      {compact ? (
        <ul className={s.mustChips}>
          {items.map((item, i) => (
            <li key={`${item.name}-${i}`}>
              <button
                type="button"
                className={s.mustChip}
                aria-pressed={known[i]}
                title={item.note ?? undefined}
                onClick={() => toggle(i)}
              >
                <span className={s.chipMark} aria-hidden>
                  {known[i] ? "✓" : "+"}
                </span>
                {item.name}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <ul className={s.mustList}>
          {items.map((item, i) => (
            <li key={`${item.name}-${i}`} className={s.mustItem} data-known={known[i] ? "" : undefined}>
              <span className={s.mustMark} aria-hidden>
                <svg viewBox="0 0 20 20" width="20" height="20">
                  <path d="M5 10.5l3.2 3.2L15 7" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <span className={s.mustText}>
                <span className={s.mustName}>{item.name}</span>
                {item.note ? <span className={s.mustNote}>{item.note}</span> : null}
              </span>
              <button
                type="button"
                className={s.knowBtn}
                aria-pressed={known[i]}
                aria-label={`${item.name}: znam to`}
                onClick={() => toggle(i)}
              >
                {known[i] ? "Znam ✓" : "Znam to"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** Dolny pasek „Aplikuj” na telefonie; chowa się, gdy formularz jest już na ekranie. */
export function ApplyBar({ targetId }: { targetId: string }) {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const el = document.getElementById(targetId);
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([entry]) => setHidden(entry.isIntersecting), {
      rootMargin: "0px 0px -30% 0px",
    });
    io.observe(el);
    return () => io.disconnect();
  }, [targetId]);

  return (
    <div className={s.applyBar} data-hidden={hidden ? "" : undefined}>
      <a href={`#${targetId}`} className={s.applyBtn} tabIndex={hidden ? -1 : undefined}>
        Aplikuj — 2 minuty
      </a>
    </div>
  );
}
