/**
 * Akceptacja klienta na Tablicy (makiety i decyzje Artura D1–D6, 16.10.2026).
 *
 * Delivery Lead dostawał akceptację od klienta i nie wiedział, gdzie ją
 * zaznaczyć: kolumna nazywała się „Umowa”, a jedynym śladem była mała
 * plakietka „Akceptacja”. Teraz akceptację zaznacza przycisk „Klient
 * zaakceptował” (karta w „Rozmowie u klienta”, panel osoby, werdykt po
 * rozmowie), a karta w kolumnie „Akceptacja i umowa” mówi, kiedy i kto ją
 * zaznaczył. Ruch idzie wspólną ścieżką (`usePipelineMove`), dzwonek
 * „Klient zaakceptował” wysyła serwer.
 *
 * Czysty moduł bez renderu — liczą go karta, nagłówek kolumny, okno i panel.
 */

import type { StageBadgeKey } from "@/lib/board-stages";
import { warsawToday } from "@/lib/warsaw-date";

/** Lustro `_client_acceptance_badge` (`backend/app/api/pipeline.py`). */
export interface ClientAcceptanceBadge {
  stage_id: number;
  /** Dzień akceptacji (RRRR-MM-DD, kalendarz firmy). */
  accepted_on: string | null;
  planned_start_on: string | null;
  marked_at: string | null;
  marked_by_name: string | null;
}

/** Odbiorca dzwonka — `GET /api/pipeline/client-acceptance/recipients`. */
export interface ClientAcceptanceRecipient {
  user_id: number;
  name: string;
  role: "recruiter" | "owner" | "delivery_lead" | "head_of_recruitment";
  role_label: string;
}

/** Co niesie ruch z okna „Klient zaakceptował” (lustro pól `StageMove`). */
export interface ClientAcceptancePayload {
  acceptedOn: string;
  plannedStartOn: string | null;
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** „16.10” z RRRR-MM-DD. */
export function shortDay(iso: string | null | undefined): string | null {
  const match = iso ? DATE_ONLY.exec(iso) : null;
  return match ? `${match[3]}.${match[2]}` : null;
}

/** „01.11.2026” z RRRR-MM-DD. */
export function longDay(iso: string | null | undefined): string | null {
  const match = iso ? DATE_ONLY.exec(iso) : null;
  return match ? `${match[3]}.${match[2]}.${match[1]}` : null;
}

/** „Olga W.” z „Olga Wzorcowa”; jedno słowo zostaje jak jest. */
export function shortPersonName(full: string | null | undefined): string | null {
  const words = full?.trim().split(/\s+/).filter(Boolean) ?? [];
  if (words.length === 0) return null;
  if (words.length === 1) return words[0];
  return `${words[0]} ${words[words.length - 1][0]}.`;
}

/**
 * Wiersz na karcie i w panelu: „✓ Klient zaakceptował · 16.10 · Olga W.”.
 * Bez rodzaju gramatycznego osoby — „zaakceptował” odnosi się do klienta.
 */
export function acceptanceLine(badge: ClientAcceptanceBadge | null | undefined): string | null {
  if (!badge) return null;
  return [
    "✓ Klient zaakceptował",
    shortDay(badge.accepted_on),
    shortPersonName(badge.marked_by_name),
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Pełna treść dla dymka i czytnika ekranu. */
export function acceptanceTitle(badge: ClientAcceptanceBadge | null | undefined): string | null {
  if (!badge) return null;
  const day = longDay(badge.accepted_on);
  const parts = [
    day ? `Klient zaakceptował ${day}` : "Klient zaakceptował",
    badge.marked_by_name ? `zaznaczył(a) ${badge.marked_by_name}` : null,
  ].filter(Boolean);
  const start = longDay(badge.planned_start_on);
  return `${parts.join(" — ")}.${start ? ` Planowany start: ${start}.` : ""}`;
}

export interface ContractStepCounts {
  accepted: number;
  sent: number;
  signed: number;
}

/**
 * Liczniki w nagłówku kolumny „Akceptacja i umowa”: ile osób jest po
 * akceptacji, z wysłaną i z podpisaną umową. Karta bez odznaki (własny etap
 * szablonu w tej kolumnie) liczy się jako zaakceptowana — tam trafia
 * dopiero po akceptacji.
 */
export function contractStepCounts(badges: Iterable<StageBadgeKey | null | undefined>): ContractStepCounts {
  const counts: ContractStepCounts = { accepted: 0, sent: 0, signed: 0 };
  for (const badge of badges) {
    if (badge === "contract_signed") counts.signed += 1;
    else if (badge === "contract_sent") counts.sent += 1;
    else counts.accepted += 1;
  }
  return counts;
}

/** Dymek po zapisie: „Karol Wzorcowy — klient zaakceptował. Dzwonek: Marta N., Ewa T.” */
export function acceptedToast(
  candidateName: string,
  recipients: ReadonlyArray<Pick<ClientAcceptanceRecipient, "name">>,
): string {
  const names = recipients
    .map((r) => shortPersonName(r.name))
    .filter((n): n is string => Boolean(n));
  if (names.length === 0) return `${candidateName} — klient zaakceptował.`;
  // Skrót „Olaf P.” kończy się kropką — bez drugiej na końcu zdania.
  const list = names.join(", ");
  return `${candidateName} — klient zaakceptował. Powiadomienie: ${list}${list.endsWith(".") ? "" : "."}`;
}

export interface AcceptanceFormErrors {
  acceptedOn?: string;
  plannedStartOn?: string;
}

/**
 * Walidacja okna — lustro `assert_client_acceptance_dates` (serwer i tak
 * sprawdza): akceptacja nie z przyszłości, start nie przed akceptacją.
 */
export function validateAcceptance(
  acceptedOn: string,
  plannedStartOn: string,
  today: string = warsawToday(),
): AcceptanceFormErrors {
  const errors: AcceptanceFormErrors = {};
  if (!DATE_ONLY.test(acceptedOn)) {
    errors.acceptedOn = "Podaj datę akceptacji.";
  } else if (acceptedOn > today) {
    errors.acceptedOn = "Data akceptacji nie może być z przyszłości.";
  }
  if (plannedStartOn) {
    if (!DATE_ONLY.test(plannedStartOn)) {
      errors.plannedStartOn = "Podaj datę w formacie dzień, miesiąc, rok.";
    } else if (DATE_ONLY.test(acceptedOn) && plannedStartOn < acceptedOn) {
      errors.plannedStartOn = "Start nie może wypaść przed akceptacją.";
    }
  }
  return errors;
}
