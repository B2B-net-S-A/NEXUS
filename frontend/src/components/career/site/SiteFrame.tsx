/**
 * Rama strony kariery w układzie nowej strony B2B Network: nagłówek
 * w gradiencie wariantu 5 z nawigacją głównej strony (b2bnetwork.pl) i stopka
 * w burgund-obsydianie z danymi spółki, jak na stronie głównej (25.11.2026,
 * źródło: `SiteHeader.tsx`, `SiteFooter.tsx` i `content/site/shared.ts` repo
 * b2bnetwork-www). Kariera żyje w NEXUSIE pod kariera.b2bnetwork.pl, a reszta
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

const TOP_LINKS = [{ label: "O firmie", href: site("/grupa") }];

const NAV_LINKS = [
  { label: "Kogo dostarczamy", href: site("/#kompetencje") },
  { label: "Modele współpracy", href: site("/#modele") },
  { label: "Proces", href: site("/#proces") },
  { label: "Realizacje", href: site("/#realizacje") },
  { label: "Dla specjalistów", href: site("/dla-specjalistow") },
  { label: "R&D", href: site("/rd/dynaminds-labs") },
  { label: "Kontakt", href: site("/kontakt") },
];

/** Ten sam przycisk co w nagłówku strony głównej; na wąskich telefonach krótka etykieta. */
const CLIENT_CTA = { label: "Porozmawiajmy o projekcie", short: "Porozmawiajmy", href: site("/#kontakt") };

/** Stopka strony głównej: dwie kolumny czytane wierszami, Kariera prowadzi tutaj. */
const FOOTER_LINKS = [
  { label: "B2B Network", href: COMPANY_SITE },
  { label: "Kariera", href: null },
  { label: "DYNAMINDS Labs", href: site("/rd/dynaminds-labs") },
  { label: "Kontakt", href: site("/kontakt") },
  { label: "O firmie", href: site("/grupa") },
  { label: "Szkolenia", href: site("/szkolenia") },
  { label: "Blog", href: site("/blog") },
];

const LEGAL_LINKS = [
  { label: "Polityka prywatności", href: site("/polityka-prywatnosci") },
  { label: "Cookies", href: site("/cookies") },
  { label: "Ochrona sygnalistów", href: site("/ochrona-sygnalistow") },
  { label: "Spółka akcyjna", href: site("/spolka-akcyjna") },
];

const PHONE = { label: "+48 577 317 312", href: "tel:+48577317312" };
const LINKEDIN = "https://www.linkedin.com/company/b2bnetwork/";

/** Znak wyjścia na inną stronę (jak w stopce strony głównej). */
function OutMark() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true" className={s.out}>
      <path d="M1 12 11.5 1.5M4 1.5h7.5V9" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

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
  pageLabel,
  children,
}: {
  /** Strona główna kariery (lista rekrutacji); `null` = ekran bez kontekstu żądania (błąd, ładowanie). */
  homeHref: string | null;
  rodoHref: string | null;
  /** Adres tej strony w stopce, np. „kariera.b2bnetwork.pl/marta-n” (strona rekrutera). */
  pageLabel?: string;
  children: ReactNode;
}) {
  return (
    <div className={s.site} lang="pl">
      <header className={s.header}>
        <nav className={`${s.wrap} ${s.top}`} aria-label="Strona firmy">
          {TOP_LINKS.map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
          {homeHref ? (
            <a href={homeHref} aria-current="page" className={s.navCur}>
              Kariera
            </a>
          ) : (
            <span className={s.navCur}>Kariera</span>
          )}
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
            <span className={s.ctaShort}>{CLIENT_CTA.short}</span>
            <span className={s.ctaLong}>{CLIENT_CTA.label}</span>
          </a>
          <details className={s.menu}>
            <summary aria-label="Menu">
              <svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true">
                <path d="M0 1h20M0 7h20M0 13h20" stroke="currentColor" strokeWidth="2" />
              </svg>
            </summary>
            <div className={s.menuList}>
              {homeHref ? <a href={homeHref}>Kariera: wszystkie rekrutacje</a> : null}
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
        <div className={s.wrap}>
          <div className={s.footerGrid}>
            <div className={s.footerInfo}>
              <div className={s.footerBrand}>
                <B2BLogo variant="white" height={34} />
                <b>B2B.net S.A.</b>
              </div>
              <p>Kopernik Office Buildings, wejście A, Al. Jerozolimskie 180, 02-486 Warszawa</p>
              <p>
                KRS 0000387063 · NIP 5711707392 · REGON 280613330
                <br />
                kapitał zakładowy 1 360 000 zł, wpłacony w całości
              </p>
              <p className={s.footerContact}>
                <a href={PHONE.href}>
                  <span className={s.srOnly}>Telefon </span>
                  {PHONE.label}
                </a>
                <a href={LINKEDIN}>
                  LinkedIn
                  <OutMark />
                </a>
              </p>
            </div>
            <nav className={s.footerNav} aria-label="Stopka">
              {FOOTER_LINKS.map((l) =>
                l.href ? (
                  <a key={l.label} href={l.href}>
                    {l.label}
                  </a>
                ) : homeHref ? (
                  <a key={l.label} href={homeHref}>
                    {l.label}
                  </a>
                ) : null,
              )}
            </nav>
          </div>
          <div className={s.footerBottom}>
            <p>
              © {new Date().getFullYear()} B2B.net S.A.
              {pageLabel ? <span className={s.mono}> · {pageLabel}</span> : null}
            </p>
            <nav className={s.footerLegal} aria-label="Informacje prawne">
              {rodoHref ? <a href={rodoHref}>Klauzula RODO dla kandydatów</a> : null}
              {LEGAL_LINKS.map((l) => (
                <a key={l.href} href={l.href}>
                  {l.label}
                </a>
              ))}
            </nav>
          </div>
        </div>
      </footer>
    </div>
  );
}
