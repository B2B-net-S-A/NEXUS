import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationFactsSection } from "../ConversationFactsSection";
import { candidateFactsApi, type ConversationFactsResponse } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  candidateFactsApi: { getConversationFacts: vi.fn() },
}));

const getFacts = vi.mocked(candidateFactsApi.getConversationFacts);

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConversationFactsSection candidateId={7} />
    </QueryClientProvider>,
  );
}

const response = (overrides: Partial<ConversationFactsResponse> = {}): ConversationFactsResponse => ({
  candidate_id: 7,
  enabled: true,
  facts: [
    {
      id: 1,
      kind: "skill",
      value: "Optymalizacja zapytań PL/SQL",
      status: "confirmed",
      source: "sheet",
      noted_at: "2026-11-03T10:00:00Z",
      job_id: 5,
      job_title: "Programista baz danych",
      author_name: "Ewa Test",
      evidence: "3 lata w banku",
      job_only: false,
    },
    {
      id: 2,
      kind: "domain",
      value: "Energetyka",
      status: "absent",
      source: "sheet",
      noted_at: "2026-11-03T10:00:00Z",
      job_id: 5,
      job_title: null,
      author_name: null,
      evidence: null,
      job_only: true,
    },
    {
      id: 3,
      kind: "skill",
      value: "Apache Airflow",
      status: "confirmed",
      source: "note_ai",
      noted_at: "2026-10-01T10:00:00Z",
      job_id: null,
      job_title: null,
      author_name: null,
      evidence: null,
      job_only: false,
    },
  ],
  ...overrides,
});

describe("ConversationFactsSection", () => {
  beforeEach(() => getFacts.mockReset());

  it("pokazuje źródło, datę, zakres i brak przycisku potwierdzania", async () => {
    getFacts.mockResolvedValue(response());
    renderSection();
    expect(await screen.findByText("Optymalizacja zapytań PL/SQL")).toBeInTheDocument();
    expect(screen.getByText("z arkusza")).toBeInTheDocument();
    expect(screen.getByText("z notatek (AI)")).toBeInTheDocument();
    expect(screen.getByText("Nie ma")).toBeInTheDocument();
    expect(screen.getByText(/tylko ta rekrutacja/)).toBeInTheDocument();
    expect(screen.getByText(/Ewa Test · 3\.11\.2026|Ewa Test · 03\.11\.2026/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /potwierd/i })).toBeNull();
  });

  it("przy wyłączonej fladze bloku nie ma", async () => {
    getFacts.mockResolvedValue(response({ enabled: false, facts: [] }));
    const { container } = renderSection();
    await waitFor(() => expect(getFacts).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("awaria zapytania nie wygląda jak brak faktów", async () => {
    getFacts.mockRejectedValueOnce(new Error("500"));
    renderSection();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się wczytać faktów z rozmów.");
  });
});
