/**
 * Skróty do ciasnych miejsc: nazwisko („Marta K.”) i termin („30.09”).
 *
 * Do 02.10.2026 moduł składał też linijkę faktów pod tytułem rekrutacji
 * (lokalizacja, budżet, rekruter, DL, hiring manager, obsada). Nagłówek
 * pokazuje dziś trzy wyróżnione fakty (`lib/job-header-facts.ts`), a reszta
 * jest w widoku „Zlecenie i Champion”.
 */

/**
 * „Marta Kowalska" → „Marta K.".
 *
 * Nagłówek ma jedną linię na cztery fakty, więc nazwisko skraca się do
 * inicjału — imię zostaje w całości, bo to po nim rozpoznaje się osobę
 * w rozmowie. Nazwisko jednoczłonowe zostaje jak jest (nie ma czego skracać),
 * wieloczłonowe („Anna Nowak-Kowalska") skraca się do pierwszej litery
 * pierwszego członu, tak jak zapisuje się je w mailu.
 */
export function shortenPersonName(name: string | null | undefined): string | null {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return null;
  const parts = trimmed.split(/\s+/);
  if (parts.length < 2) return trimmed;
  const last = parts[parts.length - 1];
  const initial = last.slice(0, 1).toLocaleUpperCase("pl-PL");
  return `${parts.slice(0, -1).join(" ")} ${initial}.`;
}

/** `2026-09-30` → `30.09`. Rok pomijamy — nagłówek mówi o bieżącej pracy. */
export function formatDeadlineShort(
  deadline: string | null | undefined,
): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(deadline ?? "");
  if (!match) return null;
  const [, , month, day] = match;
  return `${day}.${month}`;
}
