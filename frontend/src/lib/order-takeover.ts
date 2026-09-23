// Przypisanie osoby ze szkicu do zamówienia i przejęcie pozostałych MD
// (ticket 09.2026). Autorytetem jest serwer (`app/services/order_line_takeover.py`)
// — tu liczymy wyłącznie PODGLĄD, który DL widzi przed zapisem, tą samą regułą:
//
// * pula w MD → pozostałe MD przechodzą 1:1 (bez przelicznika),
// * pula w kwocie → „Pozostało X MD × stawka odchodzącego = kwota" i dwie
//   opcje: po stawce odchodzącego (X MD) albo po stawce przychodzącego
//   (kwota ÷ stawka przychodzącego, zaokrąglone do 0,1 MD). Żadna nie jest
//   domyślna.

import type {
  MdTransferMethod,
  OrderGroupRead,
  OrderLineRead,
} from "@/lib/api/orderGroups";
import { usesSharedMdPool } from "@/lib/client-order-list";

export const MD_TRANSFER_METHOD_LABELS: Record<MdTransferMethod, string> = {
  one_to_one: "1:1",
  departing_rate: "po stawce osoby odchodzącej",
  incoming_rate: "po stawce osoby przychodzącej",
};

export type TakeoverPoolUnit = "md" | "amount";

export interface TransferOption {
  method: MdTransferMethod;
  /** MD dla nowej osoby; `null` = brak stawki, nie da się policzyć. */
  md: number | null;
}

export interface TransferPreview {
  unit: TakeoverPoolUnit;
  remaining: number;
  /** Pula w kwocie: pozostałe MD × stawka odchodzącego. */
  amount: number | null;
  options: TransferOption[];
}

/** Zaokrąglenie do 0,1 MD (połówki w górę) — lustro `round_to_tenth`. */
export function roundToTenth(value: number): number {
  return Math.round((value + Number.EPSILON) * 10) / 10;
}

export function transferPreview(input: {
  unit: TakeoverPoolUnit | null | undefined;
  remaining: number | null | undefined;
  departingRate: number | null | undefined;
  incomingRate: number | null | undefined;
}): TransferPreview | null {
  const { unit, departingRate, incomingRate } = input;
  if (!unit || input.remaining == null) return null;
  const remaining = Math.max(0, input.remaining);
  if (unit === "md") {
    return {
      unit,
      remaining,
      amount: null,
      options: [{ method: "one_to_one", md: remaining }],
    };
  }
  const amount =
    departingRate != null && departingRate > 0 ? remaining * departingRate : null;
  return {
    unit,
    remaining,
    amount,
    options: [
      { method: "departing_rate", md: remaining },
      {
        method: "incoming_rate",
        md:
          amount != null && incomingRate != null && incomingRate > 0
            ? roundToTenth(amount / incomingRate)
            : null,
      },
    ],
  };
}

/** Metoda, którą wyślemy: pula w MD ma jedną odpowiedź; w kwocie — wybór DL. */
export function effectiveTransferMethod(
  unit: TakeoverPoolUnit | null | undefined,
  chosen: MdTransferMethod | null,
): MdTransferMethod | null {
  if (unit === "md") return "one_to_one";
  if (unit === "amount") {
    return chosen === "departing_rate" || chosen === "incoming_rate" ? chosen : null;
  }
  return null;
}

const plNumber = (value: number) =>
  new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 }).format(value);

/** Stawka kosztowa kontraktu przeliczona na PLN/MD (A6): godzinowa × 8. */
export function contractCostRatePerMd(
  rate: number | null | undefined,
  unit: string | null | undefined,
): { value: number; note: string } | null {
  if (rate == null || rate <= 0) return null;
  if (unit === "hourly") {
    return {
      value: Math.round(rate * 8 * 100) / 100,
      note: `Z kontraktu: ${plNumber(rate)} PLN/h × 8`,
    };
  }
  if (unit === "daily") {
    return { value: rate, note: `Z kontraktu: ${plNumber(rate)} PLN/MD` };
  }
  return null;
}

export interface TakeoverSourceOption {
  group: OrderGroupRead;
  line: OrderLineRead;
  state: "ended" | "leaving";
  departureDate: string | null;
  /** Pozostałe MD, które przejmie nowa osoba (dziś). */
  remaining: number;
}

/** Pozostałe MD osoby odchodzącej: migawka otwartej sprawy albo linia. */
export function sourceRemainingMd(line: OrderLineRead): number {
  const pending =
    line.offboarding_case?.status === "pending" ? line.offboarding_case : null;
  return Math.max(0, pending?.remaining_md_snapshot ?? line.md_remaining ?? 0);
}

/** Osoby, za które można „wejść" — stan liczy serwer (`takeover_source`). */
export function takeoverSources(
  groups: readonly OrderGroupRead[],
): TakeoverSourceOption[] {
  return groups
    .filter(
      (group) =>
        group.status === "active" && !group.is_cost_based && !usesSharedMdPool(group),
    )
    .flatMap((group) =>
      group.lines
        .filter((line) => line.takeover_source && sourceRemainingMd(line) > 0)
        .map((line) => ({
          group,
          line,
          state: line.takeover_source as "ended" | "leaving",
          departureDate: line.departure_date ?? null,
          remaining: sourceRemainingMd(line),
        })),
    );
}

function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1, day + days));
  return next.toISOString().slice(0, 10);
}

/** Data wejścia domyślnie dzień po ostatnim dniu osoby odchodzącej. */
export function defaultEntryDate(
  departureDate: string | null | undefined,
  todayIso: string,
): string {
  return departureDate ? addDays(departureDate, 1) : todayIso;
}

/** „Wolna pula" zamówienia z pulą per osoba: MD zwolnione przez osoby
 *  z zakończoną współpracą, o których nikt jeszcze nie zdecydował. */
export function freePoolMd(group: OrderGroupRead): number {
  return group.lines.reduce((sum, line) => {
    const pending = line.offboarding_case;
    if (pending?.status !== "pending" || pending.uses_shared_md_pool) return sum;
    return sum + Math.max(0, pending.remaining_md_snapshot ?? 0);
  }, 0);
}

/** Aktywne zamówienia, do których osoba może dołączyć (A2). */
export function joinableGroups(
  groups: readonly OrderGroupRead[],
  contractId: number,
): OrderGroupRead[] {
  return groups.filter(
    (group) =>
      (group.status === "active" || group.status === "scheduled") &&
      group.can_add_consultant &&
      !group.lines.some(
        (line) =>
          line.contract_id === contractId &&
          (line.status === "active" || line.status === "draft"),
      ),
  );
}

/** Ile MD ponad wolną pulę (0 = mieści się). */
export function mdOverFreePool(requested: number, free: number): number {
  return Math.max(0, roundToTenth(requested - free));
}
