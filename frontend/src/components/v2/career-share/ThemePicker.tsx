"use client";

import { Check, Loader2 } from "lucide-react";

import {
  CAREER_THEME_IDS,
  CAREER_THEMES,
  careerTheme,
  isCareerThemeId,
  type CareerThemeId,
} from "@/components/career/themes";

/**
 * Wybór szablonu graficznego rekrutacji w oknie „Udostępnij” (od 28.10.2026
 * trzy szablony B2B Network zamiast 12 scen ról).
 *
 * WYJĄTEK OD ZASADY TOKEN-FIRST: próbki kolorów odwzorowują ZEWNĘTRZNĄ stronę
 * kariery i grafikę OG, więc idą z palet szablonów (`components/career/
 * themes.ts`). Ramki, podpisy i stany wyboru to NEXUS: tokeny.
 */
export interface ThemePickerProps {
  /** Wybór rekrutera; `null` = domyślny według roli. */
  value: string | null;
  /** Domyślny szablon tej rekrutacji (rola z tytułu, potem kategoria). */
  defaultTheme: string;
  onChange: (theme: string | null) => void;
  busy?: boolean;
}

export function ThemePicker({ value, defaultTheme, onChange, busy = false }: ThemePickerProps) {
  // Zapisana dawna scena (sprzed 28.10.2026) nie jest już szablonem — strona
  // pokazuje wtedy domyślny według roli, więc wybór wygląda jak brak wyboru.
  const chosen = isCareerThemeId(value) ? value : null;
  const effective = chosen ?? defaultTheme;
  const defaultLabel = careerTheme(defaultTheme).label;
  return (
    <section className="space-y-2" aria-labelledby="job-theme-heading">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="job-theme-heading" className="text-sm font-semibold text-foreground">
          Wygląd strony, grafiki i plakatu
        </h3>
        {chosen ? (
          <button
            type="button"
            className="text-xs font-medium text-primary underline-offset-2 hover:underline disabled:opacity-60"
            onClick={() => onChange(null)}
            disabled={busy}
          >
            Przywróć domyślny ({defaultLabel})
          </button>
        ) : null}
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Domyślny wynika z roli w tytule rekrutacji. Zmiana działa od razu na stronie i w nowych
        postach — bez ponownego zatwierdzania opisu. Posty już opublikowane zachowują grafikę
        z dnia publikacji.
      </p>
      <div className="grid grid-cols-3 gap-2" role="group" aria-label="Szablony">
        {CAREER_THEME_IDS.map((id: CareerThemeId) => {
          const t = CAREER_THEMES[id];
          const selected = id === effective;
          return (
            <button
              key={id}
              type="button"
              aria-pressed={selected}
              disabled={busy}
              onClick={() => onChange(id === defaultTheme ? null : id)}
              className={`flex flex-col gap-1.5 rounded-md border p-1.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-progress ${
                selected ? "border-primary bg-primary/5" : "border-border hover:border-foreground/30"
              }`}
              data-testid={`theme-${id}`}
            >
              {/* Kolory strony kariery, nie tokeny — patrz komentarz na górze pliku. */}
              <span
                className="flex h-12 flex-col justify-end rounded px-2 py-1.5 font-sans text-[11px] font-extrabold leading-none"
                style={{ backgroundColor: t.bg, border: `1px solid ${t.line}` }}
                aria-hidden="true"
              >
                <span style={{ color: t.heading }}>Senior</span>
                <span style={{ color: t.title }}>Developer</span>
              </span>
              <span className="flex items-center justify-between gap-1 text-xs font-medium text-foreground">
                <span className="truncate">{t.label}</span>
                {selected && busy ? (
                  <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden="true" />
                ) : selected ? (
                  <Check className="h-3 w-3 shrink-0 text-primary" aria-hidden="true" />
                ) : null}
              </span>
              <span className="truncate text-[11px] text-muted-foreground">
                {id === defaultTheme ? "domyślny · " : ""}
                {t.role}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
