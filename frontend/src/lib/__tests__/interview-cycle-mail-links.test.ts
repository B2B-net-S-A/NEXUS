/**
 * Przyciski z maila (26.10.2026): `?do=<krok>` otwiera okno tylko wtedy, gdy
 * para naprawdę stoi na tym kroku; `?choose=N` wskazuje termin od 1.
 */
import { describe, expect, it } from "vitest";

import { chosenSlotIndex, linkedStepAction, type CycleItem, type SlotRequest } from "@/lib/interview-cycle";

const request: SlotRequest = {
  id: 11,
  status: "awaiting_recruiter",
  slots: [
    { start: "2031-06-12T12:30:00Z", end: "2031-06-12T13:30:00Z" },
    { start: "2031-06-13T08:00:00Z", end: "2031-06-13T09:00:00Z" },
  ],
  chosen_index: null,
  respond_by: null,
  recruiter_id: 7,
  created_by: 1,
  duration_minutes: 60,
  note: null,
  event_id: null,
};

function item(status: SlotRequest["status"]): CycleItem {
  return {
    candidate_id: 5,
    candidate_name: "Anna Test",
    candidate_email: null,
    job_id: 9,
    job_title: "Java Dev",
    client_id: 3,
    client_name: "Klient",
    steps: [
      { key: "slots", label: "", state: "done", at: null, event_id: null, meta: null },
      { key: "choice", label: "", state: "current", at: null, event_id: null, meta: null },
    ],
    current_step: "choice",
    latest_stage: "client_interview",
    slot_request: { ...request, status },
    interview_event_id: null,
    debrief: null,
  } as CycleItem;
}

describe("linkedStepAction", () => {
  it("krok z linku = krok pary → akcja okna", () => {
    const action = linkedStepAction(item("awaiting_recruiter"), "pick", { canManageSlots: false });
    expect(action).toMatchObject({ type: "pick", pair: { candidate_id: 5, job_id: 9 } });
  });

  it("para już dalej (czeka na DL) → bez okna wyboru dla rekrutera", () => {
    expect(linkedStepAction(item("awaiting_dl"), "pick", { canManageSlots: false })).toBeNull();
  });

  it("potwierdzenie tylko dla roli, która potwierdza terminy", () => {
    expect(linkedStepAction(item("awaiting_dl"), "confirm", { canManageSlots: true })?.type).toBe("confirm");
    expect(linkedStepAction(item("awaiting_dl"), "confirm", { canManageSlots: false })).toBeNull();
  });

  it("brak albo nieznany krok → null", () => {
    expect(linkedStepAction(item("awaiting_recruiter"), null, { canManageSlots: false })).toBeNull();
    expect(linkedStepAction(item("awaiting_recruiter"), "approve", { canManageSlots: false })).toBeNull();
  });
});

describe("chosenSlotIndex", () => {
  it.each([
    ["1", 0],
    ["2", 1],
    ["3", null],
    ["0", null],
    ["x", null],
    [null, null],
  ])("choose=%s → %s", (raw, expected) => {
    expect(chosenSlotIndex(raw, request)).toBe(expected);
  });

  it("bez wniosku → null", () => {
    expect(chosenSlotIndex("1", null)).toBeNull();
  });

  it("termin z maila tylko na tym samym wniosku (`req`)", () => {
    expect(chosenSlotIndex("2", request, "11")).toBe(1);
    // Para dostała nowy wniosek po mailu — „termin 2” to inna godzina.
    expect(chosenSlotIndex("2", request, "10")).toBeNull();
  });
});
