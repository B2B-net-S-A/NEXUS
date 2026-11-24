// Wypowiedzenia z poczty (decyzje Artura 23.11.2026): co karta zrobi po kliknięciu.
// Karta nie zapisuje niczego sama — woła istniejące trasy kontraktu i zamówienia,
// a potem zapisuje decyzję (`POST /api/back-office/notices/{id}/decision`).

import type { NoticeDetail } from "@/lib/api/back-office";

export type NoticeChoice = "confirm" | "shorten_order" | "keep_order" | "withdraw";

export interface NoticeRequest {
  method: "post" | "patch";
  url: string;
  body: Record<string, unknown>;
}

export interface NoticeAction {
  choice: NoticeChoice;
  label: string;
  /** Główny przycisk karty. */
  primary: boolean;
  /** Trasa kontraktu albo zamówienia wołana przed decyzją (brak = sama decyzja). */
  request: NoticeRequest | null;
  /** Co zapisujemy w decyzji (ślad w sprawie). */
  applied: Record<string, unknown>;
  /** Kroki pokazane pod „Po kliknięciu”. */
  effects: string[];
}

export function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

/** Przyciski dla rodzaju propozycji, z datą wybraną przez człowieka. */
export function noticeActions(detail: NoticeDetail, lastDay: string | null): NoticeAction[] {
  const contract = detail.contract;
  const order = detail.order;
  if (!contract) return [];

  if (detail.kind === "consultant_notice") {
    if (contract.terminated_at || contract.agreement_termination_mode) {
      // Zakończenie wpisane już ręcznie (np. #339 z 12.11): karta niczego nie
      // zapisuje drugi raz, tylko przypina mail do kontraktu.
      return [
        {
          choice: "confirm",
          label: "Potwierdź — zakończenie już jest w kontrakcie",
          primary: true,
          request: null,
          applied: { already_recorded: true, last_day: contract.terminated_at ?? contract.end_date },
          effects: [
            `Kontrakt ma już zakończenie (${dayLabel(contract.terminated_at ?? contract.end_date)}) — bez zmian`,
            "Mail zostaje przy kontrakcie, a ta sprawa zamyka się z notatką",
          ],
        },
      ];
    }
    if (!lastDay || !detail.delivered_on) return [];
    const mode = detail.agreement ? "mutual_agreement" : "notice";
    return [
      {
        choice: "confirm",
        label: detail.agreement ? "Potwierdź porozumienie" : "Potwierdź wypowiedzenie",
        primary: true,
        request: {
          method: "post",
          url: `/api/contracts/${contract.id}/terminate`,
          body: {
            termination_reason: detail.agreement ? "mutual_agreement" : "consultant_resigned",
            terminated_at: lastDay,
            // Rozwiązanie umowy zapisuje się tylko przy B2B (trasa odmawia innym).
            ...(contract.contract_type === "b2b"
              ? {
                  agreement_termination: {
                    mode,
                    party: "consultant",
                    signed_on: detail.delivered_on,
                    last_day: lastDay,
                  },
                }
              : {}),
          },
        },
        applied: { last_day: lastDay, delivered_on: detail.delivered_on, mode },
        effects: [
          `Rozwiązanie umowy w kontrakcie: ${detail.agreement ? "porozumienie" : "wypowiedzenie"} konsultanta, złożone ${dayLabel(detail.delivered_on)}, ostatni dzień ${dayLabel(lastDay)}`,
          "Kontrakt przechodzi na „Kończący się” — ta sama trasa co „Zakończ współpracę”",
          order
            ? `Linia zamówienia ${order.title} skraca się do ostatniego dnia umowy (dziś do ${dayLabel(order.end_date)})`
            : "Kontrakt nie ma otwartej linii zamówienia",
          "Sprawa wyjścia od razu, z krokami: dostępy, sprzęt, ostatnie rozliczenie",
          "Ta sprawa z maila zamyka się z notatką, co z niej wynikło",
        ],
      },
    ];
  }

  if (detail.kind === "client_termination" || detail.kind === "date_change") {
    const target = detail.kind === "client_termination" ? detail.client_end_date : lastDay;
    const actions: NoticeAction[] = [];
    // Koniec z CPro Nordei (koniec, nieprzedłużenie, internalizacja): potwierdzenie
    // otwiera sprawę wyjścia z wybranym dniem — benefity, sprzęt, dostępy, rozliczenie.
    const exitEffect = (day: string | null | undefined): string[] =>
      detail.kind === "client_termination" && detail.cpro_event && detail.cpro_event !== "changes"
        ? [
            day
              ? `Sprawa wyjścia z ostatnim dniem ${dayLabel(day)}: decyzja o przepięciu, benefity (rezygnacja do 19.), sprzęt z rejestru, dostępy, ostatnie rozliczenie`
              : "Sprawa wyjścia nie powstanie bez daty końca zamówienia",
            ...(detail.cpro_event === "internalization"
              ? ["Internalizacja: porozumienie ze zdjęciem zakazu konkurencji"]
              : []),
          ]
        : [];
    if (order && target && target !== order.end_date) {
      actions.push({
        choice: "shorten_order",
        label: `Ustaw koniec linii ${order.title} na ${dayLabel(target)}`,
        primary: true,
        request: {
          method: "patch",
          url: `/api/clients/${order.client_id}/orders/${order.id}`,
          body: { end_date: target },
        },
        applied: { order_end_date: target, previous_order_end_date: order.end_date, choice: "shorten_order" },
        effects: [
          `Linia zamówienia ${order.title}: ${dayLabel(order.end_date)} → ${dayLabel(target)}`,
          "Umowa konsultanta bez zmian — jej datę zmienia „Zakończ współpracę” albo „Cofnij zakończenie” na kontrakcie",
          ...exitEffect(target),
        ],
      });
    }
    actions.push({
      choice: "keep_order",
      label: order ? `Zostaw ${dayLabel(order.end_date)}` : "Zapisz bez zmian",
      primary: actions.length === 0,
      request: null,
      applied: { choice: "keep_order", order_end_date: order?.end_date ?? null },
      effects: [
        "Nic się nie zmienia; w sprawie zostaje ślad, kto i na podstawie którego maila zdecydował",
        ...exitEffect(order?.end_date ?? target),
      ],
    });
    return actions;
  }

  if (detail.kind === "withdrawal") {
    return [
      {
        choice: "withdraw",
        label: "Wycofaj wypowiedzenie",
        primary: true,
        request: {
          method: "post",
          url: `/api/contracts/${contract.id}/notice-withdrawal`,
          body: { end_date: null, note: "Wycofanie wypowiedzenia z maila (back office)." },
        },
        applied: { choice: "withdraw" },
        effects: [
          "Kontrakt wraca na „Aktywny”, umowa bezterminowo (akcja „Wycofaj wypowiedzenie” z Aneksów)",
          "Zakończony kontrakt wraca tą samą drogą co „Cofnij zakończenie”, łącznie z zamówieniami",
          "Sprawa wyjścia zamyka się automatycznie",
        ],
      },
    ];
  }
  return [];
}

/** Tekst przycisku „to nie…” dla rodzaju propozycji. */
export const REJECT_LABELS: Record<NoticeDetail["kind"], string> = {
  consultant_notice: "To nie wypowiedzenie",
  client_termination: "To nie koniec zamówienia",
  date_change: "To nie zmiana daty",
  withdrawal: "To nie wycofanie",
};
