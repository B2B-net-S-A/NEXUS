import { describe, expect, it } from "vitest";

import type { QcResult } from "@/lib/api/cvQc";
import { handedOffMessage, handoffGate, handoffStatus, type HandoffQcState } from "@/lib/cv-editor-handoff";

function qc(over: Partial<QcResult> = {}): QcResult {
  return {
    stage_id: 5,
    candidate_id: 11,
    candidate_name: "Anna Przykładowa",
    job_id: 21,
    job_title: "Java",
    client_name: null,
    passed: false,
    blocking_failed: 2,
    warnings_count: 0,
    override: null,
    run_id: null,
    computed_at: null,
    cv: null,
    original_cv: { source: null, filename: null, text: null },
    client_request: { must: [], nice: [], critical: [], critical_source: "none" },
    checks: [
      {
        key: "no_unsupported",
        label: "Zgodność z oryginałem",
        severity: "blocking",
        status: "fail",
        summary: null,
        items: [{ term: "Jenkins", fix: "remove_term" }],
      },
    ],
    ...over,
  };
}

const ready = (over: Partial<QcResult> = {}, total = 4): HandoffQcState => ({
  total,
  blocking: over.blocking_failed ?? 2,
  state: "ready",
  qc: qc(over),
});
const BASE = { impersonating: false, canManage: false };

describe("handoffGate", () => {
  it("blokady + `can_override` z serwera → obejście z listą rzeczy i trybem z wyniku", () => {
    expect(handoffGate(ready({ can_override: true, advisory: true }), BASE)).toEqual({
      kind: "override",
      advisory: true,
      pending: ["Jenkins — jest w CV, a nie ma tego w oryginale"],
    });
  });

  it("starszy wynik bez `can_override` → uprawnienie `recruitment_manage`; tryb z wołającego", () => {
    expect(handoffGate(ready(), { ...BASE, canManage: true, advisoryFallback: true })).toMatchObject({
      kind: "override",
      advisory: true,
    });
    expect(handoffGate(ready(), BASE)).toEqual({ kind: "blocked" });
  });

  it("podgląd jako inny użytkownik nie przepuszcza", () => {
    expect(handoffGate(ready({ can_override: true }), { ...BASE, impersonating: true })).toEqual({ kind: "blocked" });
  });

  it("zaliczone, przepuszczone, bez blokad, awaria albo QC innego CV → zwykłe przekazanie", () => {
    expect(handoffGate(ready({ passed: true, blocking_failed: 0 }), BASE)).toEqual({ kind: "ready" });
    expect(
      handoffGate(ready({ override: { reason: "x", by_name: null, at: null } as QcResult["override"] }), BASE),
    ).toEqual({ kind: "ready" });
    expect(handoffGate(ready({ blocking_failed: 0 }), BASE)).toEqual({ kind: "ready" });
    expect(handoffGate({ total: 0, blocking: 0, state: "failed", qc: null }, BASE)).toEqual({ kind: "ready" });
    expect(handoffGate({ total: 1, blocking: 0, state: "ready", qc: null }, BASE)).toEqual({ kind: "ready" });
  });

  it("QC się liczy → czekamy", () => {
    expect(handoffGate({ total: 0, blocking: 0, state: "loading" }, BASE)).toEqual({ kind: "waiting" });
  });
});

describe("handoffStatus", () => {
  it("liczba rzeczy do decyzji i odmiana „blokuje / blokują”", () => {
    const one = ready({ blocking_failed: 1, can_override: true }, 1);
    expect(handoffStatus(one, handoffGate(one, BASE))).toBe("1 rzecz do decyzji · 1 blokuje wysyłkę");
    const two = ready({ can_override: true }, 3);
    expect(handoffStatus(two, handoffGate(two, BASE))).toBe("3 rzeczy do decyzji · 2 blokują wysyłkę");
    const clean = ready({ passed: true, blocking_failed: 0 }, 0);
    expect(handoffStatus(clean, handoffGate(clean, BASE))).toBe("Nic do decyzji · nic nie blokuje wysyłki");
  });

  it("awaria QC nie udaje zera", () => {
    const down: HandoffQcState = { total: 0, blocking: 0, state: "failed", qc: null };
    expect(handoffStatus(down, handoffGate(down, BASE))).toMatch(/QC nie odpowiada/);
  });
});

describe("handedOffMessage", () => {
  it("imię bez odmiany po rodzaju; zdanie o kontroli tylko przy zatwierdzaniu", () => {
    expect(handedOffMessage("Anna Przykładowa", true)).toBe(
      "Anna — przekazano Delivery Leadowi. Sprawdzamy treść CV w tle.",
    );
    expect(handedOffMessage("  Jan  Kowalski ", false)).toBe("Jan — przekazano Delivery Leadowi.");
  });
});
