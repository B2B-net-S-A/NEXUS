/**
 * Krajowy Rejestr Zadłużonych przed podpisem umowy B2B (0801, 27.11.2026).
 *
 * KRZ nie ma API, więc NEXUS otwiera portal, kopiuje NIP albo PESEL do
 * schowka, a człowiek zaznacza wynik. PESEL zostaje w przeglądarce: nie idzie
 * do API ani do bazy (decyzja Artura, RODO). Reguła bramki jest po stronie
 * serwera (`services/b2b_contract_generator/krz.py`); tu tylko stan formularza
 * i to, co pokazać przy wierszu.
 */

import type {
  B2BKrzCheckInput,
  B2BKrzEntryKind,
  B2BKrzState,
} from "@/lib/api";

/** Wyszukiwarka podmiotów w portalu publicznym KRZ. Numer wkleja człowiek. */
export const KRZ_PORTAL_URL =
  "https://krz.ms.gov.pl/#!/application/KRZPortalPUB/1.9/KrzRejPubGui.WyszukiwaniePodmiotow?params=JTdCJTdE&seq=0";

export const KRZ_ENTRY_KINDS: readonly { value: B2BKrzEntryKind; label: string }[] = [
  { value: "enforcement", label: "Umorzona egzekucja (bezskuteczna)" },
  { value: "bankruptcy", label: "Upadłość" },
  { value: "consumer_bankruptcy", label: "Upadłość konsumencka" },
  { value: "restructuring", label: "Restrukturyzacja" },
  { value: "business_ban", label: "Zakaz prowadzenia działalności" },
  { value: "alimony", label: "Dłużnik alimentacyjny" },
  { value: "other", label: "Inny wpis" },
];

export const KRZ_NOTE_MAX = 300;

export interface KrzFormState {
  result: "clear" | "entry" | null;
  entryKind: B2BKrzEntryKind | null;
  entryNote: string;
}

export const EMPTY_KRZ_FORM: KrzFormState = {
  result: null,
  entryKind: null,
  entryNote: "",
};

/** Wynik do wysłania; `null`, gdy człowiek jeszcze nie rozstrzygnął. */
export function krzFormToPayload(state: KrzFormState): B2BKrzCheckInput | null {
  if (state.result === "clear") return { result: "clear" };
  if (state.result === "entry" && state.entryKind) {
    const note = state.entryNote.trim().slice(0, KRZ_NOTE_MAX);
    return { result: "entry", entry_kind: state.entryKind, entry_note: note || null };
  }
  return null;
}

/** Stan formularza z zapisanej umowy („Popraw”) albo pusty. */
export function krzFormFromPayload(
  value: Partial<B2BKrzCheckInput> | null | undefined,
): KrzFormState {
  if (!value || (value.result !== "clear" && value.result !== "entry")) {
    return EMPTY_KRZ_FORM;
  }
  return {
    result: value.result,
    entryKind: (value.entry_kind as B2BKrzEntryKind | null | undefined) ?? null,
    entryNote: value.entry_note ?? "",
  };
}

export function digitsOnly(value: string): string {
  return value.replace(/\D/g, "");
}

const PESEL_WEIGHTS = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3] as const;

/** PESEL z poprawną cyfrą kontrolną — podpowiedź przy literówce, nic więcej. */
export function peselLooksValid(value: string): boolean {
  const digits = digitsOnly(value);
  if (digits.length !== 11) return false;
  const sum = PESEL_WEIGHTS.reduce((acc, w, i) => acc + w * Number(digits[i]), 0);
  return (10 - (sum % 10)) % 10 === Number(digits[10]);
}

export type KrzTone = "success" | "warning" | "danger";

export interface KrzBadgeView {
  tone: KrzTone;
  label: string;
}

/** Plakietka przy wierszu rejestru i w panelu osoby. */
export function krzBadge(state: B2BKrzState): KrzBadgeView {
  if (state.result === null) {
    return state.nip_changed
      ? { tone: "warning", label: "KRZ: NIP zmieniony, sprawdź jeszcze raz" }
      : { tone: "warning", label: "KRZ: nie sprawdzono" };
  }
  if (state.result === "clear") return { tone: "success", label: "KRZ: brak wpisów" };
  if (state.decision === "allowed") return { tone: "warning", label: "KRZ: wpis, dopuszczona" };
  if (state.decision === "rejected") return { tone: "danger", label: "KRZ: wpis, niedopuszczona" };
  return { tone: "danger", label: "KRZ: wpis, decyzja DL" };
}

/** „Sprawdzono 27.11.2026, 21:04 · Dominik Z.” — kiedy i kto zaznaczył wynik. */
export function krzCheckedLine(state: B2BKrzState): string | null {
  if (!state.checked_at) return null;
  const when = new Date(state.checked_at).toLocaleString("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return state.checked_by_name
    ? `Sprawdzono ${when} · ${state.checked_by_name}`
    : `Sprawdzono ${when}`;
}

/** Kto czeka z decyzją — „Czeka na decyzję: Anna K., Jan N.”. */
export function krzWaitingLine(state: B2BKrzState): string | null {
  if (state.result !== "entry" || state.decision !== null) return null;
  if (state.decider_names.length === 0) return "Czeka na decyzję Delivery Leada.";
  return `Czeka na decyzję: ${state.decider_names.join(", ")}.`;
}

export interface KrzDialogLine {
  tone: "success" | "warning";
  title: string;
  description: string;
}

/** Linijka KRZ w oknie „Sprawdzenie w rejestrze” przed „Pobierz DOCX”. */
export function krzDialogLine(state: KrzFormState): KrzDialogLine {
  const payload = krzFormToPayload(state);
  if (payload?.result === "clear") {
    return {
      tone: "success",
      title: "KRZ: brak wpisów",
      description: "Wynik zapisze się przy umowie.",
    };
  }
  if (payload?.result === "entry") {
    const kind = KRZ_ENTRY_KINDS.find((k) => k.value === payload.entry_kind)?.label;
    return {
      tone: "warning",
      title: `KRZ: ${kind ?? "wpis"}`,
      description:
        "Pobierzesz DOCX, a do podpisu umowa pójdzie po decyzji Delivery Leada klienta.",
    };
  }
  return {
    tone: "warning",
    title: "KRZ: nie sprawdzono",
    description:
      "Pobierzesz DOCX, ale „Wyślij do podpisu” i „Oznacz jako podpisaną” poczekają na wynik. Sprawdzisz go w kroku „Partner” albo w rejestrze umów.",
  };
}
