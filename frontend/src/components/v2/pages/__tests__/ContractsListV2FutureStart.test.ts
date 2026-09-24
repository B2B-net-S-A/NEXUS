import { describe, expect, it } from "vitest";

import {
  contractorsCountText,
  futureStartLabel,
} from "@/components/v2/pages/ContractsListV2";

/**
 * Audyt 24.09.2026 (U5): status „Aktywny" niesie też umowy, które dopiero się
 * zaczną. Rejestr liczył je jak pracujące (463 w Firmie, 480 w Kontraktach),
 * a wiersz nie mówił, że osoba jeszcze nie weszła do projektu.
 */
describe("kontrakty z przyszłym startem", () => {
  it("plakietka „startuje DD.MM” tylko przy aktywnej umowie z przyszłym startem", () => {
    expect(futureStartLabel("active", "2026-10-01", "2026-09-24")).toBe(
      "startuje 01.10",
    );
    expect(futureStartLabel("ending", "2026-09-25", "2026-09-24")).toBe(
      "startuje 25.09",
    );
    expect(futureStartLabel("active", "2026-09-24", "2026-09-24")).toBeNull();
    expect(futureStartLabel("active", "2026-01-01", "2026-09-24")).toBeNull();
    expect(futureStartLabel("draft", "2026-10-01", "2026-09-24")).toBeNull();
    expect(futureStartLabel("active", null, "2026-09-24")).toBeNull();
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
