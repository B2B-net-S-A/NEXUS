import { describe, expect, it } from "vitest";

import { prepResponseView } from "@/lib/prep-response";

const NOW = new Date("2031-10-06T08:00:00.000Z");
const BASE = {
  start: "2031-10-09T08:00:00.000Z",
  status: "scheduled" as const,
  proposed_start: null,
  proposed_end: null,
};

describe("prepResponseView", () => {
  it("nic, gdy prep odwołany albo odpowiedzi jeszcze nie sprawdzano", () => {
    expect(prepResponseView({ ...BASE, candidate_response: null }, NOW)).toBeNull();
    expect(
      prepResponseView({ ...BASE, candidate_response: "accepted", status: "cancelled" }, NOW),
    ).toBeNull();
  });

  it("przyjął / może / odrzucił", () => {
    expect(prepResponseView({ ...BASE, candidate_response: "accepted" }, NOW)).toMatchObject({
      label: "Kandydat przyjął",
      tone: "ok",
    });
    expect(prepResponseView({ ...BASE, candidate_response: "tentative" }, NOW)?.tone).toBe("info");
    expect(prepResponseView({ ...BASE, candidate_response: "declined" }, NOW)).toMatchObject({
      label: "Kandydat odrzucił",
      proposed: null,
    });
  });

  it("propozycja kandydata wygrywa z samą odmową i niesie termin", () => {
    const view = prepResponseView(
      {
        ...BASE,
        candidate_response: "declined",
        proposed_start: "2031-10-09T11:00:00.000Z",
        proposed_end: "2031-10-09T11:45:00.000Z",
      },
      NOW,
    );
    expect(view?.label).toMatch(/^Kandydat proponuje: .+ · \d{1,2}:\d{2}$/);
    expect(view?.proposed).toEqual({
      start: "2031-10-09T11:00:00.000Z",
      end: "2031-10-09T11:45:00.000Z",
    });
  });

  it("bez odpowiedzi: spokojnie, a dobę przed prepem — ostrzeżenie", () => {
    expect(prepResponseView({ ...BASE, candidate_response: "none" }, NOW)?.tone).toBe("muted");
    expect(
      prepResponseView(
        { ...BASE, candidate_response: "none", start: "2031-10-06T20:00:00.000Z" },
        NOW,
      ),
    ).toMatchObject({ label: "Brak odpowiedzi kandydata", tone: "wait" });
  });
});
