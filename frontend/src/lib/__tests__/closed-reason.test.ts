import { describe, expect, it } from "vitest";
import { closedReason, LEGACY_UNKNOWN_REASON_LABEL } from "@/lib/closed-reason";

describe("closedReason (19.10.2026)", () => {
  it("osoba w toku nie ma powodu zamknięcia, nawet z notatką ruchu", () => {
    expect(closedReason({ stage: "screening", notes: "ok", rejection_reason_name: "x" })).toBeNull();
    expect(closedReason({ stage: "hired" })).toBeNull();
  });

  it("odrzucenie z powodem: czerwień, komentarz i kto bez białych znaków", () => {
    expect(
      closedReason({
        stage: "rejected",
        rejection_reason_name: " Za wysokie oczekiwania finansowe ",
        closed_by_name: " Julia Swidkiewicz ",
        notes: "  Oczekuje 190 zł/h.\n",
        moved_at: "2026-10-16T10:00:00Z",
      }),
    ).toEqual({
      kind: "rejected",
      verb: "Odrzucony",
      reason: "Za wysokie oczekiwania finansowe",
      reasonText: "Za wysokie oczekiwania finansowe",
      unknown: false,
      comment: "Oczekuje 190 zł/h.",
      by: "Julia Swidkiewicz",
      at: "2026-10-16T10:00:00Z",
      tone: "danger",
    });
  });

  it("brak powodu mówi to wprost i nie jest czerwony", () => {
    const r = closedReason({ stage: "rejected", rejection_reason_name: "  ", notes: "" });
    expect(r?.reason).toBeNull();
    expect(r?.reasonText).toBe("powód nie został zapisany");
    expect(r?.unknown).toBe(true);
    expect(r?.comment).toBeNull();
    expect(r?.tone).toBe("neutral");
  });

  it("karta z Traffita: powód nieznany, szara", () => {
    const r = closedReason({ stage: "rejected", rejection_reason_name: LEGACY_UNKNOWN_REASON_LABEL });
    expect(r?.unknown).toBe(true);
    expect(r?.tone).toBe("neutral");
  });

  it("rezygnacja jest szara także z powodem", () => {
    const r = closedReason({ stage: "withdrawn", rejection_reason_name: "Przyjął inną ofertę" });
    expect(r?.verb).toBe("Rezygnacja");
    expect(r?.tone).toBe("neutral");
    expect(r?.unknown).toBe(false);
  });
});
