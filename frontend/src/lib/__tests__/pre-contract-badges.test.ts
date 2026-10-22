import { describe, expect, it } from "vitest";

import { preContractCardBadge } from "@/lib/board-card-badges";
import { isPreContractWarning, type MoveRequirementItem } from "@/lib/api/moveRequirements";
import { preContractTabFromParam } from "@/components/v2/recruitment/PreContractsList";

describe("plakietka umowy przedwstępnej na karcie", () => {
  it("bierze napis z serwera i mapuje ton na ton karty", () => {
    expect(
      preContractCardBadge({ id: 1, state: "sent", label: "Przedwstępna wysłana · czeka 2 dni", tone: "wait", detail: "Wysłana" }),
    ).toEqual({ key: "pre_contract", label: "Przedwstępna wysłana · czeka 2 dni", tone: "info", title: "Wysłana" });
    expect(preContractCardBadge({ id: 1, state: "requested", label: "x", tone: "late", detail: "" })?.tone).toBe("urgent");
    expect(preContractCardBadge({ id: 1, state: "requested", label: "x", tone: "missing", detail: "" })?.tone).toBe("wait");
    expect(preContractCardBadge(null)).toBeNull();
  });
});

describe("ostrzeżenie w oknie „Przesuń dalej”", () => {
  const base: MoveRequirementItem = {
    key: "pre_contract",
    label: "Umowa przedwstępna niepodpisana",
    status: "missing",
    blocking: false,
    action: { kind: "open_pre_contract", label: "Otwórz umowę" },
  };
  it("rozpoznaje brak umowy jako ostrzeżenie, nie bramkę", () => {
    expect(isPreContractWarning(base)).toBe(true);
    expect(isPreContractWarning({ ...base, status: "ok" })).toBe(false);
    expect(isPreContractWarning({ ...base, key: "qc" })).toBe(false);
  });
});

describe("zakładka listy z adresu", () => {
  it("nieznana albo brak = „Do zrobienia”", () => {
    expect(preContractTabFromParam(null)).toBe("todo");
    expect(preContractTabFromParam("penalty")).toBe("penalty");
    expect(preContractTabFromParam("x")).toBe("todo");
  });
});
