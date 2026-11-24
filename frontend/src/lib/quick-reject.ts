/**
 * Odrzucenie jednym kliknięciem w panelu osoby (decyzja Artura 23.11.2026).
 *
 * Pod rzędem akcji panelu stoi „Odrzuć:” z trzema najczęstszymi powodami
 * zalogowanej osoby z 30 dni (`GET /api/pipeline/my-quick-reject-reasons`).
 * Klik odrzuca jak „Potwierdź” w oknie przy „Odrzucamy my” — ten sam ruch
 * (`usePipelineMove.deferReject`), z 10 s na „Cofnij” jak strzałka „→” (D7).
 * Zasady: docs/claude/rekrutacja-tablica/odrzucenie-jednym-kliknieciem.md.
 */
import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { AutofillLearnedFrom } from "@/lib/autofill-feedback";
import type { BoardColumnKey } from "@/lib/board-stages";
import { closeReason, closeReasonFits, type CloseReasonKey } from "@/lib/close-reasons";

export interface QuickRejectReasonRow {
  key: string;
  count: number;
  source: "mine" | "team";
}

export interface QuickRejectReasonsResponse {
  reasons: QuickRejectReasonRow[];
  since: string;
}

/** Powód w wierszu „Odrzuć:”. `opensWindow` — klik otwiera okno z tym powodem. */
export interface QuickRejectChip {
  key: CloseReasonKey;
  label: string;
  opensWindow: boolean;
  source: "mine" | "team";
}

/**
 * Powody, przy których okno pyta o coś jeszcze: „Za droga” — ile osoba teraz
 * chce (`nowa-stawka-przy-odrzuceniu-za-drogo.md`, nowe minimum w profilu),
 * „Lokalizacja lub tryb pracy” — ile dni w biurze (bez tego serwer odda 422).
 * Chip otwiera wtedy okno z zaznaczonym powodem zamiast odrzucać od razu.
 */
export const QUICK_REJECT_OPENS_WINDOW: ReadonlySet<CloseReasonKey> = new Set([
  "too_expensive",
  "location_mode",
]);

/** Opis obowiązkowy — takich powodów w skrócie nie ma nigdy. */
const NEEDS_DESCRIPTION: ReadonlySet<CloseReasonKey> = new Set(["other", "hm_already_interviewed"]);

export const QUICK_REJECT_LIMIT = 3;

/**
 * Wiersz „Odrzuć:” stoi tylko w „Nowych” i „Screeningu”: tam mail odrzucenia
 * nie wychodzi (`not_client_visible`), a okno nie ma pytań o umowę, rozmowę
 * u klienta ani odpowiedź na ofertę. Od „Zweryfikowanego” odrzucenie zostaje
 * w oknie (mail do kandydata, powody klienta).
 */
export function quickRejectAllowed(column: BoardColumnKey | null | undefined): boolean {
  return column === "new" || column === "screening";
}

/** Odpowiedź serwera → chipy: tylko znane powody, które wybieramy my, bez opisu. */
export function quickRejectChips(rows: readonly QuickRejectReasonRow[] | undefined): QuickRejectChip[] {
  const out: QuickRejectChip[] = [];
  for (const row of rows ?? []) {
    const reason = closeReason(row.key as CloseReasonKey);
    if (!reason || NEEDS_DESCRIPTION.has(reason.key)) continue;
    if (!closeReasonFits(reason, "recruiter", true)) continue;
    if (out.some((chip) => chip.key === reason.key)) continue;
    out.push({
      key: reason.key,
      label: reason.label,
      opensWindow: QUICK_REJECT_OPENS_WINDOW.has(reason.key),
      source: row.source,
    });
    if (out.length >= QUICK_REJECT_LIMIT) break;
  }
  return out;
}

/**
 * „Skąd to wiesz?” przy osobie od systemu — okno pyta, skrót nie może.
 * W „Nowych” rekruter odrzuca po lekturze profilu (mediana 35 s), w
 * „Screeningu” po rozmowie. Tak samo domyślnie pyta porcja dnia („profile”).
 */
export function quickRejectLearnedFrom(column: BoardColumnKey | null | undefined): AutofillLearnedFrom {
  return column === "screening" ? "call" : "profile";
}

/** „Odrzucono: Anna Nowak · Za mało doświadczenia · otwarta: Jan Kowalski”. */
export function quickRejectMessage(args: {
  name: string;
  reasonLabel: string;
  next: string | null;
  queueName: string | null;
}): string {
  const tail = args.next
    ? `otwarta: ${args.next}`
    : args.queueName
      ? `to była ostatnia osoba w kolejce „${args.queueName}”`
      : "to była ostatnia osoba w kolejce";
  return `Odrzucono: ${args.name} · ${args.reasonLabel} · ${tail}`;
}

export const QUICK_REJECT_QUERY_KEY = ["pipeline", "my-quick-reject-reasons"] as const;

/** Najczęstsze powody zalogowanej osoby. Awaria = brak wiersza (zostaje „Odrzuć z powodem”). */
export function useQuickRejectReasons(enabled: boolean) {
  return useQuery({
    queryKey: QUICK_REJECT_QUERY_KEY,
    queryFn: async () =>
      (await api.get<QuickRejectReasonsResponse>("/api/pipeline/my-quick-reject-reasons")).data,
    enabled,
    staleTime: 10 * 60_000,
    retry: false,
  });
}
