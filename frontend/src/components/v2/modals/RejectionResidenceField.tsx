"use client";

/**
 * Powód „Mieszka poza Polską” w oknie odrzucenia (decyzja Artura 24.11.2026).
 *
 * System nie proponuje do rekrutacji osób, które według profilu mieszkają
 * poza Polską (`backend/app/services/residence.py`). Przy jednej osobie okno
 * pyta, gdzie mieszka (domyślnie kraj z profilu), a serwer zapisuje kraj na
 * profilu jak ołówek „Lokalizacja” — bez tego osoba bez kraju w profilu
 * wracałaby w kolejnych rekrutacjach.
 */

import { FormField } from "@/components/ui/form-field";

export interface RejectionResidenceProfile {
  city: string | null;
  country: string | null;
}

/** Kraje najczęstsze w bazie poza Polską (kopia produkcji, 24.11.2026). */
export const ABROAD_COUNTRIES: ReadonlyArray<{ code: string; label: string }> = [
  { code: "IN", label: "Indie" },
  { code: "UA", label: "Ukraina" },
  { code: "DE", label: "Niemcy" },
  { code: "GB", label: "Wielka Brytania" },
  { code: "RO", label: "Rumunia" },
  { code: "ES", label: "Hiszpania" },
  { code: "PK", label: "Pakistan" },
  { code: "BY", label: "Białoruś" },
  { code: "FR", label: "Francja" },
  { code: "NL", label: "Holandia" },
  { code: "US", label: "Stany Zjednoczone" },
  { code: "NG", label: "Nigeria" },
  { code: "IT", label: "Włochy" },
  { code: "TR", label: "Turcja" },
  { code: "CZ", label: "Czechy" },
  { code: "PT", label: "Portugalia" },
  { code: "IE", label: "Irlandia" },
  { code: "SE", label: "Szwecja" },
  { code: "NO", label: "Norwegia" },
  { code: "FI", label: "Finlandia" },
  { code: "CH", label: "Szwajcaria" },
  { code: "AE", label: "Zjednoczone Emiraty Arabskie" },
];

export function countryLabel(code: string | null | undefined): string | null {
  const upper = code?.trim().toUpperCase();
  if (!upper) return null;
  if (upper === "PL") return "Polska";
  return ABROAD_COUNTRIES.find((c) => c.code === upper)?.label ?? upper;
}

/** Kraj z profilu, jeśli to nie Polska — od niego startuje pole. */
export function profileAbroadCountry(profile: RejectionResidenceProfile | null | undefined): string {
  const code = profile?.country?.trim().toUpperCase() ?? "";
  return /^[A-Z]{2}$/.test(code) && code !== "PL" ? code : "";
}

interface Props {
  /** `undefined` — kilka osób albo profil niewczytany. */
  profile?: RejectionResidenceProfile | null;
  several: boolean;
  country: string;
  onCountryChange: (code: string) => void;
}

export function RejectionResidenceField({ profile, several, country, onCountryChange }: Props) {
  const current = profile
    ? [profile.city, countryLabel(profile.country)].filter(Boolean).join(", ") || null
    : null;
  const alreadySaved = !!country && country === profileAbroadCountry(profile);
  const options = ABROAD_COUNTRIES.some((c) => c.code === country) || !country
    ? ABROAD_COUNTRIES
    : [...ABROAD_COUNTRIES, { code: country, label: country }];

  return (
    <div
      data-testid="rejection-residence"
      className="ml-6 space-y-2 rounded-md border border-border border-l-2 border-l-primary px-3 py-2.5"
    >
      {several ? null : (
        <FormField label="Gdzie mieszka?" required>
          <select
            id="rejection-residence-country"
            aria-label="Kraj zamieszkania"
            value={country}
            onChange={(e) => onCountryChange(e.target.value)}
            className="h-9 w-full max-w-xs rounded-md border border-border bg-background px-2 text-sm"
          >
            <option value="">Wybierz kraj</option>
            {options.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
        </FormField>
      )}
      {several ? null : alreadySaved ? (
        <p className="text-xs text-muted-foreground" data-testid="rejection-residence-current">
          Na profilu już jest: {current}.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="rejection-residence-current">
          Zapiszemy na profilu: <span className="font-medium">Kraj → {countryLabel(country) ?? "…"}</span>
          {profile !== undefined ? ` (teraz: ${current ?? "nie uzupełniono"})` : null}.
        </p>
      )}
      <p className="text-xs text-muted-foreground" data-testid="rejection-residence-system">
        System nie proponuje do rekrutacji osób mieszkających poza Polską — nie doda{" "}
        {several ? "tych osób" : "tej osoby"} do żadnej rekrutacji. Ręcznie można{" "}
        {several ? "je" : "ją"} dodać.
      </p>
    </div>
  );
}
