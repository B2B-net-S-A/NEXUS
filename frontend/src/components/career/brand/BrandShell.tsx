/**
 * Rama ekranów kariery poza stroną rekrutacji (tablica, strona rekrutera,
 * podziękowanie, zamknięta rekrutacja, 404) w barwach marki B2B Network —
 * ten sam pasek z logo, stopka i kroje co szablony ogłoszeń z
 * `components/career/layouts/` (decyzja Artura 28.10.2026). Kolory z tokenów
 * `--kr-*` szablonu (`CareerThemeScope`), więc rama działa w Grafit, Terminal
 * i Jasny.
 */
import type { ReactNode } from "react";

import { B2BLogo } from "../B2BLogo";
import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import "../layouts/brandFonts.css";
import styles from "./brandPage.module.css";

export { styles as brandStyles };

/** Łuki znaku B2B (dwie „brzuszki” litery B) — dekoracja za tytułem, jak w Grafit. */
export function BrandArc({ className }: { className?: string }) {
  return (
    <svg className={className ?? styles.arc} viewBox="0 0 520 600" aria-hidden="true" focusable="false">
      <path
        className={styles.arcPath}
        d="M30 40 H300 A125 125 0 0 1 300 290 H170 M170 290 H330 A140 140 0 0 1 330 570 H30"
        pathLength={1}
      />
    </svg>
  );
}

/** Ostatnie słowo w czerwieni marki — tylko słowo z liter (numer na końcu zostaje biały). */
export function BrandTitle({
  text,
  as: Tag = "h1",
  className,
  id,
}: {
  text: string;
  as?: "h1" | "h2";
  className?: string;
  id?: string;
}) {
  const i = text.lastIndexOf(" ");
  const last = i > 0 ? text.slice(i + 1) : text;
  const letters = /^[\p{L}-]+[.!?,]?$/u.test(last);
  const head = letters ? (i > 0 ? text.slice(0, i + 1) : "") : text;
  const tail = letters ? last : "";
  return (
    <Tag className={className ?? styles.title} id={id}>
      {head}
      {tail ? <span className={styles.titleTail}>{tail}</span> : null}
    </Tag>
  );
}

/** Pasek z samym logo — ekran ładowania i błędu (bez kontekstu żądania). */
export function BrandBare({ children }: { children: ReactNode }) {
  return (
    <div className={styles.root}>
      <header className={styles.bar}>
        <div className={styles.barInner}>
          <span className={styles.logoLink}>
            <B2BLogo variant="onDark" height={30} className={styles.logoDark} />
            <B2BLogo variant="color" height={30} className={styles.logoLight} />
          </span>
        </div>
      </header>
      {children}
    </div>
  );
}

export function BrandPage({
  homeHref,
  homeLabel = "Wszystkie rekrutacje",
  cta,
  rodoHref,
  hostLabel,
  children,
}: {
  homeHref: string;
  /** Link w pasku; `null` = bez (np. na samej tablicy). */
  homeLabel?: string | null;
  /** Przycisk w pasku (np. „Zostaw CV” → `#zostaw-cv`). */
  cta?: { href: string; label: string } | null;
  rodoHref: string;
  /** Adres strony w stopce, np. „kariera.b2bnetwork.pl/marta-n”. */
  hostLabel: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.root}>
      <header className={styles.bar}>
        <div className={styles.barInner}>
          <a href={homeHref} className={styles.logoLink} aria-label="B2B Network — wszystkie rekrutacje">
            <B2BLogo variant="onDark" height={30} className={styles.logoDark} />
            <B2BLogo variant="color" height={30} className={styles.logoLight} />
          </a>
          {homeLabel || cta ? (
            <nav className={styles.barNav} aria-label="Nawigacja">
              {homeLabel ? (
                <a href={homeHref} className={styles.barLink}>
                  {homeLabel}
                </a>
              ) : null}
              {cta ? (
                <a href={cta.href} className={styles.barCta}>
                  {cta.label}
                </a>
              ) : null}
            </nav>
          ) : null}
        </div>
      </header>
      {children}
      <BrandFooter rodoHref={rodoHref} hostLabel={hostLabel} homeHref={homeHref} />
    </div>
  );
}

export function BrandFooter({
  rodoHref,
  hostLabel,
  homeHref,
}: {
  rodoHref: string;
  hostLabel: string;
  homeHref: string;
}) {
  return (
    <footer className={styles.footer}>
      <div className={styles.footerTop}>
        <B2BLogo variant="onDark" height={24} className={styles.logoDark} />
        <B2BLogo variant="color" height={24} className={styles.logoLight} />
        <span className={styles.footerBrand}>B2B.NET S.A.</span>
        <a href={rodoHref} className={styles.footerLink}>
          Klauzula informacyjna RODO
        </a>
        <a href={homeHref} className={styles.footerLink}>
          {hostLabel}
        </a>
      </div>
      <p className={styles.legal}>{COMPANY_LEGAL_LINE}</p>
    </footer>
  );
}
