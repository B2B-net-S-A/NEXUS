"use client";

/**
 * Lewa kolumna okna: fakty „Z tej rekrutacji”, czego brakuje, warunki
 * wpisane w ogłoszeniu (miasto, start, długość, język pracy) i przypomnienie
 * o widełkach.
 *
 * Miasto ma pole od 28.10.2026: lokalizacja rekrutacji bywa adresem biura
 * klienta, a po adresie łatwo go wygooglować. Puste = miasto z rekrutacji.
 *
 * Wpisane, a niezapisane warunki trzyma okno (`drafts`): ponowne wczytanie
 * ogłoszenia po odrzuconym zapisie nie może ich wyczyścić.
 */

import { AlertCircle, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AdContent, AdFact, AdReadinessItem } from "@/lib/api/jobAd";

import type { AdDrafts } from "./job-ad-edit";

export type AdTerms = Pick<AdContent, "city" | "start" | "duration" | "language">;
export const TERM_KEYS = ["city", "start", "duration", "language"] as const;

interface AdFactsRailProps {
  facts: AdFact[];
  readiness: AdReadinessItem[];
  /** `null` = ogłoszenie jeszcze nie powstało. */
  content: AdContent | null;
  drafts: AdDrafts;
  saving: boolean;
  /** Trwa przygotowanie nowej treści. */
  locked: boolean;
  onDraftChange: (key: keyof AdTerms, text: string | null) => void;
  onSaveTerms: (terms: AdTerms) => Promise<boolean>;
}

const TERM_FIELDS: ReadonlyArray<{
  key: keyof AdTerms;
  label: string;
  placeholder: string;
}> = [
  { key: "city", label: "Miasto w ogłoszeniu", placeholder: "np. Warszawa" },
  { key: "start", label: "Start projektu", placeholder: "np. listopad 2026" },
  {
    key: "duration",
    label: "Długość współpracy",
    placeholder: "np. 12 miesięcy",
  },
  {
    key: "language",
    label: "Język pracy",
    placeholder: "np. polski, angielski B2",
  },
];

export function AdFactsRail({
  facts,
  readiness,
  content,
  drafts,
  saving,
  locked,
  onDraftChange,
  onSaveTerms,
}: AdFactsRailProps) {
  const saved = (key: keyof AdTerms) => content?.[key] ?? "";
  const value = (key: keyof AdTerms) => drafts[key] ?? saved(key);
  const dirty = TERM_KEYS.some((key) => value(key).trim() !== saved(key));
  const missing = readiness.filter((item) => !item.present);
  const recruitmentCity = facts.find((fact) => fact.key === "city")?.value;
  const placeholderOf = (key: keyof AdTerms, fallback: string) =>
    key === "city" && recruitmentCity ? `Z rekrutacji: ${recruitmentCity}` : fallback;

  return (
    <aside
      aria-label="Z tej rekrutacji"
      className="flex w-[252px] flex-none flex-col gap-4 overflow-y-auto border-r border-border bg-card px-4 py-3 text-[13px]"
    >
      <div className="flex flex-col gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Z tej rekrutacji
        </h2>
        {facts.length > 0 ? (
          <dl className="grid grid-cols-[84px_minmax(0,1fr)] gap-x-2 gap-y-1">
            {facts.map((fact) => (
              <div key={fact.key} className="contents">
                <dt className="text-muted-foreground">{fact.label}</dt>
                <dd className="text-foreground">{fact.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <ul className="flex flex-col gap-1" data-testid="job-ad-readiness">
          {readiness.map((item) => (
            <li
              key={item.key}
              className={
                item.present
                  ? "flex items-center gap-1.5 text-foreground"
                  : "flex items-center gap-1.5 text-warning-muted-foreground"
              }
            >
              {item.present ? (
                <Check className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" />
              ) : (
                <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              )}
              {item.label}
              {item.present ? null : " — brak"}
            </li>
          ))}
        </ul>
        {missing.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Czego nie ma w rekrutacji, tego generator nie dopisuje.
          </p>
        ) : null}
      </div>

      {content ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void onSaveTerms({
              city: value("city").trim(),
              start: value("start").trim(),
              duration: value("duration").trim(),
              language: value("language").trim(),
            });
          }}
        >
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Warunki w ogłoszeniu
          </h2>
          {TERM_FIELDS.map(({ key, label, placeholder }) => (
            <label key={key} className="flex flex-col gap-1" data-ad-field={key}>
              <span className="text-xs text-muted-foreground">{label}</span>
              <Input
                value={value(key)}
                placeholder={placeholderOf(key, placeholder)}
                maxLength={80}
                className="h-8 text-[13px]"
                onChange={(event) =>
                  // Powrót do zapisanej wartości = pole nie jest już w edycji.
                  onDraftChange(key, event.target.value === saved(key) ? null : event.target.value)
                }
              />
            </label>
          ))}
          {dirty ? (
            <Button
              type="submit"
              size="sm"
              loading={saving}
              disabled={locked}
              className="self-start"
            >
              Zapisz warunki
            </Button>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Zapis dotyczy ogłoszenia. Puste miasto = miasto z rekrutacji, bez ulicy. Pozostałe
            puste pola ogłoszenie pomija.
          </p>
        </form>
      ) : null}

      <div className="rounded-md bg-muted px-3 py-2">
        <p className="font-medium text-foreground">Nie trafia do ogłoszenia</p>
        <p className="text-muted-foreground">
          nazwa klienta, stawki i budżet, notatki „Tylko zespół”, numer requestu
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Widełki
        </h2>
        <p className="text-xs text-muted-foreground">
          Wpisujesz je samodzielnie w formularzu portalu. Nie podpowiadamy ich z budżetu rekrutacji,
          a w treści ogłoszenia kwot nie ma.
        </p>
      </div>
    </aside>
  );
}
