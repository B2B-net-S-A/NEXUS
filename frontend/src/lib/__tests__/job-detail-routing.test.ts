import { describe, expect, it } from "vitest";

import { jobProposalsHref } from "@/components/v2/jobs/JobListCells";
import inventory from "@/lib/recruitment-feature-inventory.json";
import {
  carryPersonAcrossViews,
  parseRecruitmentSegment,
  readJobDetailUrlState,
  resolveLegacyJobTab,
  rewriteLegacyJobParams,
} from "@/lib/job-detail-routing";

describe("resolveLegacyJobTab", () => {
  it.each([
    ["pipeline", { view: "people" }],
    ["screening", { view: "people", segment: "group:screening", panelSection: "screening" }],
    ["cv", { view: "people", segment: "group:verification", panelSection: "cv" }],
    ["interviews", { view: "people", segment: "group:client", panelSection: "interviews" }],
    ["contract", { view: "people", segment: "group:contract", panelSection: "contract" }],
    ["notes", { view: "people", panelSection: "notes" }],
    ["ai-matching", { view: "people", segment: "proposals" }],
    ["similar", { view: "people", segment: "proposals" }],
    ["manual-search", { view: "people", slideOver: "manual-search" }],
    ["portals", { view: "people", slideOver: "order", orderSection: "portals" }],
    ["questions", { view: "people", slideOver: "questions" }],
    ["history", { view: "people", slideOver: "history-chat", slideOverTab: "request" }],
    ["chat", { view: "people", slideOver: "history-chat", slideOverTab: "chat" }],
    ["champion", { view: "champion" }],
    ["champion-profile", { view: "champion" }],
  ])("?tab=%s", (tab, expected) => {
    expect(resolveLegacyJobTab(tab)).toEqual(expected);
  });

  it("każdy stary identyfikator ze spisu ma cel", () => {
    for (const tab of [...inventory.old_tab_ids, ...inventory.old_tab_aliases]) {
      expect(resolveLegacyJobTab(tab), tab).not.toBeNull();
    }
  });

  it("nieznany identyfikator, nowy widok i brak parametru nie są starym adresem", () => {
    expect(resolveLegacyJobTab("people")).toBeNull();
    expect(resolveLegacyJobTab("board")).toBeNull();
    expect(resolveLegacyJobTab("cokolwiek")).toBeNull();
    expect(resolveLegacyJobTab(null)).toBeNull();
    // Klucze prototypu nie są zakładkami.
    expect(resolveLegacyJobTab("constructor")).toBeNull();
  });
});

describe("parseRecruitmentSegment", () => {
  it("przyjmuje wyłącznie kształty, które tabela zna", () => {
    expect(parseRecruitmentSegment("proposals")).toBe("proposals");
    expect(parseRecruitmentSegment("group:client")).toBe("group:client");
    expect(parseRecruitmentSegment("stage:17")).toBe("stage:17");
    expect(parseRecruitmentSegment("stage:0")).toBeNull();
    expect(parseRecruitmentSegment("stage:abc")).toBeNull();
    expect(parseRecruitmentSegment("group:nope")).toBeNull();
    expect(parseRecruitmentSegment("")).toBeNull();
    expect(parseRecruitmentSegment(null)).toBeNull();
  });
});

describe("readJobDetailUrlState", () => {
  const read = (query: string) => readJobDetailUrlState(new URLSearchParams(query));

  it("pusty adres niczego nie wymusza", () => {
    expect(read("")).toEqual({
      view: null,
      segment: null,
      panelSection: null,
      slideOver: null,
      slideOverTab: null,
      orderSection: null,
      highlightProposals: false,
    });
  });

  it("czyta nowy kształt", () => {
    expect(read("tab=board").view).toBe("board");
    const state = read("seg=stage:5&panel=cv&win=history-chat&wintab=moves");
    expect(state).toMatchObject({
      segment: "stage:5",
      panelSection: "cv",
      slideOver: "history-chat",
      slideOverTab: "moves",
      orderSection: null,
    });
    expect(read("win=order&wintab=team").orderSection).toBe("team");
  });

  it("stary adres daje ten sam stan co nowy", () => {
    expect(read("tab=chat")).toMatchObject({
      view: "people",
      slideOver: "history-chat",
      slideOverTab: "chat",
    });
    expect(read("tab=portals")).toMatchObject({ slideOver: "order", orderSection: "portals" });
    expect(read("tab=notes&candidate=7")).toMatchObject({ view: "people", panelSection: "notes" });
  });

  it("nowe parametry wygrywają ze starym ?tab=", () => {
    expect(read("tab=screening&seg=closed&panel=notes")).toMatchObject({
      view: "people",
      segment: "closed",
      panelSection: "notes",
    });
  });

  it("?highlight=ai-proposals otwiera segment propozycji", () => {
    expect(read("highlight=ai-proposals")).toMatchObject({
      view: "people",
      segment: "proposals",
      highlightProposals: true,
    });
  });

  it("link „+N propozycji” z listy rekrutacji trafia w segment propozycji tabeli", () => {
    // Adres budowany przez `jobProposalsHref` — ma trafić bez przepisywania.
    const query = new URL(jobProposalsHref(7), "https://nexus.test").searchParams;
    expect(query.toString()).toBe("tab=people&seg=proposals");
    expect(readJobDetailUrlState(query)).toMatchObject({
      view: "people",
      segment: "proposals",
      slideOver: null,
    });
    expect(rewriteLegacyJobParams(query)).toBeNull();
  });

  it("zakładka okna nie przecieka do innego okna", () => {
    expect(read("win=questions&wintab=chat")).toMatchObject({
      slideOver: "questions",
      slideOverTab: null,
      orderSection: null,
    });
  });
});

describe("rewriteLegacyJobParams", () => {
  const rewrite = (query: string) =>
    rewriteLegacyJobParams(new URLSearchParams(query))?.toString() ?? null;

  it("nowego adresu nie rusza", () => {
    expect(rewrite("")).toBeNull();
    expect(rewrite("tab=board&seg=closed")).toBeNull();
    expect(rewrite("tab=champion&intake=1")).toBeNull();
    expect(rewrite("candidate=5")).toBeNull();
  });

  it("przepisuje stare zakładki, zostawiając resztę parametrów", () => {
    expect(rewrite("tab=pipeline")).toBe("");
    expect(rewrite("tab=pipeline&candidate=12")).toBe("candidate=12");
    expect(rewrite("tab=screening")).toBe("seg=group%3Ascreening&panel=screening");
    expect(rewrite("tab=notes&candidate=3")).toBe("candidate=3&panel=notes");
    expect(rewrite("tab=chat")).toBe("win=history-chat&wintab=chat");
    expect(rewrite("tab=history")).toBe("win=history-chat&wintab=request");
    expect(rewrite("tab=portals")).toBe("win=order&wintab=portals");
    expect(rewrite("tab=questions")).toBe("win=questions");
    expect(rewrite("tab=manual-search")).toBe("win=manual-search");
    expect(rewrite("tab=similar")).toBe("seg=proposals");
  });

  it("champion-profile → champion, z zachowaniem ?intake=1", () => {
    expect(rewrite("tab=champion-profile&intake=1")).toBe("intake=1&tab=champion");
  });

  it("?highlight=ai-proposals → segment propozycji, parametr znika", () => {
    expect(rewrite("highlight=ai-proposals")).toBe("seg=proposals");
    expect(rewrite("tab=ai-matching&highlight=ai-proposals")).toBe("seg=proposals");
  });

  it("nieznana zakładka jest zdejmowana (ląduje na widoku domyślnym)", () => {
    expect(rewrite("tab=nie-ma-takiej&candidate=4")).toBe("candidate=4");
  });
});

describe("carryPersonAcrossViews", () => {
  it("„Tabela” → „Tablica”: osoba z panelu otwiera się w doku", () => {
    expect(
      carryPersonAcrossViews({ from: "people", to: "board", panelCandidateId: 7, boardDockCandidateId: null }),
    ).toEqual({ panelCandidateId: 7, boardDockRequest: 7 });
  });

  it("„Tablica” → „Tabela”: osoba z doku otwiera się w panelu; zamknięty dok nie zamyka panelu", () => {
    expect(
      carryPersonAcrossViews({ from: "board", to: "people", panelCandidateId: 7, boardDockCandidateId: 9 }),
    ).toEqual({ panelCandidateId: 9, boardDockRequest: null });
    expect(
      carryPersonAcrossViews({ from: "board", to: "people", panelCandidateId: 7, boardDockCandidateId: null }),
    ).toEqual({ panelCandidateId: 7, boardDockRequest: null });
  });

  it("bez osoby i przy innych przejściach nic nie otwiera", () => {
    expect(
      carryPersonAcrossViews({ from: "people", to: "board", panelCandidateId: null, boardDockCandidateId: null }),
    ).toEqual({ panelCandidateId: null, boardDockRequest: null });
    expect(
      carryPersonAcrossViews({ from: "people", to: "champion", panelCandidateId: 7, boardDockCandidateId: null }),
    ).toEqual({ panelCandidateId: 7, boardDockRequest: null });
  });
});

describe("okno „Zlecenie” na akcji zamknięcia", () => {
  it("`?win=order&wintab=close` jest rozpoznawane (podpowiedź „Obsada kompletna”)", () => {
    const state = readJobDetailUrlState(new URLSearchParams("win=order&wintab=close"));
    expect(state.slideOver).toBe("order");
    expect(state.orderSection).toBe("close");
  });
});
