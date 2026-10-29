import { BrandBare, brandStyles as s } from "@/components/career/brand/BrandShell";
import { CareerThemeScope } from "@/components/career/CareerThemeScope";

/**
 * Własna granica ładowania strony kariery. Bez niej zadziałałby szkielet
 * pulpitu z `app/loading.tsx` — kandydat widziałby na chwilę jasne karty
 * i tabelę przed stroną kariery. Pasek z logo jak na docelowej stronie
 * (od 29.10.2026 barwy marki, nie okno terminala).
 */
export default function CareerLoading() {
  return (
    <CareerThemeScope theme="grafit">
      <BrandBare>
        <main className={`${s.wrap} ${s.message}`} role="status" aria-live="polite">
          <p className={s.note}>Ładowanie…</p>
        </main>
      </BrandBare>
    </CareerThemeScope>
  );
}
