import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchTeamsForClient: vi.fn(),
  splitTeamRequest: vi.fn(),
}));
vi.mock("@/lib/api/jobTeams", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/jobTeams")>()),
  fetchTeamsForClient: api.fetchTeamsForClient,
  splitTeamRequest: api.splitTeamRequest,
}));

import { NewJobTeamRequestCard, teamChoiceProblem } from "../NewJobTeamRequestCard";

function renderCard(onUse = vi.fn(), requestText = "Szukamy 2 testerów manualnych i jednego analityka biznesowego.") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NewJobTeamRequestCard
        clientId={7}
        value={{ mode: "team", teamId: null, newName: "" }}
        onChange={() => undefined}
        requestText={requestText}
        onUsePosition={onUse}
      />
    </QueryClientProvider>,
  );
  return onUse;
}

describe("/jobs/new: stanowisko w zespole", () => {
  beforeEach(() => {
    sessionStorage.clear();
    api.fetchTeamsForClient.mockResolvedValue([]);
  });

  it("zespół bez wyboru i bez nazwy nowego blokuje utworzenie", () => {
    expect(teamChoiceProblem({ mode: "team", teamId: null, newName: " " })).toMatch(/Wybierz zespół/);
    expect(teamChoiceProblem({ mode: "team", teamId: 3, newName: "" })).toBeNull();
    expect(teamChoiceProblem({ mode: "one" })).toBeNull();
  });

  it("rozbija zapytanie i „Użyj” przekazuje rolę i liczbę osób", async () => {
    const user = userEvent.setup();
    api.splitTeamRequest.mockResolvedValue({
      positions: [
        { title: "Tester manualny", headcount: 2, seniority: null, words: ["testy manualne"] },
        { title: "Analityk biznesowy", headcount: 1, seniority: "senior", words: [] },
      ],
    });
    const onUse = renderCard();
    await user.click(await screen.findByRole("button", { name: "Rozbij zapytanie na stanowiska" }));
    expect(await screen.findByText("Tester manualny")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Użyj" })[0]);
    expect(onUse).toHaveBeenCalledWith(expect.objectContaining({ title: "Tester manualny", headcount: 2 }));
    expect(screen.getByText("użyte")).toBeInTheDocument();
  });

  it("pusty odczyt mówi o tym zamiast pokazywać pustą listę", async () => {
    const user = userEvent.setup();
    api.splitTeamRequest.mockResolvedValue({ positions: [] });
    renderCard();
    await user.click(await screen.findByRole("button", { name: "Rozbij zapytanie na stanowiska" }));
    expect(await screen.findByText(/nie znalazł w treści stanowisk/)).toBeInTheDocument();
  });

  it("bez treści zapytania przycisk jest nieaktywny i podpowiada, skąd ją wziąć", async () => {
    renderCard(vi.fn(), "");
    expect(await screen.findByRole("button", { name: "Rozbij zapytanie na stanowiska" })).toBeDisabled();
    expect(screen.getByText(/Wklej treść zapytania/)).toBeInTheDocument();
  });
});
