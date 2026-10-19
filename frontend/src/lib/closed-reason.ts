/**
 * Powód zamknięcia karty w rekrutacji — ramka w panelu osoby i linia na
 * karcie w „Odrzuconych” i „Rezygnacjach” (prośba rekrutera, D1–D3
 * z 19.10.2026). Do tej daty powód było widać tylko w profilu kandydata
 * (zakładka „Rekrutacje”), choć kolumna obiecywała „powody w doku”.
 *
 * Wyłącznie z pól karty Tablicy: etykieta powodu i kto zamknął liczy serwer
 * (`rejection_reason_name`, `closed_by_name`), komentarz z okna odrzucenia
 * to `notes` etapu. Niczego nie zgadujemy — brak powodu mówimy wprost.
 */

/** Lustro `rejection_reason_labels` („legacy_unknown”) — karty z Traffita. */
export const LEGACY_UNKNOWN_REASON_LABEL = "Powód nieznany (import z Traffita)";

export interface ClosedReasonSource {
  stage: string;
  rejection_reason_name?: string | null;
  closed_by_name?: string | null;
  notes?: string | null;
  moved_at?: string | null;
}

export interface ClosedReason {
  kind: "rejected" | "withdrawn";
  /** „Odrzucony” albo „Rezygnacja” — początek ramki. */
  verb: string;
  /** Etykieta powodu; `null` = nie zapisano. */
  reason: string | null;
  /** Tekst do wyświetlenia w miejscu powodu (także, gdy go nie ma). */
  reasonText: string;
  /** Powód nieznany: nie zapisano albo karta z importu Traffita. */
  unknown: boolean;
  comment: string | null;
  by: string | null;
  at: string | null;
  /** Odrzucenie z powodem = czerwień; rezygnacja i brak powodu = szarość. */
  tone: "danger" | "neutral";
}

export function closedReason(item: ClosedReasonSource): ClosedReason | null {
  if (item.stage !== "rejected" && item.stage !== "withdrawn") return null;
  const kind = item.stage;
  const reason = item.rejection_reason_name?.trim() || null;
  const unknown = reason == null || reason === LEGACY_UNKNOWN_REASON_LABEL;
  return {
    kind,
    verb: kind === "rejected" ? "Odrzucony" : "Rezygnacja",
    reason,
    reasonText: reason ?? "powód nie został zapisany",
    unknown,
    comment: item.notes?.trim() || null,
    by: item.closed_by_name?.trim() || null,
    at: item.moved_at ?? null,
    tone: kind === "rejected" && !unknown ? "danger" : "neutral",
  };
}
