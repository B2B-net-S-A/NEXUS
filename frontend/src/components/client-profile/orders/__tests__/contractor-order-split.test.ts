/**
 * Podział osi zamówień kontraktora (bieżące / przyszłe / historia) i bramka
 * „Zakończ współpracę" — reguły z `contractor-order-row`, które czytają wiersz
 * tabeli i panel `ContractorOrderPanel`. Do 29.09.2026 żyły (i były tu
 * testowane) w `components/OrdersAndContractsTab.tsx`.
 */
import { describe, expect, it } from "vitest";

import {
  canTerminateContractor,
  splitOrders,
} from "@/components/client-profile/orders/contractor-order-row";
import type { ClientOrderRead } from "@/lib/api/dlPortal";

/** Local YYYY-MM-DD offset from today, matching the component's todayLocalISO. */
function localISO(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function makeOrder(partial: Partial<ClientOrderRead> & { id: number; title: string }): ClientOrderRead {
  return {
    client_id: 7,
    contract_id: 529,
    job_id: null,
    framework_contract_id: null,
    description: null,
    status: "active",
    start_date: null,
    end_date: null,
    rate_client: null,
    total_value: null,
    currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    candidate_id: 99,
    candidate_name: "Tomasz Sadowski",
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
    ...partial,
  };
}

const ACTIVE = makeOrder({
  id: 1,
  title: "45767",
  order_type: "md",
  start_date: localISO(-30),
  end_date: null,
  rate_client: 180,
});
const FUTURE = makeOrder({
  id: 2,
  title: "3320",
  order_type: "cost",
  start_date: localISO(30),
  end_date: localISO(60),
  rate_client: 190,
});
const HISTORY = makeOrder({
  id: 3,
  title: "OLD-1",
  order_type: "periodic",
  status: "completed",
  start_date: localISO(-400),
  end_date: localISO(-40),
  rate_client: 150,
  // Ticket #4: etykieta "Job: …" ma NIE renderować się mimo obecnej wartości.
  job_title: "Specjalista: Engineer DevOps",
});

describe("splitOrders", () => {
  it("promotes the latest started order and queues the future one", () => {
    const { activeOrder, futureOrders, historyOrders } = splitOrders([
      FUTURE,
      ACTIVE,
      HISTORY,
    ]);
    expect(activeOrder?.id).toBe(ACTIVE.id);
    expect(futureOrders.map((o) => o.id)).toEqual([FUTURE.id]);
    expect(historyOrders.map((o) => o.id)).toEqual([HISTORY.id]);
  });

  it("treats a start_date of today as already active (not future)", () => {
    const startsToday = makeOrder({ id: 5, title: "T", start_date: localISO(0) });
    const { activeOrder, futureOrders } = splitOrders([startsToday]);
    expect(activeOrder?.id).toBe(5);
    expect(futureOrders).toHaveLength(0);
  });

  it("falls back to the soonest upcoming order when nothing has started", () => {
    const soon = makeOrder({ id: 6, title: "soon", start_date: localISO(10) });
    const later = makeOrder({ id: 7, title: "later", start_date: localISO(40) });
    const { activeOrder, futureOrders } = splitOrders([later, soon]);
    expect(activeOrder?.id).toBe(6);
    expect(futureOrders.map((o) => o.id)).toEqual([7]);
  });

  it("keeps cancelled orders out of active/future and in history", () => {
    const cancelled = makeOrder({
      id: 8,
      title: "x",
      status: "cancelled",
      start_date: localISO(-5),
    });
    const { activeOrder, futureOrders, historyOrders } = splitOrders([
      ACTIVE,
      cancelled,
    ]);
    expect(activeOrder?.id).toBe(ACTIVE.id);
    expect(futureOrders).toHaveLength(0);
    expect(historyOrders.map((o) => o.id)).toEqual([8]);
  });

  it("wybiera zamówienie, które trwa dziś, a nie zamknięty duplikat tego samego okresu", () => {
    // Kontrakt #479 (zgłoszenie 29.09.2026): stary wiersz z importu Excela
    // (`completed`) stoi PRZED aktywnym, bo API sortuje po starcie, a starty
    // są równe. Zamknięty wiersz w slocie chował „Zakończ zamówienie".
    const stale = makeOrder({
      id: 15,
      title: "K/2026/197070/ŁO/477/26APP",
      status: "completed",
      start_date: "2026-07-01",
      end_date: "2026-09-30",
    });
    const live = makeOrder({
      id: 464,
      title: "K/2026/197070/ŁO/477/26APP",
      status: "active",
      start_date: "2026-07-01",
      end_date: "2026-09-30",
    });
    const { activeOrder, futureOrders, historyOrders } = splitOrders(
      [stale, live],
      "2026-09-29",
    );
    expect(activeOrder?.id).toBe(464);
    expect(futureOrders).toHaveLength(0);
    expect(historyOrders.map((o) => o.id)).toEqual([15]);
  });

  it("nowszy start nie przebija bieżącego zamówienia, gdy nowsze już się skończyło", () => {
    const endedLater = makeOrder({
      id: 20,
      title: "ENDED",
      status: "active",
      start_date: localISO(-10),
      end_date: localISO(-2),
    });
    const running = makeOrder({
      id: 21,
      title: "RUNNING",
      status: "active",
      start_date: localISO(-100),
      end_date: null,
    });
    expect(splitOrders([endedLater, running]).activeOrder?.id).toBe(21);
  });

  it("bez bieżącego zamówienia zostaje ostatnie rozpoczęte (historia osoby)", () => {
    const newest = makeOrder({
      id: 30,
      title: "NEWEST",
      status: "completed",
      start_date: localISO(-40),
      end_date: localISO(-10),
    });
    const older = makeOrder({
      id: 31,
      title: "OLDER",
      status: "completed",
      start_date: localISO(-100),
      end_date: localISO(-50),
    });
    const { activeOrder, historyOrders } = splitOrders([newest, older]);
    expect(activeOrder?.id).toBe(30);
    expect(historyOrders.map((o) => o.id)).toEqual([31]);
  });
});

describe("canTerminateContractor", () => {
  it("przepuszcza wszystko poza `ended` i `void`", () => {
    for (const status of [
      "draft",
      "ready_for_signature",
      "active",
      "ending",
    ]) {
      expect(canTerminateContractor(status)).toBe(true);
    }
    expect(canTerminateContractor("ended")).toBe(false);
    expect(canTerminateContractor("void")).toBe(false);
  });

  it("brak statusu traktuje jak stan nieterminalny", () => {
    // `contract_status` jest po stronie API nullowalne (`contract.status.value
    // if contract else None`). Ukrycie przycisku przy braku danych zostawiłoby
    // kontraktora bez jedynej drogi zakończenia — awaria odczytu nie może
    // czytać się jak stan terminalny.
    expect(canTerminateContractor(null)).toBe(true);
  });
});
