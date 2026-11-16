// Czyste reguły karty „Umowa ramowa” kontraktu (F1, 15.11.2026) — testowane osobno.
import type { FrameworkCategory, FrameworkStatus } from "@/lib/api/framework-rates";

const PLN = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function plnPerHour(value: string | number | null): string {
  if (value === null || value === "") return "—";
  return `${PLN.format(Number(value))} zł/h`;
}

/** Kwota w tabeli: bez jednostki (jest w nagłówku kolumny). */
export function plnAmount(value: string | number | null): string {
  if (value === null || value === "") return "—";
  return PLN.format(Number(value));
}

export const STATUS_LABEL: Record<FrameworkStatus, string> = {
  in: "W stawce",
  in_addon: "W stawce dzięki dopłacie",
  over: "Ponad stawką",
  no_limit: "Bez limitu z umowy",
};

export function statusTone(status: FrameworkStatus): "success" | "info" | "danger" | "neutral" {
  if (status === "in") return "success";
  if (status === "in_addon") return "info";
  if (status === "over") return "danger";
  return "neutral";
}

/** Karta znika u klienta bez cennika umowy ramowej i bez kategorii z COA. */
export function showsFrameworkCard(data: FrameworkCategory | undefined): boolean {
  if (!data) return false;
  return data.cards.length > 0 || Boolean(data.coa_label) || data.card !== null;
}

/** „178,00 zł/h + 20% Kafka = 213,60 zł/h” albo samo maksimum. */
export function limitBreakdown(data: FrameworkCategory): string | null {
  if (!data.card || data.card.rate_max === null) return null;
  const base = plnPerHour(data.card.rate_max);
  if (!data.addon) return base;
  return `${base} + ${Number(data.addon.percent)}% ${data.addon.technology} = ${plnPerHour(data.framework_limit)}`;
}

export function sourceLabel(source: FrameworkCategory["source"]): string | null {
  if (source === "coa") return "z COA";
  if (source === "dl") return "wybrał Delivery Lead";
  return null;
}

/** Błąd formularza przed wysłaniem; `null` = można zapisać. */
export function categoryFormError(form: {
  rateCardId: number | null;
  addon: string;
  confirmedBy: string;
  confirmedOn: string;
}): string | null {
  if (form.rateCardId === null) return "Wybierz kategorię z umowy ramowej.";
  if (form.addon && (!form.confirmedBy.trim() || !form.confirmedOn)) {
    return "Dopłatę wpisz z potwierdzeniem klienta: kto potwierdził i kiedy.";
  }
  return null;
}
