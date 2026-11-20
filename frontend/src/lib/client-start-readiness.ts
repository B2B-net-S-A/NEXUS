// Licznik „Start u klienta: N z M ustalone” (decyzja Artura z 20.11.2026,
// `docs/claude/klienci/start-u-klienta-ustalone.md`).
//
// „Ustalone” znaczy: ktoś to jawnie wybrał. Wartość domyślna się nie liczy,
// bo 20.11.2026 na produkcji żaden klient nie miał pakietu, listy dokumentów
// ani sposobu rozliczenia, a makieta z domyślnymi wartościami pokazywała
// „2 z 5”. Wzory protokołów nie wchodzą: w systemie nie ma żadnego wgranego
// wzoru, więc każdy klient ma „Standard recepcji” bez wyboru.
//
// Licznik liczy tylko części, które osoba ma na ekranie (moduł, uprawnienie),
// i pojawia się od dwóch takich części — przy jednej powtarzałby jej stan.

import { SETTLEMENT_MODES } from "@/components/consultant-portal/portal-model";
import type { SettlementMode } from "@/lib/api/consultant-portal";
import type { EquipmentProvider } from "@/lib/api/equipment";
import { countPl } from "@/lib/plural-pl";

/** Część zakładki z punktu widzenia osoby, która ją ogląda. */
export type StartPart<T> =
  /** Osoba nie ma tej części na ekranie (moduł wyłączony, brak uprawnienia, 403). */
  | { status: "hidden" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; data: T };

export interface StartReadinessInput {
  documents: StartPart<{ count: number; notRequired: boolean }>;
  settlement: StartPart<{ mode: SettlementMode | null }>;
  /** Pakiet klienta: kto daje sprzęt i miejsce pierwszego dnia. */
  pack: StartPart<{ provider: EquipmentProvider; place: string | null }>;
}

export type StartFieldKey = "documents" | "settlement" | "equipment" | "first_day";

export interface StartField {
  key: StartFieldKey;
  label: string;
  settled: boolean;
  /** Co jest ustalone albo czego brakuje, po ludzku. */
  value: string;
}

export type StartReadiness =
  | { show: false }
  | { show: true; settled: number; total: number; fields: StartField[] };

/** Od tylu widocznych części licznik ma sens (przy jednej powtarza jej stan). */
export const MIN_VISIBLE_PARTS = 2;

const PROVIDER_VALUE: Record<EquipmentProvider, string> = {
  nasz: "od nas",
  klienta: "od klienta",
  nieznany: "nie wiadomo",
};

function documentsField(data: { count: number; notRequired: boolean }): StartField {
  const base = { key: "documents" as const, label: "Dokumenty do startu" };
  if (data.count > 0) {
    return {
      ...base,
      settled: true,
      value: `${countPl(data.count, "pozycja", "pozycje", "pozycji")} na liście`,
    };
  }
  if (data.notRequired) return { ...base, settled: true, value: "klient nie wymaga" };
  return { ...base, settled: false, value: "brak listy" };
}

function settlementField(mode: SettlementMode | null): StartField {
  const base = { key: "settlement" as const, label: "Sposób rozliczania" };
  if (mode) return { ...base, settled: true, value: SETTLEMENT_MODES[mode].label };
  return { ...base, settled: false, value: "nie wybrano" };
}

function packFields(data: { provider: EquipmentProvider; place: string | null }): StartField[] {
  const place = data.place?.trim() ?? "";
  return [
    {
      key: "equipment",
      label: "Sprzęt",
      settled: data.provider !== "nieznany",
      value: PROVIDER_VALUE[data.provider],
    },
    {
      key: "first_day",
      label: "Pierwszy dzień",
      settled: place !== "",
      value: place || "nie wpisano miejsca",
    },
  ];
}

export function startReadiness(input: StartReadinessInput): StartReadiness {
  const parts = [input.documents, input.settlement, input.pack];
  // Część w trakcie wczytywania albo z błędem: licznik bez niej zaniżyłby
  // mianownik, więc nie ma go wcale — sama część pokazuje swój błąd.
  if (parts.some((part) => part.status === "loading" || part.status === "error")) {
    return { show: false };
  }
  const visible = parts.filter((part) => part.status === "ready").length;
  if (visible < MIN_VISIBLE_PARTS) return { show: false };
  const fields: StartField[] = [];
  if (input.documents.status === "ready") fields.push(documentsField(input.documents.data));
  if (input.settlement.status === "ready") fields.push(settlementField(input.settlement.data.mode));
  if (input.pack.status === "ready") fields.push(...packFields(input.pack.data));
  return {
    show: true,
    settled: fields.filter((field) => field.settled).length,
    total: fields.length,
    fields,
  };
}
