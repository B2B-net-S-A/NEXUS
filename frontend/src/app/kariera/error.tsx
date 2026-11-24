"use client";

import { SiteFrame, siteStyles as s } from "@/components/career/site/SiteFrame";

/**
 * Awaria odczytu (np. API niedostępne) — w ramie nowej strony B2B Network,
 * z ponowieniem. Bez kontekstu żądania, więc bez linków do kariery i RODO.
 */
export default function CareerError({ reset }: { error: Error; reset: () => void }) {
  return (
    <SiteFrame homeHref={null} rodoHref={null}>
      <main>
        <section className={`${s.ch} ${s.chRed} ${s.notice}`}>
          <div className={s.wrap} role="alert">
            <p aria-hidden="true" className={`${s.display} ${s.heroNum}`}>
              ?
            </p>
            <h1 className={`${s.lead} ${s.recLead}`}>Chwilowa przerwa.</h1>
            <p className={`${s.body} ${s.recAbout}`}>Nie udało się wczytać strony. Spróbuj ponownie za chwilę.</p>
            <div className={s.actions}>
              <button type="button" className={`${s.btn} ${s.btnWhite}`} onClick={reset}>
                Spróbuj ponownie
              </button>
            </div>
          </div>
        </section>
      </main>
    </SiteFrame>
  );
}
