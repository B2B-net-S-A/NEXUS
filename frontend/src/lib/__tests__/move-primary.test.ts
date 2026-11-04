import { describe, expect, it } from "vitest";

import {
  HAND_TO_DL_MESSAGE,
  NO_QC_STAGE_MESSAGE,
  planPrimaryStep,
} from "@/lib/move-primary";
import type { MovePrimary, MoveRequirementsResponse } from "@/lib/api/moveRequirements";

const data = (
  primary: MovePrimary,
  from: MoveRequirementsResponse["from_column"] = "verified",
): Pick<MoveRequirementsResponse, "primary" | "from_column"> => ({ primary, from_column: from });

describe("planPrimaryStep — główny przycisk okna i ramki ruchu", () => {
  it("bez odpowiedzi serwera przycisk jest nieaktywny", () => {
    expect(planPrimaryStep(null, 0)).toEqual({ type: "disabled" });
    expect(planPrimaryStep(undefined, 0)).toEqual({ type: "disabled" });
  });

  it("„move”: ruch, a przy brakach blokujących — nieaktywny", () => {
    expect(planPrimaryStep(data({ kind: "move", label: "Przesuń" }), 0)).toEqual({ type: "move" });
    expect(planPrimaryStep(data({ kind: "move", label: "Przesuń" }), 2)).toEqual({ type: "disabled" });
  });

  it("„hand_to_dl” spoza „QC CV”: ruch na etap QC z komunikatem bez nieistniejącej kolejki", () => {
    expect(
      planPrimaryStep(data({ kind: "hand_to_dl", label: "Przekaż", target_stage_def_id: 41 }), 0),
    ).toEqual({ type: "stage", stageDefId: 41, notice: HAND_TO_DL_MESSAGE });
    expect(HAND_TO_DL_MESSAGE).not.toMatch(/Czeka na Ciebie/);
  });

  it("„hand_to_dl” bez etapu QC w szablonie: błąd, nie udawane przekazanie", () => {
    expect(
      planPrimaryStep(data({ kind: "hand_to_dl", label: "Przekaż", target_stage_def_id: null }), 0),
    ).toEqual({ type: "error", message: NO_QC_STAGE_MESSAGE });
  });

  // 14.10.2026: osoba już w „QC CV” — dawniej przycisk z toastem o „Czeka na
  // Ciebie”, której rekruter nie ma. Teraz stan, bez przycisku.
  it("„hand_to_dl” w „QC CV”: osoba czeka u Delivery Leada — bez przycisku", () => {
    expect(
      planPrimaryStep(data({ kind: "hand_to_dl", label: "Przekaż", target_stage_def_id: null }, "cv_qc"), 0),
    ).toEqual({ type: "waiting" });
  });

  it("„hand_to_cpro”: etap Cpro wskazany przez serwer; bez niego nieaktywny", () => {
    expect(
      planPrimaryStep(data({ kind: "hand_to_cpro", label: "Akceptuj", target_stage_def_id: 45 }, "cv_qc"), 0),
    ).toEqual({ type: "stage", stageDefId: 45, notice: null });
    expect(planPrimaryStep(data({ kind: "hand_to_cpro", label: "Akceptuj" }, "cv_qc"), 0)).toEqual({
      type: "disabled",
    });
  });

  it("„blocked”: nieaktywny", () => {
    expect(planPrimaryStep(data({ kind: "blocked", label: "Najpierw uzupełnij: QC CV" }), 0)).toEqual({
      type: "disabled",
    });
  });
});
