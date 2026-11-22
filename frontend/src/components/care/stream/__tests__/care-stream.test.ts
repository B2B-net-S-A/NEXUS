import { describe, expect, it } from "vitest";

import type { ContractTimelineItem } from "@/lib/api";
import type { CareConversation, TechCard, TimelineEvent } from "@/lib/api/care";
import type { ContractFeedbackItem } from "@/lib/api/client-people";

import {
  buildCareStream,
  filterStream,
  isLongText,
  streamCounts,
  tidyText,
  visibleFilters,
  withMentionNames,
} from "../care-stream";

function note(overrides: Partial<ContractTimelineItem> = {}): ContractTimelineItem {
  return {
    id: 1,
    kind: "note",
    at: "2026-11-10T09:30:00Z",
    summary: null,
    content: "Klient chce przedłużyć do marca.",
    sub_type: "general",
    status: null,
    author_id: 7,
    author_name: "jan.testowy@firma.test",
    duration_seconds: null,
    ...overrides,
  };
}

function talk(overrides: Partial<CareConversation> = {}): CareConversation {
  return {
    id: 2,
    occurred_on: "2026-11-12",
    channel: "phone",
    satisfaction: 4,
    note: "Wszystko w porządku.\n\n\nProjekt do lutego.",
    attrition_risk: false,
    wants_change: true,
    project_end_on: null,
    client_hiring: false,
    client_hiring_note: null,
    follow_up_on: "2026-12-12",
    author: { id: 3, name: "Natalia Opiekunka" },
    ...overrides,
  };
}

function techCard(overrides: Partial<TechCard> = {}): TechCard {
  return {
    id: 31,
    contract_id: 5,
    client_id: 3,
    interview_on: "2026-11-05",
    status: "ok",
    is_draft: false,
    finalized_at: null,
    satisfaction: null,
    area: { id: 1, name: "Płatności" },
    skills: [
      { id: 1, name: "Java" },
      { id: 2, name: "Kafka" },
    ],
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
    memorable_quote: "Zespół rośnie.",
    note: null,
    sales_status: null,
    author: null,
    ...overrides,
  };
}

function feedback(overrides: Partial<ContractFeedbackItem> = {}): ContractFeedbackItem {
  return {
    session_id: 9,
    held_on: "2026-11-08",
    channel: "teams",
    contact: { id: 4, name: "Piotr Menedżerski" },
    quality: 4,
    communication: 5,
    autonomy: null,
    average: 4.5,
    extension_outlook: "likely",
    note: "Chwali samodzielność.",
    author: { id: 3, name: "Natalia Opiekunka" },
    ...overrides,
  };
}

function event(kind: TimelineEvent["kind"], on: string, title: string, future = false): TimelineEvent {
  return { kind, on, title, detail: null, link: null, future };
}

describe("buildCareStream", () => {
  it("łączy źródła od najnowszych, z rozmową, kartą, opinią i notatką", () => {
    const items = buildCareStream({
      notes: [note()],
      conversations: [talk()],
      techCards: [techCard()],
      feedback: [feedback()],
    });
    expect(items.map((item) => item.kind)).toEqual(["consultant", "note", "client", "project"]);
    const [conversation, contractNote, opinion, card] = items;
    expect(conversation.title).toBe("Rozmowa z konsultantem · telefon");
    expect(conversation.body).toBe("Wszystko w porządku.\nProjekt do lutego.");
    expect(conversation.facts).toEqual(["zadowolenie 4 / 5", "chce zmiany projektu", "następny kontakt 12.12.2026"]);
    expect(conversation.author).toBe("Natalia Opiekunka");
    // Adres e-mail autora notatki nie trafia na ekran — imię i nazwisko.
    expect(contractNote.author).toBe("Jan Testowy");
    expect(contractNote.title).toBe("Notatka");
    expect(opinion.title).toBe("Rozmowa z klientem · teams · Piotr Menedżerski");
    expect(opinion.facts).toEqual(["Jakość pracy 4", "Komunikacja 5", "średnio 4,5 / 5", "przedłużenie: raczej tak"]);
    expect(card.body).toBe("„Zespół rośnie.”");
    expect(card.facts).toEqual(["dział Płatności", "technologie: 2"]);
    expect(card.techCard).toEqual({ id: 31, on: "2026-11-05" });
  });

  it("notatka z północy w Warszawie ma dzień Warszawy, nie UTC", () => {
    const [item] = buildCareStream({ notes: [note({ at: "2026-11-09T23:30:00Z" })] });
    expect(item.day).toBe("2026-11-10");
  });

  it("w tym samym dniu wcześniej stoi zapis z późniejszą godziną", () => {
    const items = buildCareStream({
      notes: [note({ id: 1, at: "2026-11-10T08:00:00Z" }), note({ id: 2, at: "2026-11-10T15:00:00Z" })],
    });
    expect(items.map((item) => item.key)).toEqual(["note-2", "note-1"]);
  });

  it("szkic karty, plan, zdarzenia umowy i rozmowy z osi opieki nie wchodzą; zmiany w opiece — wyszarzone", () => {
    const items = buildCareStream({
      techCards: [techCard({ is_draft: true })],
      timeline: [
        event("plan", "2026-12-01", "Plan: rozmowa według rytmu", true),
        event("order_start", "2026-07-01", "Zamówienie „123”"),
        event("conversation", "2026-11-12", "Rozmowa · telefon"),
        event("owner", "2026-11-02", "Opiekun: Natalia Opiekunka"),
        event("case_opened", "2026-11-03", "Sprawa otwarta: Dostęp do VPN"),
      ],
    });
    expect(items.map((item) => item.title)).toEqual(["Sprawa otwarta: Dostęp do VPN", "Opiekun: Natalia Opiekunka"]);
    expect(items.every((item) => item.quiet && item.kind === "care")).toBe(true);
  });

  it("połączenie: kierunek słowem, treść ze streszczenia, minuty zamiast sekund", () => {
    const [item] = buildCareStream({
      notes: [note({ kind: "call", sub_type: "outbound", summary: "Umówiony start.", content: "pełna transkrypcja", duration_seconds: 95 })],
    });
    expect(item.title).toBe("Połączenie wychodzące");
    expect(item.body).toBe("Umówiony start.");
    expect(item.facts).toEqual(["2 min"]);
  });

  it("rodzaj notatki słowem; nieznany to zwykła notatka", () => {
    const items = buildCareStream({
      notes: [note({ id: 1, sub_type: "email" }), note({ id: 2, sub_type: "dziwny", at: "2026-11-09T09:00:00Z" })],
    });
    expect(items.map((item) => item.title)).toEqual(["Notatka · e-mail", "Notatka"]);
  });

  it("rozmiar zespołu bez podwójnego „osób”", () => {
    const [range] = buildCareStream({ techCards: [techCard({ team_size: "10-15" })] });
    const [worded] = buildCareStream({ techCards: [techCard({ team_size: "9 osób" })] });
    expect(range.facts).toContain("zespół 10-15 osób");
    expect(worded.facts).toContain("zespół 9 osób");
  });

  it("puste źródła to pusty strumień", () => {
    expect(buildCareStream({})).toEqual([]);
    expect(buildCareStream({ notes: null, conversations: undefined })).toEqual([]);
  });
});

describe("filtry strumienia", () => {
  const items = buildCareStream({
    notes: [note()],
    conversations: [talk()],
    techCards: [techCard()],
    timeline: [event("owner", "2026-11-02", "Opiekun: Natalia Opiekunka")],
  });

  it("liczy rodzaje i filtruje", () => {
    expect(streamCounts(items)).toEqual({ all: 4, talks: 2, notes: 1, feedback: 0, care: 1 });
    expect(filterStream(items, "talks").map((item) => item.kind)).toEqual(["consultant", "project"]);
    expect(filterStream(items, "all")).toHaveLength(4);
  });

  it("pokazuje tylko filtry z czymś w środku, a przy jednym rodzaju żadnych", () => {
    expect(visibleFilters(streamCounts(items))).toEqual(["all", "talks", "notes", "care"]);
    expect(visibleFilters(streamCounts(buildCareStream({ notes: [note()] })))).toEqual([]);
  });
});

describe("treść", () => {
  it("wzmianka „@adres” pokazuje imię i nazwisko", () => {
    expect(withMentionNames("Proszę @anna.przykladowa@firma.test o umowę")).toBe("Proszę @Anna Przykladowa o umowę");
    expect(withMentionNames("bez wzmianek")).toBe("bez wzmianek");
  });

  it("puste linie znikają, pusta treść to brak treści", () => {
    expect(tidyText("a\n\n\nb\r\n\r\nc")).toBe("a\nb\nc");
    expect(tidyText("   ")).toBeNull();
    expect(tidyText(null)).toBeNull();
  });

  it("„Rozwiń” przy długiej treści albo wielu liniach", () => {
    expect(isLongText("x".repeat(241))).toBe(true);
    expect(isLongText("a\nb\nc\nd")).toBe(true);
    expect(isLongText("krótko")).toBe(false);
    expect(isLongText(null)).toBe(false);
  });
});
