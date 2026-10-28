"use client";

/**
 * Szablon `terminal`: karta „Co już masz?” — jedyne miejsce z wymaganiami na
 * stronie. Zaznaczenia żyją tylko w pamięci komponentu (bez localStorage, bez
 * wysyłki). Licznik pojawia się dopiero po pierwszym zaznaczeniu — „0 z 6” na
 * starcie czytało się jak wynik testu (przegląd makiety 28.10.2026).
 */
import { useState } from "react";

import styles from "./terminalJob.module.css";

/** Przy dłuższej liście karta pokazuje tyle pozycji, żeby nie rozpychać hero (MDM: 24). */
const VISIBLE = 6;
/** Zwijamy dopiero, gdy schowane byłyby co najmniej trzy pozycje. */
const COLLAPSE_FROM = VISIBLE + 3;

interface FitItem {
  key: string;
  name: string;
  note: string | null;
  nice: boolean;
}

function FitRow({ item, on, hidden, onToggle }: { item: FitItem; on: boolean; hidden: boolean; onToggle: () => void }) {
  return (
    <li hidden={hidden}>
      <button
        type="button"
        role="checkbox"
        aria-checked={on}
        onClick={onToggle}
        className={`${styles.fitRow} ${item.nice ? styles.fitRowNice : ""} ${on ? styles.fitRowOn : ""}`}
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

export function TerminalFitCard({
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
    .map((m, i) => ({ key: `m${i}`, name: m.name.trim(), note: m.note?.trim() || null, nice: false }));
  const niceItems: FitItem[] = nice
    .filter((n) => n.trim())
    .map((n, i) => ({ key: `n${i}`, name: n.trim(), note: null, nice: true }));
  const total = mustItems.length + niceItems.length;
  const collapsible = total >= COLLAPSE_FROM;

  const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set());
  const [expanded, setExpanded] = useState(false);
  const toggle = (key: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // Wymagane idą pierwsze, więc przy zwiniętej karcie widać najważniejsze.
  const isHidden = (index: number) => collapsible && !expanded && index >= VISIBLE;
  const count = checked.size;
  const full = total > 0 && count >= total;
  const niceHidden = niceItems.every((_, i) => isHidden(mustItems.length + i));

  return (
    <section id="wymagania" className={styles.fit} aria-label="Wymagania">
      <header className={styles.fitHead}>
        <div>
          <h2 className={styles.fitTitle}>
            Co już masz?
          </h2>
          <p className={styles.fitHint}>
            {count === 0 ? "Zaznacz, co już znasz." : "Nie musisz mieć wszystkiego."}
          </p>
        </div>
        <p className={styles.fitCount} aria-live="polite">
          {count > 0 ? (
            <>
              <strong>{count}</strong>
              <span> z {total}</span>
            </>
          ) : null}
        </p>
      </header>

      {mustItems.length > 0 ? (
        <div className={styles.fitGroup}>
          <h3 className={styles.fitLabel}>Wymagane</h3>
          <ul className={styles.fitList}>
            {mustItems.map((item, i) => (
              <FitRow
                key={item.key}
                item={item}
                hidden={isHidden(i)}
                on={checked.has(item.key)}
                onToggle={() => toggle(item.key)}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {niceItems.length > 0 ? (
        <div className={styles.fitGroup} hidden={niceHidden}>
          <h3 className={`${styles.fitLabel} ${styles.fitLabelNice}`}>Mile widziane</h3>
          <ul className={styles.fitList}>
            {niceItems.map((item, i) => (
              <FitRow
                key={item.key}
                item={item}
                hidden={isHidden(mustItems.length + i)}
                on={checked.has(item.key)}
                onToggle={() => toggle(item.key)}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {collapsible ? (
        <button
          type="button"
          className={styles.fitMore}
          aria-expanded={expanded}
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? "Zwiń listę" : `Pokaż wszystkie (${total})`}
        </button>
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
