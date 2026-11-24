import { SiteFrame, siteStyles as s } from "@/components/career/site/SiteFrame";
import { careerHref } from "@/lib/career/host";

import { careerRequestContext } from "./_context";

/** 404 strony kariery — także każdy adres spoza listy na hoście kariery. Rama nowej strony B2B Network. */
export default async function CareerNotFound() {
  const { base } = await careerRequestContext();
  const homeHref = careerHref(base, { to: "home" });
  return (
    <SiteFrame homeHref={homeHref} rodoHref={careerHref(base, { to: "rodo" })}>
      <main>
        <section className={`${s.ch} ${s.chRed} ${s.notice}`}>
          <div className={s.wrap}>
            <p aria-hidden="true" className={`${s.display} ${s.heroNum}`}>
              404
            </p>
            <h1 className={`${s.lead} ${s.recLead}`}>Nie znaleziono strony.</h1>
            <p className={`${s.body} ${s.recAbout}`}>
              Sprawdź, czy link z ogłoszenia jest kompletny — albo zobacz wszystkie otwarte rekrutacje
              B2Bnetwork.
            </p>
            <div className={s.actions}>
              <a className={`${s.btn} ${s.btnWhite}`} href={homeHref}>
                Wszystkie otwarte rekrutacje
              </a>
            </div>
          </div>
        </section>
      </main>
    </SiteFrame>
  );
}
