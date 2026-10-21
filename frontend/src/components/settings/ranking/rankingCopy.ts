import type { RankingLayer, RankingMetrics, RankingPanelWeights } from "@/lib/api";

export const LAYER_LABELS: Record<RankingLayer, string> = {
  semantic: "Podobieństwo CV do rekrutacji",
  skills: "Umiejętności z listy",
  location: "Lokalizacja i tryb pracy",
  salary: "Stawka",
  availability: "Dostępność",
};

export const LAYER_SHORT: Record<"semantic" | "skills" | "location", string> = {
  semantic: "CV",
  skills: "Umiejętności",
  location: "Lokalizacja",
};

/** Co liczy warstwa — tak jak liczy silnik (scoring_service.py). */
export const LAYER_HINTS: Record<RankingLayer, string> = {
  semantic:
    "AI (Voyage) porównuje całe CV i profil z treścią rekrutacji: opisem, wymaganiami, Championem. To główny składnik.",
  skills:
    "Ile technologii z listy osoba ma (profil, CV, notatki). Wymagane liczą się 2×, mile widziane 1×.",
  location: "Pół za tryb (zdalnie / hybryda / biuro), pół za miasto. Brak danych = 65% punktów.",
  salary:
    "Każdy dostaje tyle samo, więc kolejności nie zmienia. Stawka ponad budżet to plakietka „+X%” (decyzja z 30.09).",
  availability: "Wyłączona — w pomiarze z 17.08 pogarszała trafność.",
};

export const SLIDER_HINTS: Record<"semantic" | "skills" | "location", string> = {
  semantic: "Całe CV i profil porównane przez AI z opisem rekrutacji.",
  skills: "Wymagane 2×, mile widziane 1×. Szuka w profilu, CV i notatkach.",
  location: "Miasto i zdalnie / hybryda / biuro. Brak danych = 65% punktów.",
};

/** Kolory warstw z tokenów wykresów (bez palety). */
export const LAYER_COLORS: Record<RankingLayer, string> = {
  semantic: "bg-chart-1",
  skills: "bg-chart-2",
  location: "bg-chart-3",
  salary: "bg-muted-foreground/40",
  availability: "bg-transparent border border-muted-foreground/40",
};

export const EDITABLE = ["semantic", "skills", "location"] as const;
export type EditableLayer = (typeof EDITABLE)[number];

export const METRIC_LABELS: Record<keyof RankingMetrics, { label: string; hint?: string }> = {
  page1_hit: {
    label: "Rekrutacje, w których właściwa osoba jest na 1. stronie",
    hint: "właściwa = zweryfikowana albo wysłana do klienta; 1. strona = 50 pierwszych",
  },
  median_first: { label: "Miejsce pierwszej właściwej osoby (mediana)" },
  top50_share: { label: "Właściwe osoby w top 50" },
  mrr: { label: "Średnia odwrotność miejsca pierwszej właściwej (MRR)" },
  proposals: {
    label: "Osoby z „Dop.” od progu w 200 pierwszych",
    hint: "przybliżenie nocnych propozycji na tych samych rekrutacjach",
  },
};

const pl = (value: number, digits = 1) =>
  value.toLocaleString("pl-PL", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

export function formatMetric(key: keyof RankingMetrics, value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (key === "page1_hit" || key === "top50_share") return `${pl(value)}%`;
  if (key === "mrr") return pl(value, 3);
  return pl(value, 1);
}

/** Zmiana miary z kierunkiem „lepiej”: mediana miejsca lepsza, gdy maleje. */
export function metricDelta(
  key: keyof RankingMetrics,
  before: number | null,
  after: number | null,
): { text: string; tone: "better" | "worse" | "same" } {
  if (before === null || after === null) return { text: "—", tone: "same" };
  const diff = after - before;
  if (Math.abs(diff) < 1e-9) return { text: "bez zmian", tone: "same" };
  if (key === "median_first") {
    const places = Math.abs(diff);
    const word = places === 1 ? "miejsce" : places < 5 ? "miejsca" : "miejsc";
    return diff < 0
      ? { text: `▲ ${pl(places)} ${word}`, tone: "better" }
      : { text: `▼ ${pl(places)} ${word}`, tone: "worse" };
  }
  if (key === "proposals") {
    return { text: `${diff > 0 ? "+" : "−"}${pl(Math.abs(diff), 0)}`, tone: "same" };
  }
  const unit = key === "mrr" ? "" : " pkt";
  return diff > 0
    ? { text: `▲ ${pl(diff, key === "mrr" ? 3 : 1)}${unit}`, tone: "better" }
    : { text: `▼ ${pl(-diff, key === "mrr" ? 3 : 1)}${unit}`, tone: "worse" };
}

/** „Umiejętności 10 → 30 · próg 70 → 75” */
export function describeChange(
  before: RankingPanelWeights | undefined,
  after: RankingPanelWeights | undefined,
): string {
  if (!after) return "";
  if (!before) {
    return `CV ${after.semantic} · umiejętności ${after.skills} · lokalizacja ${after.location} · próg ${after.threshold}%`;
  }
  const parts: string[] = [];
  for (const layer of EDITABLE) {
    if (before[layer] !== after[layer]) {
      parts.push(`${LAYER_SHORT[layer]} ${before[layer]} → ${after[layer]}`);
    }
  }
  if (before.threshold !== after.threshold) {
    parts.push(`próg ${before.threshold}% → ${after.threshold}%`);
  }
  return parts.length ? parts.join(" · ") : "bez zmian w ważnościach";
}

const DATE_TIME = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

const DATE = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? DATE_TIME.format(new Date(iso)) : "—";
}

export function formatDate(iso: string | null | undefined): string {
  return iso ? DATE.format(new Date(iso)) : "—";
}
