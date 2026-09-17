import { countPl } from "@/lib/plural-pl";

const ISO_DATE = /\b(\d{4})-(\d{2})-(\d{2})\b/g;

/**
 * Daty w tytułach i treściach powiadomień przychodzą z backendu jako
 * RRRR-MM-DD (UAT M00-B05). Treści NIE zmieniamy w bazie — skaner wygasania
 * deduplikuje alerty po tym sformułowaniu — więc format DD.MM.RRRR nakładamy
 * wyłącznie przy wyświetlaniu.
 */
export function formatNotificationText(text: string | null | undefined): string {
  if (!text) return "";
  return text.replace(ISO_DATE, (_match, year, month, day) => `${day}.${month}.${year}`);
}

/** „Przed chwilą” / „5 min temu” / „3 h temu” / „1 dzień temu” / „5 dni temu”. */
export function notificationTimeAgo(
  iso?: string | null,
  now: number = Date.now(),
): string {
  if (!iso) return "";
  const diff = Math.floor((now - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "Przed chwilą";
  if (diff < 3600) return `${Math.floor(diff / 60)} min temu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h temu`;
  return `${countPl(Math.floor(diff / 86400), "dzień", "dni", "dni")} temu`;
}

/**
 * Przypomnienie nieobecnego kolegi widoczne w zastępstwie — backend podaje
 * `on_behalf_of_name` tylko dla cudzych wierszy. Pole jest opcjonalne w typie
 * odpowiedzi (starsze wdrożenia go nie wysyłają), stąd luźny kształt wejścia.
 */
export function notificationOnBehalfLabel(notification: object): string | null {
  const raw = (notification as { on_behalf_of_name?: unknown }).on_behalf_of_name;
  const name = typeof raw === "string" ? raw.trim() : "";
  return name ? `w zastępstwie za ${name}` : null;
}
