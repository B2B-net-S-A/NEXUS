// Asystent prawny na Poligonie (lekcja z 26.11.2026): zadanie „szkic odpowiedzi
// na wypowiedzenie” i szkic pisma z zestawu, bez modelu i bez zapisu.

import { describe, expect, it } from "vitest";

import dataset from "../dataset.json";
import { NO_AMOUNTS, viewerFrom } from "../amounts";
import { PRACTICE_LETTER_ONLY_REPLY } from "../legal-letter";
import { BLOCKED_WRITE_MESSAGE, createPoligonStore, resolveDates, type PoligonDataset } from "../store";
import { approvalView, availableKinds, type LetterDraft, type LegalTask } from "@/lib/legal-letters";

const DATA = dataset as unknown as PoligonDataset;
// 30.11.2026, 12:00 UTC: wypowiedzenie 28.11, okres od grudnia → koniec 31.12.
const NOW = Date.UTC(2026, 10, 30, 12, 0, 0);
const ACTIVE = 990521;
const ENDED = 990522;
const access = (granted: string[]) =>
  Object.fromEntries(["delivery_view", "amounts_view"].map((k) => [k, granted.includes(k) ? "manage" : "none"]));
const DL = viewerFrom({ role: "delivery_lead", effective_action_access: access(["delivery_view", "amounts_view"]) });
const TCM = viewerFrom({ role: "talent_community_manager", effective_action_access: access(["delivery_view"]) });

function call(method: string, url: string, viewer = DL, opts: { params?: Record<string, unknown>; body?: unknown } = {}) {
  const store = createPoligonStore(DATA, NOW);
  const res = store.handle({ method, url, params: opts.params, body: opts.body, viewer });
  if (res === "network") throw new Error(`${url} poszło do API`);
  return res;
}

describe("@releom: koniec miesiąca względem dnia", () => {
  it("liczy ostatni dzień miesiąca po miesiącu dnia sprzed N dni", () => {
    expect(resolveDates("@releom:-2:1", NOW)).toBe("2026-12-31");
    expect(resolveDates("@releom:-2:1", Date.UTC(2026, 11, 1, 12))).toBe("2026-12-31");
    expect(resolveDates("@releom:0:0", Date.UTC(2027, 1, 10, 12))).toBe("2027-02-28");
  });
});

describe("kontrakt ćwiczebny z wypowiedzeniem Partnera", () => {
  it("trwający kontrakt ma wypowiedzenie Partnera, więc panel daje odpowiedź na nie", () => {
    const contract = call("get", `/api/contracts/${ACTIVE}`).data as Record<string, string | null>;
    expect(contract.agreement_termination_signed_on).toBe("2026-11-28");
    expect(contract.agreement_last_day).toBe("2026-12-31");
    expect(availableKinds(contract as never).map((k) => k.key)).toContain("notice_reply");
  });

  it("zadanie asystenta: na liście i na trwającym kontrakcie, nie na zakończonym", () => {
    const list = call("get", "/api/legal/tasks").data as { items: LegalTask[] };
    expect(list.items.map((t) => t.href)).toEqual([`/contracts/${ACTIVE}?pismo=notice_reply`]);
    const own = call("get", "/api/legal/tasks", DL, { params: { contract_id: ACTIVE } }).data as { items: LegalTask[] };
    expect(own.items).toHaveLength(1);
    const ended = call("get", "/api/legal/tasks", DL, { params: { contract_id: ENDED } }).data as { items: LegalTask[] };
    expect(ended.items).toEqual([]);
  });

  it("osoba bez podglądu kwot nie dostaje zadań (jak serwer)", () => {
    expect((call("get", "/api/legal/tasks", TCM).data as { items: unknown[] }).items).toEqual([]);
    expect((call("get", "/api/legal/tasks", NO_AMOUNTS).data as { items: unknown[] }).items).toEqual([]);
  });
});

describe("szkic pisma na Poligonie", () => {
  const draft = () =>
    call("post", `/api/contracts/${ACTIVE}/legal-letter/draft`, DL, { body: { kind: "notice_reply" } });

  it("odpowiedź: termin z kontraktu, pytanie o formę, dwa sprawdzone cytaty", () => {
    const res = draft();
    expect(res.status).toBe(200);
    const d = res.data as LetterDraft;
    expect(d.facts.find((f) => f.label === "Rozwiązanie")).toMatchObject({ value: "31.12.2026", note: "zgodne z NEXUSEM" });
    expect(d.text).toContain("28.11.2026");
    expect(d.text).toContain("31.12.2026");
    expect(d.warning?.level).toBe("question");
    expect(d.checks.map((c) => c.status)).toEqual(["ok", "ok"]);
    expect(d.checks.map((c) => c.citation.raw).every((raw) => d.text.includes(raw.replace(" Umowy", "")))).toBe(true);
    expect(d.recipient.candidate_id).toBe(990112);
  });

  it("„Zatwierdzam” czeka na odpowiedź o formę, potem przechodzi bez zapisu", () => {
    const d = draft().data as LetterDraft;
    expect(approvalView(d, d.text, false).canApprove).toBe(false);
    expect(approvalView(d, d.text, true).canApprove).toBe(true);
    const res = call("post", `/api/contracts/${ACTIVE}/legal-letter/approve`, DL, {
      body: { kind: "notice_reply", original_confirmed: true, text: d.text },
    });
    expect(res.status).toBe(200);
    expect(res.data).toMatchObject({ approved: true, task_key: null, counts: { ok: 2, missing: 0, mismatch: 0 } });
  });

  it("data w nagłówku to dzień w Warszawie, nie UTC", () => {
    expect((draft().data as LetterDraft).text.startsWith("Warszawa, 30.11.2026\n")).toBe(true);
    const lateStore = createPoligonStore(DATA, Date.UTC(2026, 10, 30, 23, 30));
    const late = lateStore.handle({ method: "post", url: `/api/contracts/${ACTIVE}/legal-letter/draft`, body: { kind: "notice_reply" }, viewer: DL });
    if (late === "network") throw new Error("poszło do API");
    expect((late.data as LetterDraft).text.startsWith("Warszawa, 01.12.2026\n")).toBe(true);
  });

  it("inny rodzaj pisma: komunikat, że na Poligonie jest tylko odpowiedź", () => {
    const res = call("post", `/api/contracts/${ACTIVE}/legal-letter/draft`, DL, { body: { kind: "termination_agreement" } });
    expect((res.data as LetterDraft).error).toBe(PRACTICE_LETTER_ONLY_REPLY);
  });

  it("DOCX i kontrakt bez wypowiedzenia zostają zablokowane jak każdy zapis", () => {
    const docx = call("post", `/api/contracts/${ACTIVE}/legal-letter/docx`, DL, { body: { kind: "notice_reply" } });
    expect(docx).toEqual({ status: 409, data: { detail: BLOCKED_WRITE_MESSAGE } });
    const ended = call("post", `/api/contracts/${ENDED}/legal-letter/draft`, DL, { body: { kind: "notice_reply" } });
    expect(ended.status).toBe(409);
    const real = call("post", "/api/contracts/339/legal-letter/draft", DL, { body: { kind: "notice_reply" } });
    expect(real.status).toBe(409);
  });
});
