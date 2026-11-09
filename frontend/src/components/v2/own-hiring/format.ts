import type { OwnHiringCard } from "@/lib/api/ownHiring";

const TZ = "Europe/Warsaw";

export function formatMonths(months: number | null): string {
  if (months === null || months <= 0) return "bez dat";
  if (months < 12) return `${months} mies.`;
  const years = Math.floor(months / 12);
  const rest = months % 12;
  const yearText = years === 1 ? "1 r." : `${years} l.`;
  return rest ? `${yearText} ${rest} mies.` : yearText;
}

export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("pl-PL", { timeZone: TZ, day: "numeric", month: "numeric" });
}

/** Termin odpowiedzi to północ po ostatnim dniu: pokazujemy ten ostatni dzień. */
export function formatDueDay(iso: string): string {
  return formatDay(new Date(new Date(iso).getTime() - 1).toISOString());
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("pl-PL", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
}

export function formatWhen(iso: string): string {
  const weekday = new Date(iso).toLocaleDateString("pl-PL", { timeZone: TZ, weekday: "short" });
  return `${weekday} ${formatDay(iso)}, ${formatTime(iso)}`;
}

export type CardTone = "success" | "warning" | "danger" | "info" | "soft" | "neutral" | "outline";

/** Drugi wiersz i plakietka karty Tablicy. */
export function cardStatus(card: OwnHiringCard, now: Date): { line: string; badge: string; tone: CardTone } {
  const experience = card.role ? `${card.role} · ${formatMonths(card.months)}` : "Bez odczytanej roli";
  switch (card.stage) {
    case "new":
      return { line: experience, badge: card.source ?? "Ogłoszenie", tone: "soft" };
    case "invited": {
      if (card.replied_at) return { line: experience, badge: "Odpisał(a) mailem", tone: "info" };
      const due = card.response_due_at ? new Date(card.response_due_at) : null;
      const lastDay = due !== null && due.getTime() - now.getTime() < 24 * 3600 * 1000;
      return {
        line: experience,
        badge: lastDay ? "Ostatni dzień" : due ? `Czeka do ${formatDueDay(due.toISOString())}` : "Czeka",
        tone: lastDay ? "warning" : "outline",
      };
    }
    case "no_response":
      return { line: experience, badge: "Do decyzji", tone: "warning" };
    case "assistant":
      return card.callback_at
        ? { line: experience, badge: `Telefon ${formatWhen(card.callback_at)}`, tone: "info" }
        : { line: experience, badge: `Próba ${card.call_attempts + 1} z 3`, tone: "outline" };
    case "teams":
    case "office": {
      if (card.needs_decision) return { line: "Po rozmowie", badge: "Wpisz decyzję", tone: "danger" };
      const when = card.booking ? formatWhen(card.booking.start) : "Bez terminu";
      if (card.booking?.sync_status === "failed") {
        return { line: when, badge: "Spotkanie do założenia", tone: "warning" };
      }
      if (card.stage === "office") return { line: when, badge: "Biuro", tone: "neutral" };
      return {
        line: when,
        badge: card.booking?.via === "link" ? "Z linku" : "Przez telefon",
        tone: card.booking?.via === "link" ? "success" : "neutral",
      };
    }
    case "contract":
      return {
        line: card.contract_sent_at ? `Wysłana ${formatDay(card.contract_sent_at)}` : "Wysłana",
        badge: "Czeka na podpis",
        tone: "neutral",
      };
    case "signed":
      return {
        line: experience,
        badge: card.signed_at ? `Podpisana ${formatDay(card.signed_at)}` : "Podpisana",
        tone: "success",
      };
    default:
      return { line: experience, badge: "Zamknięte", tone: "outline" };
  }
}
