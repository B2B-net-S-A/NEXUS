import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

import { HoldChecksPanel } from "@/components/v2/jobs/hold/HoldChecksPanel";
import type { HoldCheckItem } from "@/lib/job-hold";

const ITEM: HoldCheckItem = {
  job_id: 9101,
  title: "Analityk procesów",
  client_name: "Klient Alfa",
  reference: "90001",
  priority: "medium",
  work_state: "searching",
  recruiter_moves_7d: 12,
  recruiters_7d: 3,
  signals: [
    { kind: "report", at: "2026-11-26T09:53:00", by_name: "Anna Przykładowa", text: "Stoi?" },
    { kind: "dl_silent", at: null, text: "Twój ostatni ruch 09.06" },
  ],
};

function renderPanel(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HoldChecksPanel enabled={enabled} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("HoldChecksPanel", () => {
  it("pusta lista = panelu nie ma", async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } });
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalledWith("/api/hold-checks", { params: undefined }));
    expect(container).toBeEmptyDOMElement();
  });

  it("w trakcie ładowania nic nie udaje pustej listy ani panelu", () => {
    get.mockReturnValue(new Promise(() => undefined));
    const { container } = renderPanel();
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria = komunikat, nie pusta lista", async () => {
    get.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500, data: { detail: "Błąd serwera testowy" } } }),
    );
    renderPanel();
    expect(await screen.findByTestId("hold-checks-error")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/./);
    expect(screen.queryByTestId("hold-checks-panel")).not.toBeInTheDocument();
  });

  it("lista: numer, tytuł, sygnał, ruchy rekruterów; „Szukamy” odpowiada DL-em", async () => {
    get.mockResolvedValue({ data: { items: [ITEM], total: 1 } });
    post.mockResolvedValue({ data: { ok: true } });
    renderPanel();
    const row = await screen.findByTestId("hold-check-row");
    expect(row).toHaveTextContent("90001");
    expect(row).toHaveTextContent("Analityk procesów · Klient Alfa");
    expect(row).toHaveTextContent("Anna P. pyta (26.11): „Stoi?”");
    expect(row).toHaveTextContent("12 ruchów 3 rekruterów w 7 dni");
    expect(screen.getByRole("link", { name: "Otwórz" })).toHaveAttribute("href", "/jobs/9101");
    expect(screen.getByText(/1 do potwierdzenia/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("hold-check-searching"));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/jobs/9101/hold-check", { answer: "searching" }),
    );
  });

  it("bez roli nie pyta serwera", () => {
    const { container } = renderPanel(false);
    expect(get).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });
});
