import { BrandPage, BrandTitle, brandStyles as s } from "@/components/career/brand/BrandShell";
import { CareerThemeScope } from "@/components/career/CareerThemeScope";
import { careerHref } from "@/lib/career/host";

import { careerRequestContext } from "./_context";

/** 404 strony kariery — także każdy adres spoza listy na hoście kariery. */
export default async function CareerNotFound() {
  const { base, host } = await careerRequestContext();
  const homeHref = careerHref(base, { to: "home" });
  return (
    <CareerThemeScope theme="grafit">
      <BrandPage homeHref={homeHref} rodoHref={careerHref(base, { to: "rodo" })} hostLabel={host}>
        <main className={`${s.wrap} ${s.message}`}>
          <BrandTitle text="Nie znaleziono strony." />
          <p className={s.messageText}>
            Sprawdź, czy link z ogłoszenia jest kompletny — albo zobacz wszystkie otwarte
            rekrutacje B2B Network.
          </p>
          <div className={`${s.actions} ${s.messageActions}`}>
            <a className={s.btn} href={homeHref}>
              Wszystkie otwarte rekrutacje
            </a>
          </div>
        </main>
      </BrandPage>
    </CareerThemeScope>
  );
}
