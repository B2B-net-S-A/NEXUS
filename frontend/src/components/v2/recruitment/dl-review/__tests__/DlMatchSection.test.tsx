import { describe, expect, it } from "vitest";

import { acceptLabel } from "../DecisionPanel";
import { initialSelection, matchTargets, summarizeResults } from "../DlMatchSection";
import type { DlMatchJob, DlMatchSendResult } from "@/lib/dl-match-api";

function job(id: number, extra: Partial<DlMatchJob> = {}): DlMatchJob {
  return {
    job_id: id,
    title: `Java ${id}`,
    client_name: "PKO BP",
    client_reference: `ZOB-${id}`,
    score: 80,
    matching_must: [],
    gap_must: [],
    linked: false,
    destination: "cv_sent",
    sendable: true,
    ...extra,
  };
}

const FALLBACK = { rate: "185", unit: "hourly", currency: "PLN" };

describe("Match — zaznaczenie i stawki", () => {
  it("zaznacza od razu tylko rekrutacje połączone, do których da się wysłać", () => {
    const jobs = [job(1, { linked: true }), job(2), job(3, { linked: true, sendable: false })];
    const sel = initialSelection(jobs);
    expect(sel[1].checked).toBe(true);
    expect(sel[2].checked).toBe(false);
    expect(sel[3].checked).toBe(false);
  });

  it("wysyła zaznaczone ze stawką z głównej decyzji albo wpisaną przy wierszu", () => {
    const jobs = [job(1), job(2, { destination: "cpro" }), job(3)];
    const sel = {
      1: { checked: true, rate: null },
      2: { checked: true, rate: "172,5" },
      3: { checked: false, rate: "999" },
    };
    const { targets, missingRate } = matchTargets(jobs, sel, FALLBACK);
    expect(missingRate).toBe(0);
    expect(targets).toEqual([
      { job_id: 1, client_rate_value: 185, client_rate_unit: "hourly", client_rate_currency: "PLN" },
      { job_id: 2, client_rate_value: 172.5, client_rate_unit: "hourly", client_rate_currency: "PLN" },
    ]);
  });

  it("zaznaczona rekrutacja bez stawki wstrzymuje akceptację", () => {
    const { targets, missingRate } = matchTargets([job(1)], { 1: { checked: true, rate: "" } }, FALLBACK);
    expect(targets).toEqual([]);
    expect(missingRate).toBe(1);
  });

  it("przycisk mówi, do ilu rekrutacji pójdzie osoba", () => {
    expect(acceptLabel("185", "hourly", "PLN", false, 2)).toBe("Akceptuj — wysyłam do 3 rekrutacji");
    expect(acceptLabel("172", "hourly", "PLN", true, 1)).toBe("Akceptuj — do Cpro i do 1 innej rekrutacji");
    expect(acceptLabel("", "hourly", "PLN", false, 2)).toBe("Akceptuj — wpisz stawkę do klienta");
    expect(acceptLabel("185", "hourly", "PLN", false, 0)).toMatch(/^Akceptuj — wysyłam za /);
  });
});

describe("Match — podsumowanie po wysyłce", () => {
  const base: Omit<DlMatchSendResult, "job_id" | "status"> = {
    title: null,
    destination: "cv_sent",
    qc: "passed",
    reason: null,
    cv_carried: true,
  };

  it("liczy wysłane do klienta i do Cpro oraz przepuszczone QC", () => {
    const summary = summarizeResults([
      { ...base, job_id: 1, status: "sent" },
      { ...base, job_id: 2, status: "sent", destination: "cpro", qc: "overridden" },
    ]);
    expect(summary.sent).toBe(
      "Match: wysłano też do 2 rekrutacji (do klienta: 1, do kolejki Cpro: 1) · QC przepuszczone w 1",
    );
    expect(summary.problems).toEqual([]);
  });

  it("mówi, co nie poszło i dlaczego — także osobę zostawioną na „Zweryfikowanym”", () => {
    const summary = summarizeResults([
      { ...base, job_id: 3, title: "ZOB-3 Java", status: "failed", reason: "weto HM" },
      { ...base, job_id: 4, title: "ZOB-4 Java", status: "verified_only", reason: "Rekrutacja zamknięta" },
    ]);
    expect(summary.sent).toBeNull();
    expect(summary.problems).toEqual([
      "ZOB-3 Java: weto HM",
      "ZOB-4 Java: dodano na „Zweryfikowany”, wysyłka nie przeszła — Rekrutacja zamknięta",
    ]);
  });
});
