import { describe, expect, it } from "vitest";

import { buildClientAttention, contractAttention, daysUntil } from "@/components/clients/ClientAttention";
import type { CalendarItem } from "@/lib/api/client-reports";

function report(overrides: Partial<CalendarItem>): CalendarItem {
  return {
    due: null,
    carried: false,
    definition_id: 1,
    client_id: 10,
    client_name: "Klient",
    report: "Raport miesięczny",
    family: "management",
    period_key: "2026-11",
    period_label: "listopad 2026",
    preparer_label: "Delivery Lead",
    preparer_is_me: false,
    state: "todo",
    has_generator: false,
    ...overrides,
  };
}

describe("„Wymaga uwagi” na liście klientów", () => {
  it("otwarte raporty miesiąca dostają znacznik z linkiem do Raportów klienta; wysłane nie", () => {
    const map = buildClientAttention(
      [
        report({ definition_id: 1, state: "no_date" }),
        report({ definition_id: 2, state: "overdue", client_id: 11 }),
        report({ definition_id: 3, state: "sent", client_id: 12 }),
      ],
      [],
    );
    expect(map.get(10)?.map((item) => [item.label, item.tone, item.href])).toEqual([
      ["Raport: termin do ustalenia", "neutral", "/clients/10?tab=raporty"],
    ]);
    expect(map.get(11)?.[0].tone).toBe("danger");
    expect(map.has(12)).toBe(false);
  });

  it("kluczowa relacja bez kontaktu albo po 30 dniach — tak jak kropka „Ostatni kontakt”", () => {
    const map = buildClientAttention([], [
      { contact_id: 1, name: "Anna", client_id: 20, days_since_personal_touchpoint: null },
      { contact_id: 2, name: "Bartek", client_id: 21, days_since_personal_touchpoint: 30 },
      { contact_id: 3, name: "Celina", client_id: 22, days_since_personal_touchpoint: 45 },
      { contact_id: 4, name: "Damian", client_id: 23, days_since_personal_touchpoint: 120 },
    ]);
    expect(map.get(20)?.[0]).toMatchObject({ label: "Relacja bez kontaktu", tone: "neutral", note: "Anna" });
    expect(map.has(21)).toBe(false);
    expect(map.get(22)?.[0]).toMatchObject({ label: "Relacja: 45 dni bez kontaktu", tone: "warning" });
    expect(map.get(23)?.[0].tone).toBe("danger");
    expect(map.get(23)?.[0].href).toBe("/clients/23?tab=kontakty");
  });

  it("umowa ramowa: wygasła albo kończy się w 90 dni; bezterminowa i dalsza — nic", () => {
    const today = "2026-11-18";
    expect(contractAttention({ client_id: 5, scope_id: 9, expiry_date: "2026-03-29" }, today)).toMatchObject({
      label: "Umowa wygasła",
      tone: "danger",
      href: "/clients/5?tab=umowy-ramowe",
    });
    expect(contractAttention({ client_id: 5, scope_id: 9, expiry_date: "2027-01-01" }, today)).toMatchObject({
      label: "Umowa kończy się za 44 dni",
      tone: "warning",
    });
    expect(contractAttention({ client_id: 5, scope_id: 9, expiry_date: "2027-02-17" }, today)).toBeNull();
    expect(contractAttention({ client_id: 5, scope_id: 9, expiry_date: null }, today)).toBeNull();
  });

  it("dni liczy w kalendarzu, bez godzin i stref", () => {
    expect(daysUntil("2026-11-19", "2026-11-18")).toBe(1);
    expect(daysUntil("2026-11-18T23:30:00Z", "2026-11-18")).toBe(0);
    expect(daysUntil("2026-03-29", "2026-11-18")).toBe(-234);
  });
});
