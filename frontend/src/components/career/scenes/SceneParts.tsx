"use client";

import { useRef, type ReactNode } from "react";

import { ctaLabel, scoreNote, type SceneItem } from "./model";
import { usePointerVars, useScene } from "./SceneContext";

/** Etykieta przycisku pozycji: nazwa i notatka; stan niesie `aria-pressed`. */
export function itemAria(item: SceneItem): string {
  const kind = item.kind === "nice" ? " (mile widziane)" : "";
  return item.note ? `${item.name}${kind} — ${item.note}` : `${item.name}${kind}`;
}

/**
 * Pełna scena (komputer, ≥ 1024 px). Na telefonie CSS ją chowa, a tę samą
 * interakcję daje `SceneList`. `data-kr-still` = bez animacji.
 */
export function SceneFrame({
  label,
  className = "",
  children,
}: {
  /** Nazwa regionu dla czytnika („Terminal: sprawdź dopasowanie”). */
  label: string;
  className?: string;
  children: ReactNode;
}) {
  const { still, pointerFx } = useScene();
  const ref = useRef<HTMLDivElement>(null);
  usePointerVars(ref, pointerFx);
  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      className={`kr-scene-full kr-scene-box ${className}`.trim()}
      data-kr-still={still ? "" : undefined}
      data-testid="scene-full"
    >
      {children}
    </div>
  );
}

/**
 * Telefon (< 1024 px): ta sama interakcja jako zwarta lista przycisków, bez
 * efektów kursora. `mark` daje znak roli przed nazwą („[x]”, „PASS”, „200 OK”).
 */
export function SceneList({
  head,
  hint,
  mark,
  footer,
}: {
  head: ReactNode;
  hint: string;
  mark: (on: boolean, index: number) => string;
  footer?: ReactNode;
}) {
  const { items, isOn, toggle } = useScene();
  return (
    <div className="kr-scene-compact" data-testid="scene-compact">
      <p className="kr-scene-cl-head">{head}</p>
      <p className="kr-scene-cl-hint">{hint}</p>
      <ul className="kr-scene-cl">
        {items.map((item, i) => {
          const on = isOn(i);
          return (
            <li key={item.key}>
              <button
                type="button"
                className="kr-scene-cl-btn"
                aria-pressed={on}
                aria-label={itemAria(item)}
                onClick={() => toggle(i)}
              >
                <span className="kr-scene-cl-mark" aria-hidden="true">
                  {mark(on, i)}
                </span>
                <span className="kr-scene-cl-name" aria-hidden="true">
                  {item.name}
                  {item.note ? <span className="kr-c"> {"// "}{item.note}</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {footer}
    </div>
  );
}

/** Pięć kresek wyniku. */
export function ScoreSegments({ count, total }: { count: number; total: number }) {
  return (
    <span className="kr-score-segs" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className="kr-score-seg" data-on={i < count ? "" : undefined} />
      ))}
    </span>
  );
}

/**
 * Wynik „x z 5” przy przycisku „Aplikuj” (panel parametrów). Przycisk działa
 * zawsze, także przy zerze; poniżej kompletu — „Nie musisz mieć wszystkiego”.
 */
export function SceneScore({ label }: { label: ReactNode }) {
  const { count, total, applyHot } = useScene();
  return (
    <div className="kr-score" data-testid="scene-score">
      <p className="kr-score-head">
        <span>{label}</span>
        <b>
          {count}/{total}
        </b>
      </p>
      <ScoreSegments count={count} total={total} />
      <p className="kr-score-note" aria-live="polite">
        <span className="kr-sr">
          Masz {count} z {total}.{" "}
        </span>
        {scoreNote(count, total)}
      </p>
      <a href="#aplikuj" className="kr-score-cta" data-hot={applyHot ? "" : undefined}>
        {ctaLabel(count, total)}
      </a>
      <p className="kr-score-priv">Zaznaczenia widzisz tylko Ty — nic nie wysyłamy.</p>
    </div>
  );
}

/**
 * Celowy błąd szablonu Glitch. Czytnik ekranu dostaje opis z `aria-label`
 * zamiast literówki; po kliknięciu zostaje poprawny tekst.
 */
export function GlitchBug({
  index,
  wrong,
  right,
  what,
}: {
  index: number;
  wrong: string;
  right: string;
  /** „literówka w słowie rekrutacji”. */
  what: string;
}) {
  const { bugs, fixBug } = useScene();
  const found = bugs[index];
  // Znaleziony błąd zostaje tym samym przyciskiem (aria-pressed), żeby fokus
  // klawiatury nie spadł na <body>.
  return (
    <button
      type="button"
      className={found ? "kr-bug kr-bug-fixed" : "kr-bug"}
      data-bug={index}
      aria-pressed={found}
      aria-label={
        found
          ? `Błąd ${index + 1} z 3 znaleziony: ${what}.`
          : `Błąd ${index + 1} z 3: ${what}. Kliknij, żeby oznaczyć jako znaleziony.`
      }
      onClick={() => fixBug(index)}
    >
      <span aria-hidden="true">{found ? right : wrong}</span>
    </button>
  );
}
