/**
 * „Pytania z mapy klienta” w oknie rozmowy: wybór osoby przy „Komu podlega”
 * tylko z prawem edycji struktury klienta (`can_edit_org`) — bez niego sama
 * notatka (serwer odmawia 403 ORG_DENIED).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => mocks.get(...a), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));

import type { ClientQuestion } from "@/lib/api/care";

import { CareGapQuestions } from "../CareGapQuestions";

const QUESTION = {
  key: "reports_to:11",
  kind: "reports_to",
  subject: "Ewa Przykładowa",
  detail: null,
  contact_id: 11,
} as unknown as ClientQuestion;

function org(canEdit: boolean) {
  return {
    client_id: 5,
    client_name: "Firma Przykładowa",
    areas: [],
    departments: [{ people: [{ id: 12, name: "Jan Przykładowy", position: null }] }],
    without_manager: [],
    requests: [],
    people_count: 1,
    consultants_count: 1,
    can_edit_org: canEdit,
    can_write_feedback: canEdit,
  };
}

function renderQuestions() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CareGapQuestions clientId={5} questions={[QUESTION]} answers={{}} onChange={() => undefined} />
    </QueryClientProvider>,
  );
}

describe("CareGapQuestions", () => {
  beforeEach(() => mocks.get.mockReset());

  it("bez prawa edycji struktury: sama notatka, bez wyboru osoby", async () => {
    mocks.get.mockResolvedValue({ data: org(false) });
    renderQuestions();
    expect(await screen.findByText(/odpowiedz notatką/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /Odpowiedź/ })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /Notatka/ })).toBeInTheDocument();
  });

  it("z prawem edycji struktury: wybór osoby", async () => {
    mocks.get.mockResolvedValue({ data: org(true) });
    renderQuestions();
    expect(await screen.findByRole("combobox", { name: /Odpowiedź/ })).toBeInTheDocument();
  });
});
