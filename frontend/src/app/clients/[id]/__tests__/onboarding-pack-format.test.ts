import { describe, expect, it } from "vitest";

import {
  draftFromPack,
  draftProblem,
  emptyItem,
  isDirty,
  joinOffset,
  offsetLabel,
  saveFromDraft,
  splitOffset,
} from "../onboarding-pack-format";
import { packFixture } from "./pack-fixture";

describe("termin względem startu", () => {
  it("dzieli i składa przesunięcie w dniach roboczych", () => {
    expect(splitOffset(-5)).toEqual({ timing: "before", days: 5 });
    expect(splitOffset(0)).toEqual({ timing: "day", days: 0 });
    expect(splitOffset(null)).toEqual({ timing: "day", days: 0 });
    expect(splitOffset(7)).toEqual({ timing: "after", days: 7 });
    expect(joinOffset("before", 5)).toBe(-5);
    expect(joinOffset("day", 9)).toBe(0);
    expect(joinOffset("after", 0)).toBe(1);
  });

  it("pilnuje granic ścieżki (60 przed, 120 po)", () => {
    expect(joinOffset("before", 500)).toBe(-60);
    expect(joinOffset("after", 500)).toBe(120);
  });

  it("opisuje termin po ludzku", () => {
    expect(offsetLabel(-1)).toBe("1 dzień rob. przed startem");
    expect(offsetLabel(-10)).toBe("10 dni rob. przed startem");
    expect(offsetLabel(0)).toBe("w dniu startu");
    expect(offsetLabel(7)).toBe("do 7 dni rob. po starcie");
  });
});

describe("zapis pakietu", () => {
  it("wysyła wszystkie części z wersją, od której zaczęła się edycja", () => {
    const draft = draftFromPack(packFixture());
    const payload = saveFromDraft(draft, { equipment: true, rest: true }, 3);
    expect(payload.expected_version).toBe(3);
    expect(payload.equipment?.ours).toEqual([{ name: "Laptop 14 cali", note: null }]);
    expect(payload.first_day).toEqual({ contact_id: null, place: "ul. Przykładowa 20", time: "09:00", bring: null });
    expect(payload.documents).toEqual([
      {
        name: "Zaświadczenie o niekaralności",
        note: "nie starsze niż 3 miesiące",
        offset_days: -5,
        required: true,
        requires_file: true,
      },
    ]);
    expect(payload.accesses?.[0]).toMatchObject({ assignee: "delivery_lead", offset_days: -10 });
  });

  it("recepcja wysyła tylko część sprzętową", () => {
    const draft = draftFromPack(packFixture());
    const payload = saveFromDraft(draft, { equipment: true, rest: false }, 3);
    expect(Object.keys(payload).sort()).toEqual(["equipment", "expected_version"]);
  });

  it("nowy pakiet nie ma wersji do sprawdzenia", () => {
    const draft = draftFromPack(packFixture({ exists: false, version: 0 }));
    expect(saveFromDraft(draft, { equipment: true, rest: true }, 0).expected_version).toBeUndefined();
  });

  it("widzi zmianę tylko w częściach, które osoba może zapisać", () => {
    const saved = draftFromPack(packFixture());
    expect(isDirty(saved, { ...saved }, { equipment: true, rest: true })).toBe(false);
    const changed = { ...saved, firstDay: { ...saved.firstDay, place: "Inne biuro" } };
    expect(isDirty(saved, changed, { equipment: true, rest: true })).toBe(true);
    expect(isDirty(saved, changed, { equipment: true, rest: false })).toBe(false);
    // Spacje na końcu to nie zmiana.
    const spaces = { ...saved, firstDay: { ...saved.firstDay, place: "ul. Przykładowa 20  " } };
    expect(isDirty(saved, spaces, { equipment: true, rest: true })).toBe(false);
  });

  it("zatrzymuje pustą nazwę i złą godzinę przed wysłaniem", () => {
    const draft = draftFromPack(packFixture());
    expect(draftProblem(draft)).toBeNull();
    expect(draftProblem({ ...draft, documents: [...draft.documents, emptyItem()] })).toMatch(/nazwę/);
    expect(draftProblem({ ...draft, firstDay: { ...draft.firstDay, time: "25:00" } })).toMatch(
      /Godzinę/,
    );
    expect(draftProblem({ ...draft, firstDay: { ...draft.firstDay, time: "8:30" } })).toBeNull();
  });
});
