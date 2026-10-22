/**
 * Kafelek sprawy: „bez osoby” tylko wtedy, gdy naprawdę nikt nie prowadzi.
 * Przy „Moi podopieczni” bez dostępu do sprawy osoba jest ukryta
 * (`assignee_hidden`) — to nie jest „bez osoby” (przegląd 22.10.2026).
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseTile } from "@/components/work-board/CaseTile";
import type { CaseCard } from "@/lib/api/admin-cases";

function card(overrides: Partial<CaseCard>): CaseCard {
  return {
    id: 1,
    title: "Sprawa: Administracja",
    area: "administration",
    priority: "P3",
    status: "new",
    due_on: null,
    follow_up_on: null,
    overdue: false,
    assignee: null,
    subject_user: null,
    contract: null,
    source: "manual",
    checklist_done: 0,
    checklist_total: 0,
    created_at: "2026-10-20T08:00:00Z",
    updated_at: "2026-10-20T08:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function renderTile(value: CaseCard) {
  return render(
    <CaseTile card={value} onOpen={() => {}} onTake={null} taking={false} onMove={null} column="new" />,
  );
}

describe("CaseTile", () => {
  it("bez prowadzącego pisze „bez osoby”", () => {
    renderTile(card({}));
    expect(screen.getByText("bez osoby")).toBeInTheDocument();
  });

  it("ukryta osoba prowadząca to nie „bez osoby”", () => {
    renderTile(card({ assignee_hidden: true, content_hidden: true }));
    expect(screen.queryByText("bez osoby")).toBeNull();
  });
});
