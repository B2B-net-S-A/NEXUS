import { describe, expect, it } from "vitest";

import type { CaseCard } from "@/lib/api/admin-cases";

import {
  BOARD_COLUMNS,
  addChecklistItem,
  caseSubline,
  dueLabel,
  fileSize,
  groupByStatus,
  removeChecklistItem,
  toggleChecklistItem,
} from "../case-format";

function card(overrides: Partial<CaseCard> = {}): CaseCard {
  return {
    id: 1,
    title: "Polisa OC dla konsultanta",
    area: "administration",
    priority: "P2",
    status: "new",
    due_on: "2026-10-20",
    follow_up_on: null,
    overdue: false,
    assignee: null,
    subject_user: null,
    contract: null,
    source: "manual",
    checklist_done: 0,
    checklist_total: 0,
    created_at: "2026-10-16T08:00:00Z",
    updated_at: "2026-10-16T08:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

describe("daty spraw", () => {
  it("termin: po terminie liczy serwer, zrobiona sprawa nie ma terminu", () => {
    expect(dueLabel(card())).toEqual({ text: "do 20.10", overdue: false });
    expect(dueLabel(card({ overdue: true }))).toEqual({
      text: "po terminie · 20.10",
      overdue: true,
    });
    expect(dueLabel(card({ status: "done", overdue: true }))).toBeNull();
    expect(dueLabel(card({ due_on: null }))).toBeNull();
  });
});

describe("tablica", () => {
  it("rozkłada karty po kolumnach i pomija zamknięte bez kolumny", () => {
    const grouped = groupByStatus(
      [
        card({ id: 1, status: "new" }),
        card({ id: 2, status: "waiting" }),
        card({ id: 3, status: "closed" }),
        card({ id: 4, status: "new" }),
      ],
      BOARD_COLUMNS,
    );
    expect(grouped.new.map((c) => c.id)).toEqual([1, 4]);
    expect(grouped.waiting.map((c) => c.id)).toEqual([2]);
    expect(grouped.closed).toEqual([]);
  });

  it("druga linijka: osoba i klient z kontraktu, inaczej pracownik", () => {
    expect(
      caseSubline(
        card({
          contract: {
            id: 7,
            candidate_name: "Anna Przykładowa",
            client_name: "Arkada Przykładowa",
            start_date: null,
            end_date: null,
          },
        }),
      ),
    ).toBe("Anna Przykładowa · Arkada Przykładowa");
    expect(caseSubline(card({ subject_user: { id: 3, name: "Tomasz Przykładowy" } }))).toBe(
      "Tomasz Przykładowy",
    );
    expect(caseSubline(card())).toBeNull();
  });
});

describe("checklista", () => {
  const items = [
    { text: "Badania", done: false },
    { text: "BHP", done: true },
  ];

  it("przełącza, dodaje i usuwa bez mutowania wejścia", () => {
    expect(toggleChecklistItem(items, 0)[0].done).toBe(true);
    expect(items[0].done).toBe(false);
    expect(addChecklistItem(items, "  Dostęp VPN ")).toHaveLength(3);
    expect(addChecklistItem(items, "   ")).toHaveLength(2);
    expect(removeChecklistItem(items, 1)).toEqual([{ text: "Badania", done: false }]);
  });
});

it("rozmiar załącznika", () => {
  expect(fileSize(null)).toBe("");
  expect(fileSize(200)).toBe("1 kB");
  expect(fileSize(350 * 1024)).toBe("350 kB");
  expect(fileSize(1.25 * 1024 * 1024)).toBe("1,3 MB");
});
