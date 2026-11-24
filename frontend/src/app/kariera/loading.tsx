import { SiteFrame, siteStyles as s } from "@/components/career/site/SiteFrame";

/**
 * Własna granica ładowania strony kariery. Bez niej zadziałałby szkielet
 * pulpitu z `app/loading.tsx` — kandydat widziałby na chwilę jasne karty
 * i tabelę przed stroną kariery. Rama nowej strony B2B Network (od 24.11.2026),
 * bez linków do kariery, bo granica nie zna hosta żądania.
 */
export default function CareerLoading() {
  return (
    <SiteFrame homeHref={null} rodoHref={null}>
      <main>
        <section className={`${s.ch} ${s.chRed} ${s.notice}`}>
          <div className={s.wrap} role="status" aria-live="polite">
            <p className={`${s.lead} ${s.recLead}`}>Ładowanie…</p>
          </div>
        </section>
      </main>
    </SiteFrame>
  );
}
