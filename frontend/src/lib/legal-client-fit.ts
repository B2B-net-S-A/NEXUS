// Zgodność umów B2B z umową ramową klienta (asystent prawny, część G,
// 25.11.2026) — czyste funkcje panelu w Generatorze i okna szczegółów.
// Stan ustalenia i liczby liczy serwer; tu tylko kolejność, etykiety
// i dopisanie zdania do listy zmian aneksu „inna zmiana”.

import {
  MAX_ANNEX_CHANGES,
  annexChangeRows,
} from "@/lib/annex-changes";
import type { AnnexChangeRow } from "@/lib/api/b2bDocuments";
import type {
  ClientFitFinding,
  ClientFitResponse,
  ClientFitState,
} from "@/lib/api/legalClientFit";

export const CLIENT_FIT_STATE_LABEL: Record<ClientFitState, string> = {
  gap: "Luka",
  decide: "Do decyzji",
  ok: "Zgodne",
};

const STATE_ORDER: Record<ClientFitState, number> = { gap: 0, decide: 1, ok: 2 };

/** Luki, potem „do decyzji”, na końcu zgodne; w grupie kolejność serwera. */
export function sortFindings(findings: readonly ClientFitFinding[]): ClientFitFinding[] {
  return findings
    .map((finding, index) => ({ finding, index }))
    .sort(
      (a, b) =>
        STATE_ORDER[a.finding.state] - STATE_ORDER[b.finding.state] || a.index - b.index,
    )
    .map(({ finding }) => finding);
}

/**
 * Pozycje panelu: wszystkie luki i „do decyzji” oraz JEDNA zgodna (reszta
 * zgodnych tylko w oknie szczegółów — panel ma pokazać, że sprawdzenie
 * patrzyło szerzej, a nie wyliczać wszystko, co się zgadza).
 */
export function panelFindings(findings: readonly ClientFitFinding[]): ClientFitFinding[] {
  const sorted = sortFindings(findings);
  const open = sorted.filter((f) => f.state !== "ok");
  const firstOk = sorted.find((f) => f.state === "ok");
  return firstOk ? [...open, firstOk] : open;
}

export function clientFitTitle(clientName: string): string {
  const name = clientName.trim();
  return name
    ? `Sprawdzone z umową ramową ${name} i przepisami`
    : "Sprawdzone z umową ramową klienta i przepisami";
}

function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return few;
  return many;
}

/** „1 luka”, „2 luki”, „5 luk”. */
export function gapsLabel(n: number): string {
  return `${n} ${plural(n, "luka", "luki", "luk")}`;
}

/** „1 do decyzji” — bez odmiany, ale z liczbą. */
export function decideLabel(n: number): string {
  return `${n} do decyzji`;
}

/** „dotyczy 1 aktywnej umowy B2B” / „3 aktywnych umów B2B”. */
export function affectedLabel(n: number): string {
  return n === 1
    ? "dotyczy 1 aktywnej umowy B2B u klienta"
    : `dotyczy ${n} aktywnych umów B2B u klienta`;
}

export function findingsCountLabel(n: number): string {
  return `${n} ${plural(n, "ustalenie", "ustalenia", "ustaleń")}`;
}

/** Wynik do pokazania jako lista ustaleń — tylko po skończonym sprawdzeniu. */
export function hasResult(data: ClientFitResponse): boolean {
  return data.status === "done";
}

function isBlank(row: AnnexChangeRow): boolean {
  return !row.paragraph.trim() && !row.section.trim() && !row.text.trim();
}

/** Wiersz „własny tekst” listy zmian aneksu z gotowym zdaniem ustalenia. */
export function annexRowFor(text: string): AnnexChangeRow {
  return { op: "free", paragraph: "", section: "", text: text.trim() };
}

/**
 * Dopisuje zdanie do listy zmian aneksu: puste wiersze ustępują (jak gotowe
 * klauzule w `AnnexChangesField`), wpisane zostają, to samo zdanie drugi raz
 * nie wchodzi, a lista nie przekracza limitu aneksu.
 */
export function appendAnnexText(value: unknown, text: string): AnnexChangeRow[] {
  const kept = annexChangeRows(value).filter((row) => !isBlank(row));
  const row = annexRowFor(text);
  if (!row.text || kept.some((r) => r.text.trim() === row.text)) return kept;
  return [...kept, row].slice(0, MAX_ANNEX_CHANGES);
}

/** `?zgodnosc=<id klienta>` w Generatorze aneksów otwiera okno szczegółów. */
export const CLIENT_FIT_URL_PARAM = "zgodnosc";

export function parseClientFitParam(
  params: { get(name: string): string | null } | null | undefined,
): number | null {
  const raw = params?.get(CLIENT_FIT_URL_PARAM)?.trim() ?? "";
  if (!/^\d{1,9}$/.test(raw)) return null;
  const id = Number(raw);
  return id > 0 ? id : null;
}

/** Link z zadania asystenta: kreator aneksu „inna zmiana” i okno ustaleń klienta. */
export function clientFitAnnexHref(clientId: number): string {
  return `/contracts/b2b-generator?tab=annexes&new=annex_custom&${CLIENT_FIT_URL_PARAM}=${clientId}`;
}

/** Czy zdanie ustalenia już stoi w liście zmian aneksu. */
export function annexHasText(value: unknown, text: string | null): boolean {
  if (!text) return false;
  return annexChangeRows(value).some((row) => row.text.trim() === text.trim());
}
