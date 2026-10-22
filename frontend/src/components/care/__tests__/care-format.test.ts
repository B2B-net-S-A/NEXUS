import { describe, expect, it } from "vitest";

import {
  careTimeline,
  conversationSignals,
  sourceSummary,
  splitNames,
  cellLetters,
  cellTitle,
  heatLevel,
} from "@/components/care/care-format";
import { buildCardPayload, initialCardForm } from "@/components/care/TechCardDialog";
import { careRouteFrom, canSeeTeam, contractParam } from "@/components/care/CareScreen";
import {
  monthEnd,
  monthOf,
  type CareConversation,
  type HeatCell,
  type MapTechnology,
  type TechCard,
} from "@/lib/api/care";

function conversation(id: number, date: string, extra: Partial<CareConversation> = {}): CareConversation {
  return {
    id,
    occurred_on: date,
    channel: "phone",
    satisfaction: null,
    note: null,
    attrition_risk: false,
    wants_change: false,
    project_end_on: null,
    client_hiring: false,
    client_hiring_note: null,
    follow_up_on: null,
    author: null,
    ...extra,
  };
}

function card(id: number, date: string, extra: Partial<TechCard> = {}): TechCard {
  return {
    id,
    contract_id: 1,
    client_id: 1,
    interview_on: date,
    status: "ok",
    is_draft: false,
    finalized_at: null,
    satisfaction: null,
    area: null,
    skills: [],
    unrecognized_skills: [],
    vendors: [],
    hiring: null,
    hiring_source: null,
    hiring_roles: [],
    project_end_on: null,
    project_end_unknown: false,
    team_size: null,
    team_externals: null,
    initiatives: [],
    memorable_quote: null,
    note: null,
    sales_status: null,
    author: null,
    ...extra,
  };
}

function tech(name: string, areas: string[], counts: Partial<MapTechnology["counts"]> = {}): MapTechnology {
  return {
    skill_id: name.length,
    name,
    category: null,
    counts: { cards: 0, jobs: 0, consultants: 0, notes: 0, ...counts },
    source_count: 1,
    must_jobs: 0,
    consultant_months: 0,
    areas,
    last_seen: null,
    stale: false,
  };
}

describe("oś opieki", () => {
  it("łączy rozmowy i karty od najnowszych, karta przed rozmową z tego samego dnia", () => {
    const entries = careTimeline(
      [conversation(1, "2026-09-08"), conversation(2, "2026-10-02")],
      [card(7, "2026-10-02")],
    );
    expect(entries.map((e) => `${e.kind}:${e.id}`)).toEqual([
      "card:7",
      "conversation:2",
      "conversation:1",
    ]);
  });

  it("wypisuje sygnały rozmowy", () => {
    expect(
      conversationSignals(
        conversation(1, "2026-10-01", { attrition_risk: true, client_hiring: true, project_end_on: "2026-12-31" }),
      ),
    ).toEqual(["ryzyko odejścia", "koniec projektu", "klient zatrudnia"]);
  });
});

describe("mapa technologii", () => {
  it("komórka mapy cieplnej: siła = liczba rodzajów źródeł, litery i dymek", () => {
    const cell = (counts: Partial<HeatCell["counts"]>, openJobs = 0): HeatCell => {
      const full = { cards: 0, jobs: 0, consultants: 0, notes: 0, ...counts };
      return {
        counts: full,
        source_count: Object.values(full).filter(Boolean).length,
        open_jobs: openJobs,
      };
    };
    expect(heatLevel(null)).toBe(0);
    expect(heatLevel(cell({ jobs: 4 }))).toBe(1);
    expect(heatLevel(cell({ cards: 1, jobs: 2 }))).toBe(2);
    expect(heatLevel(cell({ cards: 1, jobs: 1, consultants: 1, notes: 1 }))).toBe(3);
    // Sama otwarta rekrutacja bez źródła (nie powinna się zdarzyć) — bez koloru.
    expect(heatLevel(cell({}, 1))).toBe(0);
    expect(cellLetters(cell({ notes: 1, cards: 2 }))).toEqual(["T", "N"]);
    expect(cellLetters(null)).toEqual([]);
    expect(cellTitle("Płatności", "Java 17", cell({ cards: 3, jobs: 4 }, 1))).toBe(
      "Płatności · Java 17: 3 karty, 4 rekrutacje · 1 otwarta rekrutacja",
    );
    expect(cellTitle("Data", "Kafka", null)).toBe("Data · Kafka: brak źródeł");
  });

  it("opisuje źródła po polsku", () => {
    expect(sourceSummary(tech("Java", [], { cards: 2, jobs: 1, consultants: 5 }))).toBe(
      "2 karty, 1 rekrutacja, 5 konsultantów",
    );
  });
});

describe("karta technologiczna", () => {
  it("rozdziela technologie ze słownika i wpisane tekstem", () => {
    const form = {
      ...initialCardForm(null, "2026-10-16"),
      status: "ok" as const,
      skills: [
        { id: 4, name: "java" },
        { id: null, name: "Platforma X" },
      ],
      vendors: [{ id: null, name: "Dostawca A" }],
      hiring: true,
      hiringSource: "widzial" as const,
      hiringRoles: "Java, QA",
      projectEndMonth: "2027-02",
      teamExternals: "4",
    };
    const payload = buildCardPayload(form, true);
    expect(payload.skill_ids).toEqual([4]);
    expect(payload.skill_names).toEqual(["Platforma X"]);
    expect(payload.new_vendor_names).toEqual(["Dostawca A"]);
    expect(payload.hiring_roles).toEqual(["Java", "QA"]);
    expect(payload.project_end_on).toBe("2027-02-28");
    expect(payload.team_externals).toBe(4);
    expect(payload.finalize).toBe(true);
  });

  it("bez „klient zatrudnia” nie wysyła źródła ani ról, „nie wie” zeruje koniec", () => {
    const form = {
      ...initialCardForm(card(1, "2026-10-01", { hiring: true, hiring_source: "plotka", hiring_roles: ["QA"] }), "2026-10-16"),
      hiring: false,
      projectEndMonth: "2027-01",
      projectEndUnknown: true,
      teamExternals: "kilka",
    };
    const payload = buildCardPayload(form, false);
    expect(payload.hiring).toBeNull();
    expect(payload.hiring_source).toBeNull();
    expect(payload.hiring_roles).toEqual([]);
    expect(payload.project_end_on).toBeNull();
    expect(payload.team_externals).toBeNull();
  });

  it("koniec projektu miesiącem = ostatni dzień miesiąca", () => {
    expect(monthEnd("2028-02")).toBe("2028-02-29");
    expect(monthEnd("2026-13")).toBeNull();
    expect(monthEnd("")).toBeNull();
    expect(monthOf("2026-12-31")).toBe("2026-12");
  });

  it("dzieli role po przecinku i średniku", () => {
    expect(splitNames("Java, QA;\n DevOps ,")).toEqual(["Java", "QA", "DevOps"]);
  });
});

describe("ekran /care", () => {
  const route = (query: string) => careRouteFrom(new URLSearchParams(query));

  it("zakładki 22.10.2026: Do zrobienia, Konsultanci, Klienci, Zespół opiekunów, Komunikaty", () => {
    expect(route("")).toEqual({ tab: "todo" });
    expect(route("tab=cokolwiek")).toEqual({ tab: "todo" });
    expect(route("tab=consultants")).toEqual({ tab: "consultants" });
    expect(route("tab=clients")).toEqual({ tab: "clients" });
    expect(route("tab=team")).toEqual({ tab: "team" });
    // Link z powiadomienia o komunikacie (etap 3, O12) działa dalej.
    expect(route("tab=announcements")).toEqual({ tab: "announcements" });
  });

  it("stare adresy prowadzą do nowych miejsc", () => {
    expect(route("tab=week")).toEqual({ tab: "todo" });
    expect(route("tab=contracts")).toEqual({ tab: "consultants" });
    expect(route("tab=mine")).toEqual({ tab: "consultants" });
    expect(route("tab=redeploy")).toEqual({ tab: "consultants", filter: "redeploy" });
    expect(route("tab=assignment")).toEqual({ tab: "team" });
    expect(route("tab=structure")).toEqual({ tab: "clients" });
    expect(route("tab=structure&client=12")).toEqual({ tab: "clients", redirect: "/clients/12?tab=ludzie" });
    expect(route("tab=structure&client=abc")).toEqual({ tab: "clients" });
    expect(route("tab=review")).toEqual({ tab: "todo", redirect: "/settings?item=skills" });
    // TCM nie wchodzi do Słownika — kolejka nazw ma własną pozycję w Ustawieniach.
    expect(careRouteFrom(new URLSearchParams("tab=review"), { canSeeSkills: false })).toEqual({
      tab: "todo",
      redirect: "/settings?item=skills-review",
    });
  });

  it("`?contract=` i dostęp do „Zespołu opiekunów”", () => {
    expect(contractParam("4501")).toBe(4501);
    expect(contractParam("0")).toBeNull();
    expect(contractParam("x")).toBeNull();
    expect(contractParam(null)).toBeNull();
    const me = { is_admin: false, back_office_head: false } as Parameters<typeof canSeeTeam>[0]["me"];
    expect(canSeeTeam({ me })).toBe(false);
    expect(canSeeTeam({ me: { ...me, back_office_head: true } })).toBe(true);
    expect(canSeeTeam({ me: { ...me, is_admin: true } })).toBe(true);
  });
});
