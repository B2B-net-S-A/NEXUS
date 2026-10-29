import { genitiveName } from "@/lib/career/format";

import { BrandPage, BrandTitle, brandStyles as s } from "./brand/BrandShell";

/** Podziękowanie po wysłaniu — kontekst z widoku, który pokazał formularz. */
export interface ThanksContext {
  variant: "job" | "general";
  recruiterFirstName: string;
  /** Tytuł rekrutacji („Senior Java Developer”) — tylko wariant `job`. */
  jobTitle?: string;
  homeHref: string;
  rodoHref: string;
  /** Adres w stopce. */
  hostLabel: string;
  recruiterPageHref?: string | null;
}

const CHECK = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden="true">
    <path d="m5 12 5 5 9-10" />
  </svg>
);

/**
 * Cała strona po wysłaniu formularza (makieta „Thanks”). Od 29.10.2026
 * w barwach marki zamiast logu `./aplikuj.sh --wyslij`: znacznik, tytuł,
 * trzy kroki, co już się stało, i odesłania dalej. Kolory bierze z szablonu
 * strony, z której kandydat wysłał zgłoszenie.
 */
export function ThanksLog({
  variant,
  firstName,
  email,
  recruiterFirstName,
  jobTitle,
  homeHref,
  rodoHref,
  hostLabel,
  recruiterPageHref,
}: ThanksContext & { firstName: string; email: string }) {
  const recruiter = genitiveName(recruiterFirstName);
  const name = firstName.trim();
  return (
    <BrandPage homeHref={homeHref} rodoHref={rodoHref} hostLabel={hostLabel}>
      <main className={s.main} aria-live="polite">
        <div className={`${s.wrap} ${s.message}`}>
          <div className={s.checkIcon} aria-hidden="true">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6">
              <path d="m5 12 5 5 9-10" />
            </svg>
          </div>
          <BrandTitle text={name ? `Dziękujemy, ${name}.` : "Dziękujemy."} />
          <p className={s.messageText}>
            {variant === "job" && jobTitle
              ? `Twoja aplikacja na ${jobTitle} trafiła do ${recruiter}. Odezwie się po przejrzeniu CV.`
              : `Twoje CV trafiło do ${recruiter}. Odezwie się, gdy pojawi się projekt dla Ciebie.`}
          </p>
          <ol className={s.steps} aria-label="Co już się stało">
            <li className={s.step}>
              <span className={s.stepMark}>{CHECK}</span>
              <span className={s.stepText}>
                <b>CV przesłane</b>
              </span>
            </li>
            <li className={s.step}>
              <span className={s.stepMark}>{CHECK}</span>
              <span className={s.stepText}>
                <b>Zgłoszenie zapisane</b>
              </span>
            </li>
            <li className={s.step}>
              <span className={s.stepMark}>{CHECK}</span>
              <span className={s.stepText}>
                <b>Powiadomienie wysłane</b>
                {recruiterFirstName.trim() ? ` do ${recruiter}` : ""}
              </span>
            </li>
          </ol>
          <ul className={s.messageNotes}>
            <li>
              Odpowiedź przyjdzie na <b>{email}</b>
            </li>
            <li>Twoje CV zostaje w bazie — dostaniesz też propozycje innych projektów.</li>
          </ul>
          <div className={`${s.actions} ${s.messageActions}`}>
            {recruiterPageHref ? (
              <a className={s.btn} href={recruiterPageHref}>
                Zobacz rekrutacje {recruiter}
              </a>
            ) : null}
            <a className={recruiterPageHref ? s.btnOutline : s.btn} href={homeHref}>
              Wszystkie otwarte rekrutacje
            </a>
          </div>
        </div>
      </main>
    </BrandPage>
  );
}
