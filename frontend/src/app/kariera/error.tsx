"use client";

import { BrandBare, BrandTitle, brandStyles as s } from "@/components/career/brand/BrandShell";
import { CareerThemeScope } from "@/components/career/CareerThemeScope";

/** Awaria odczytu (np. API niedostępne) — w barwach marki, z ponowieniem. */
export default function CareerError({ reset }: { error: Error; reset: () => void }) {
  return (
    <CareerThemeScope theme="grafit">
      <BrandBare>
        <main className={`${s.wrap} ${s.message}`} role="alert">
          <BrandTitle text="Chwilowa przerwa." />
          <p className={s.messageText}>Nie udało się wczytać strony. Spróbuj ponownie za chwilę.</p>
          <div className={`${s.actions} ${s.messageActions}`}>
            <button type="button" className={s.btn} onClick={reset}>
              Spróbuj ponownie
            </button>
          </div>
        </main>
      </BrandBare>
    </CareerThemeScope>
  );
}
