import { describe, expect, it } from "vitest";

import {
  careTimeline,
  conversationSignals,
  sourceSummary,
  splitNames,
  technologiesInArea,
} from "@/components/care/care-format";
import { buildCardPayload, initialCardForm } from "@/components/care/TechCardDialog";
import { careTabFrom } from "@/components/care/CareScreen";
import { monthEnd, monthOf, type CareConversation, type MapTechnology, type TechCard } from "@/lib/api/care";

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
  it("filtruje po obszarze, pusty filtr zostawia wszystko", () => {
    const list = [tech("Java", ["Płatności"]), tech("Kafka", ["Data"])];
    expect(technologiesInArea(list, null)).toHaveLength(2);
    expect(technologiesInArea(list, "Data").map((t) => t.name)).toEqual(["Kafka"]);
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
  it("czyta zakładkę z adresu, nieznana = „Ten tydzień”, dawne listy = „Konsultanci”", () => {
    expect(careTabFrom("redeploy")).toBe("redeploy");
    expect(careTabFrom("review")).toBe("review");
    expect(careTabFrom("consultants")).toBe("consultants");
    expect(careTabFrom("assignment")).toBe("assignment");
    // Link z powiadomienia o komunikacie (etap 3, O12).
    expect(careTabFrom("announcements")).toBe("announcements");
    expect(careTabFrom("contracts")).toBe("consultants");
    expect(careTabFrom("mine")).toBe("consultants");
    expect(careTabFrom("cokolwiek")).toBe("week");
    expect(careTabFrom(null)).toBe("week");
  });
});
