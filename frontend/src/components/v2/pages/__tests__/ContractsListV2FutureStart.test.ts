import { describe, expect, it } from "vitest";

import { contractorsCountText } from "@/components/v2/pages/ContractsListV2";
import { listNextSteps, type ListRowFacts } from "@/lib/contract-list-next";

/**
 * Audyt 24.09.2026 (U5): status „Aktywny" niesie też umowy, które dopiero się
 * zaczną. Rejestr liczył je jak pracujące (463 w Firmie, 480 w Kontraktach),
 * a wiersz nie mówił, że osoba jeszcze nie weszła do projektu.
 *
 * Od 20.11.2026 (wariant A) wiersz mówi to w kolumnie „Co dalej” zamiast
 * dopisku „startuje DD.MM” pod statusem — kolumny „Status” już nie ma.
 */
const row = (status: string, start: string | null): ListRowFacts => ({
  status,
  contract_type: "b2b",
  start_date: start,
  client_order_start_date: "2026-09-01",
  client_order_end_date: "2027-06-30",
  rate_client: 150,
});

const startText = (status: string, start: string | null) =>
  listNextSteps(row(status, start), "2026-09-24", { canSeeRates: true }).find((step) => step.id === "start")?.text ?? null;

describe("kontrakty z przyszłym startem", () => {
  it("„Startuje DD.MM.RRRR” tylko przy żywej umowie ze startem po dziś", () => {
    expect(startText("active", "2026-10-01")).toBe("Startuje 01.10.2026 — za 7 dni");
    expect(startText("ending", "2026-09-25")).toBe("Startuje 25.09.2026 — jutro");
    expect(startText("active", "2026-09-24")).toBeNull();
    expect(startText("active", "2026-01-01")).toBeNull();
    expect(startText("draft", "2026-10-01")).toBeNull();
    expect(startText("active", null)).toBeNull();
  });

  it("licznik nagłówka mówi, ile aktywnych umów startuje w przyszłości", () => {
    expect(contractorsCountText(473, 480, true, 17)).toBe(
      "473 kontraktorów / 480 aktywnych kontraktów (w tym 17 z przyszłym startem)",
    );
    expect(contractorsCountText(473, 480, true, 0)).toBe(
      "473 kontraktorów / 480 aktywnych kontraktów",
    );
    // Widok nie tylko obowiązujących umów — dopisek nie ma sensu.
    expect(contractorsCountText(10, 12, false, 3)).toBe("10 osób / 12 kontraktów");
  });
});
