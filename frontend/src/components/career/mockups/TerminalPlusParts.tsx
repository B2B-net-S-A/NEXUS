"use client";

/**
 * MAKIETA `terminal-plus`: karta „Co już masz?” — jedyne miejsce z wymaganiami.
 * Zaznaczenia żyją tylko w pamięci przeglądarki, nic nie wysyłamy.
 */
import { useState } from "react";

import styles from "./terminalPlus.module.css";

interface FitItem {
  key: string;
  name: string;
  note: string | null;
}

function FitRow({
  item,
  on,
  nice,
  onToggle,
}: {
  item: FitItem;
  on: boolean;
  nice: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={on}
        onClick={onToggle}
        className={`${styles.fitRow} ${nice ? styles.fitRowNice : ""} ${on ? styles.fitRowOn : ""}`}
      >
        <span className={styles.fitBox} aria-hidden="true">
          [{on ? "x" : " "}]
        </span>
        <span className={styles.fitText}>
          <span className={styles.fitName}>{item.name}</span>
          {item.note ? <span className={styles.fitNote}>{item.note}</span> : null}
        </span>
      </button>
    </li>
  );
}

export function TerminalPlusFitCard({
  must,
  nice,
  applyHref,
}: {
  must: { name: string; note: string | null }[];
  nice: string[];
  applyHref: string;
}) {
  const mustItems: FitItem[] = must
    .filter((m) => m.name.trim())
    .map((m, i) => ({ key: `m${i}`, name: m.name.trim(), note: m.note?.trim() || null }));
  const niceItems: FitItem[] = nice
    .filter((n) => n.trim())
    .map((n, i) => ({ key: `n${i}`, name: n.trim(), note: null }));
  const total = mustItems.length + niceItems.length;
  const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (key: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const count = checked.size;
  const full = total > 0 && count >= total;

  return (
    <section id="wymagania" className={styles.fit} aria-labelledby="tp-fit-title">
      <header className={styles.fitHead}>
        <div>
          <h2 id="tp-fit-title" className={styles.fitTitle}>
            Co już masz?
          </h2>
          <p className={styles.fitHint}>Zaznacz to, co znasz z projektów.</p>
        </div>
        <p className={styles.fitCount} aria-live="polite">
          <strong>{count}</strong>
          <span> z {total}</span>
        </p>
      </header>

      {mustItems.length > 0 ? (
        <div className={styles.fitGroup}>
          <h3 className={styles.fitLabel}>Wymagane</h3>
          <ul className={styles.fitList}>
            {mustItems.map((item) => (
              <FitRow
                key={item.key}
                item={item}
                nice={false}
                on={checked.has(item.key)}
                onToggle={() => toggle(item.key)}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {niceItems.length > 0 ? (
        <div className={styles.fitGroup}>
          <h3 className={`${styles.fitLabel} ${styles.fitLabelNice}`}>Mile widziane</h3>
          <ul className={styles.fitList}>
            {niceItems.map((item) => (
              <FitRow
                key={item.key}
                item={item}
                nice
                on={checked.has(item.key)}
                onToggle={() => toggle(item.key)}
              />
            ))}
          </ul>
        </div>
      ) : null}

      <p className={styles.fitFoot}>
        {full ? "Pełne dopasowanie — czekamy na Ciebie." : "Nie musisz mieć wszystkiego — aplikuj."}{" "}
        <a href={applyHref} className={styles.fitFootLink}>
          Aplikuj&nbsp;→
        </a>
      </p>
    </section>
  );
}
