/**
 * Rama strony kariery w układzie nowej strony B2B Network: czerwony nagłówek
 * z nawigacją głównej strony (b2bnetwork.pl) i grafitowa stopka z danymi
 * rejestrowymi. Kariera żyje w NEXUSIE pod kariera.b2bnetwork.pl, a reszta
 * nawigacji prowadzi na stronę firmy.
 */
import type { ReactNode } from "react";

import "../layouts/brandFonts.css";
import { B2BLogo } from "../B2BLogo";
import s from "./site.module.css";

export { s as siteStyles };

/** Strona firmy, na którą prowadzi nawigacja (bez domeny kariery). */
export const COMPANY_SITE = "https://b2bnetwork.pl";

const site = (path: string) => `${COMPANY_SITE}${path}`;

const TOP_LINKS = [
  { label: "O firmie", href: site("/grupa") },
  { label: "Kontakt", href: site("/kontakt") },
];

const NAV_LINKS = [
  { label: "Kogo dostarczamy", href: site("/#kompetencje") },
  { label: "Modele współpracy", href: site("/#modele") },
  { label: "Proces", href: site("/#proces") },
  { label: "Realizacje", href: site("/#realizacje") },
  { label: "Dla specjalistów", href: site("/dla-specjalistow") },
];

const CLIENT_CTA = { label: "Opisz, kogo potrzebujesz", href: site("/#kontakt") };

/** Znacznik rozdziału na lewym marginesie (od 1280 px, jak na planszach). */
export function ChapterMark({ index, count, name }: { index: number; count: number; name: string }) {
  return (
    <div aria-hidden="true" className={s.mark}>
      {Array.from({ length: count }, (_, i) => (
        <i key={i} className={i === index ? s.markOn : undefined} />
      ))}
      <span>
        {String(index + 1).padStart(2, "0")} {name}
      </span>
    </div>
  );
}

/** Rekruter prowadzący: kółko z inicjałem, imię i krótka notka. */
export function Who({
  name,
  initialOf,
  note,
  white = false,
  className,
}: {
  name: string;
  /** Imię, z którego bierzemy inicjał (domyślnie `name`). */
  initialOf?: string;
  note?: string;
  white?: boolean;
  className?: string;
}) {
  const initial = (initialOf ?? name).trim().charAt(0).toLocaleUpperCase("pl-PL");
  return (
    <div className={`${s.who} ${className ?? ""}`}>
      {initial ? (
        <span aria-hidden="true" className={`${s.av} ${white ? s.avWhite : ""}`}>
          {initial}
        </span>
      ) : null}
      <div>
        <b>{name}</b>
        {note ? <span>{note}</span> : null}
      </div>
    </div>
  );
}

export function ErrorIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true">
      <circle cx="7.5" cy="7.5" r="7.5" fill="currentColor" />
      <path d="M7.5 3.4v5" stroke="#fff" strokeWidth="1.9" />
      <circle cx="7.5" cy="11" r="1.1" fill="#fff" />
    </svg>
  );
}

export function CheckIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={(size * 13) / 16} viewBox="0 0 16 13" fill="none" aria-hidden="true">
      <path d="M1.5 6.5l4.6 4.6L14.5 2" stroke="currentColor" strokeWidth="2.6" strokeLinecap="square" />
    </svg>
  );
}

export function SiteFrame({
  homeHref,
  rodoHref,
  children,
}: {
  /** Strona główna kariery (lista rekrutacji). */
  homeHref: string;
  rodoHref: string;
  children: ReactNode;
}) {
  return (
    <div className={s.site} lang="pl">
      <header className={s.header}>
        <nav className={`${s.wrap} ${s.top}`} aria-label="Strona firmy">
          {TOP_LINKS.slice(0, 1).map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
          <a href={homeHref} aria-current="page" className={s.navCur}>
            Kariera
          </a>
          {TOP_LINKS.slice(1).map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
        </nav>
        <div className={`${s.wrap} ${s.headerInner}`}>
          <a href={COMPANY_SITE} className={s.logo} aria-label="B2Bnetwork — strona główna firmy">
            <B2BLogo variant="white" height={36} />
          </a>
          <nav className={s.nav} aria-label="Nawigacja główna">
            {NAV_LINKS.map((l) => (
              <a key={l.href} href={l.href}>
                {l.label}
              </a>
            ))}
          </nav>
          <a href={CLIENT_CTA.href} className={s.headerCta}>
            {CLIENT_CTA.label}
          </a>
          <details className={s.menu}>
            <summary aria-label="Menu">
              <svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true">
                <path d="M0 1h20M0 7h20M0 13h20" stroke="currentColor" strokeWidth="2" />
              </svg>
            </summary>
            <div className={s.menuList}>
              <a href={homeHref}>Kariera: wszystkie rekrutacje</a>
              {[...NAV_LINKS, ...TOP_LINKS].map((l) => (
                <a key={l.href} href={l.href}>
                  {l.label}
                </a>
              ))}
            </div>
          </details>
        </div>
      </header>

      <div className={s.main}>{children}</div>

      <footer className={s.footer}>
        <div className={`${s.wrap} ${s.footerGrid}`}>
          <div>
            <div className={s.footerBrand}>
              <B2BLogo variant="onDark" height={34} />
              <b>B2B.NET S.A.</b>
            </div>
            <p>Al. Jerozolimskie 180, 02-486 Warszawa</p>
            <p>
              KRS 0000387063 · NIP 5711707392 · Sąd Rejonowy dla m.st. Warszawy, XII Wydział
              Gospodarczy KRS · kapitał zakładowy 1 360 000 zł, wpłacony w całości
            </p>
          </div>
          <div className={s.footerRight}>
            <nav className={s.footerNav} aria-label="Stopka">
              <a href={COMPANY_SITE}>B2Bnetwork</a>
              <a href={homeHref}>Kariera</a>
              <a href={site("/kontakt")}>Kontakt</a>
              <a href={site("/grupa")}>O firmie</a>
              <a href={rodoHref}>Klauzula RODO dla kandydatów</a>
            </nav>
            <p>© {new Date().getFullYear()} B2B.NET S.A.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
