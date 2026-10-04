/**
 * „Profil Championa” → „Klient i historia” (04.10.2026): karta klienta,
 * pytania klienta z rozmów, wiedza z rozmów i wcześniejsze zapytania —
 * do tej pory na końcu długiej strony „Podgląd”.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionClientTab } from "@/components/champion/ChampionClientTab";

const getMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: { ...actual.championApi, get: (...args: unknown[]) => getMock(...args) },
  };
});
vi.mock("@/components/client-playbook/ClientPlaybookCard", () => ({
  ClientPlaybookCard: () => <div data-testid="playbook-card" />,
}));
vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: ({ readOnly }: { readOnly: boolean }) => (
    <div data-testid="request-history" data-read-only={String(readOnly)} />
  ),
}));
vi.mock("@/components/champion/plain/PlainBriefBlock", () => ({
  PlainBriefBlock: ({ parts }: { parts?: string }) => (
    <div data-testid="plain-brief-block" data-parts={parts} />
  ),
}));
vi.mock("@/components/ChampionClientQuestionsPanel", () => ({
  ChampionClientQuestionsPanel: ({ canEdit }: { canEdit: boolean }) => (
    <div data-testid="client-questions" data-can-edit={String(canEdit)} />
  ),
}));

beforeEach(() => {
  getMock.mockReset();
  getMock.mockResolvedValue({
    data: {
      job_id: 5,
      champion_profile: {
        client: { selling_points: "", sectors: ["bankowość"], historical_questions: "" },
        insights: [
          { id: "n1", topic: "ask_client", text: "Ile dni w biurze?", source: "manual", audience: "team" },
        ],
      },
    },
  });
});

function renderTab(onEditBlock?: (block: string) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChampionClientTab jobId={5} clientId={9} onEditBlock={onEditBlock} requestHistoryReadOnly />
    </QueryClientProvider>,
  );
}

describe("ChampionClientTab", () => {
  it("zbiera klienta i historię w jednym miejscu", async () => {
    renderTab();
    expect(await screen.findByText("Branże klienta: bankowość")).toBeInTheDocument();
    expect(screen.getByTestId("plain-brief-block")).toHaveAttribute("data-parts", "client");
    expect(screen.getByTestId("playbook-card")).toBeInTheDocument();
    // Pytania klienta z rozmów — tylko do odczytu (dopisuje się je w edycji).
    expect(screen.getByTestId("client-questions")).toHaveAttribute("data-can-edit", "false");
    expect(screen.getByText("Ile dni w biurze?")).toBeInTheDocument();
    expect(screen.getByTestId("request-history")).toHaveAttribute("data-read-only", "true");
  });

  it("„Edytuj” otwiera szufladę klienta i wiedzy z rozmów; bez prawa edycji — brak przycisków", async () => {
    const onEdit = vi.fn();
    renderTab(onEdit);
    await userEvent.click(await screen.findByRole("button", { name: "Edytuj: Karta klienta" }));
    expect(onEdit).toHaveBeenCalledWith("client");
    await userEvent.click(screen.getByRole("button", { name: "Edytuj: Wiedza z rozmów" }));
    expect(onEdit).toHaveBeenCalledWith("insights");
  });

  it("bez prawa edycji nie ma przycisków „Edytuj”", async () => {
    renderTab(undefined);
    await screen.findByText("Branże klienta: bankowość");
    expect(screen.queryByRole("button", { name: /^Edytuj:/ })).toBeNull();
  });
});
