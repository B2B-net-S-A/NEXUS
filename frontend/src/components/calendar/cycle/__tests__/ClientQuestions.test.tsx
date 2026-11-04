/**
 * Panel kandydata w kalendarzu pokazywał 6 pytań z rekrutacji i nie było jak
 * zobaczyć reszty bez listy całego klienta (zgłoszenie 04.11.2026).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => apiGet(...a) },
}));

import { ClientQuestions } from "@/components/calendar/cycle/ClientQuestions";

const questions = (count: number) =>
  Array.from({ length: count }, (_, i) => ({ id: i + 1, text: `Pytanie ${i + 1}` }));

function renderQuestions(roomy = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientQuestions jobId={10} clientName="Alior" roomy={roomy} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ClientQuestions", () => {
  it("panel pokazuje 6 pytań, a przycisk rozwija resztę z tej rekrutacji", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({ data: questions(9) });
    renderQuestions();
    const panel = await screen.findByTestId("cycle-client-questions");
    expect(within(panel).getAllByRole("listitem")).toHaveLength(6);

    await user.click(within(panel).getByRole("button", { name: "Pokaż wszystkie z tej rekrutacji (9)" }));
    expect(within(panel).getAllByRole("listitem")).toHaveLength(9);

    await user.click(within(panel).getByRole("button", { name: "Pokaż mniej" }));
    expect(within(panel).getAllByRole("listitem")).toHaveLength(6);
  });

  it("do 6 pytań nie ma czego rozwijać", async () => {
    apiGet.mockResolvedValue({ data: questions(6) });
    renderQuestions();
    const panel = await screen.findByTestId("cycle-client-questions");
    expect(within(panel).getAllByRole("listitem")).toHaveLength(6);
    expect(within(panel).queryByRole("button", { name: /z tej rekrutacji/ })).not.toBeInTheDocument();
  });

  it("duża strefa pokazuje całą listę od razu", async () => {
    apiGet.mockResolvedValue({ data: questions(9) });
    renderQuestions(true);
    const panel = await screen.findByTestId("cycle-client-questions");
    expect(within(panel).getAllByRole("listitem")).toHaveLength(9);
    expect(within(panel).queryByRole("button", { name: /z tej rekrutacji/ })).not.toBeInTheDocument();
  });

  it("pobiera więcej niż 50 pytań, żeby „wszystkie” było prawdą", async () => {
    apiGet.mockResolvedValue({ data: questions(1) });
    renderQuestions();
    await screen.findByTestId("cycle-client-questions");
    expect(apiGet).toHaveBeenCalledWith(
      "/api/interview-cycle/client-questions",
      expect.objectContaining({ params: { job_id: 10, limit: 200 } }),
    );
  });
});
