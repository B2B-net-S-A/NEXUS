import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DlSendQueueResponse, DlSendRow } from "@/lib/api/boardTasks";
import { useAuthStore } from "@/store/auth";

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: apiMock, api: apiMock }));

import { DlSendTopbarButton } from "../DlSendTopbarButton";

function row(overrides: Partial<DlSendRow> = {}): DlSendRow {
  return {
    stage_id: 501,
    candidate_id: 21,
    candidate_name: "Marta Przykładowa",
    job_id: 31,
    job_title: "Java Developer",
    job_working_title: null,
    client_name: "Bank Przykładowy",
    ready_since: "2026-03-04T09:00:00Z",
    waiting_workdays: 4,
    urgency: "late",
    handed_over_by_name: "Ola Rekruterska",
    ...overrides,
  };
}

const QUEUE: DlSendQueueResponse = {
  ready: [
    row(),
    row({
      stage_id: 502,
      candidate_id: 22,
      candidate_name: "Tomasz Testowy",
      job_id: 32,
      job_title: "Analityk danych",
      job_working_title: "Analityk danych (BI)",
      client_name: "Telko Przykładowe",
      urgency: "due",
      waiting_workdays: 1,
      handed_over_by_name: null,
    }),
    // Nordea (13.10.2026): osoba czeka na akceptację do kolejki Cpro.
    row({ stage_id: 503, candidate_id: 23, candidate_name: "Adam Fikcyjny", urgency: "fresh", waiting_workdays: 0, cpro: true }),
  ],
  ready_total: 3,
  not_ready_total: 2,
  imported_total: 0,
  worst_urgency: "late",
};

function setViewer(role: string) {
  useAuthStore.setState({ user: { id: 7, role, roles: [role] } as never });
}

function renderButton() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DlSendTopbarButton />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.get.mockReset();
  apiMock.get.mockResolvedValue({ data: QUEUE });
  setViewer("delivery_lead");
});

describe("DlSendTopbarButton — licznik „Do wysłania” w górnym pasku", () => {
  it("konto bez roli Delivery Leada: bez zapytania i bez licznika", async () => {
    setViewer("recruiter");
    const { container } = renderButton();
    await Promise.resolve();
    expect(apiMock.get).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("pusta kolejka nie pokazuje licznika — pasek nie mówi „sprawdź, czy masz”", async () => {
    apiMock.get.mockResolvedValue({
      data: { ready: [], ready_total: 0, not_ready_total: 3, imported_total: 0, worst_urgency: null },
    });
    const { container } = renderButton();
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith("/api/board-tasks/dl-send"));
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria odczytu nie udaje zera ani licznika", async () => {
    apiMock.get.mockRejectedValue(new Error("boom"));
    const { container } = renderButton();
    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("licznik to liczba osób gotowych do wysłania, z pilnością w nazwie", async () => {
    renderButton();
    const pill = await screen.findByRole("button", {
      name: "Do wysłania do klienta: 3 osoby — ktoś czeka 2+ dni robocze",
    });
    expect(pill).toHaveTextContent("3");
  });

  it("okienko: wiersz prowadzi na Tablicę z otwartym przeglądem, stopka na pulpit i listę", async () => {
    renderButton();
    fireEvent.click(await screen.findByRole("button", { name: /^Do wysłania do klienta: 3 osoby/ }));

    expect(await screen.findByText("3 gotowe · 2 jeszcze u rekrutera")).toBeTruthy();
    const first = screen.getByRole("link", { name: /Marta Przykładowa/ });
    expect(first).toHaveAttribute("href", "/jobs/31?candidate=21&review=1");
    expect(first).toHaveTextContent("Java Developer · Bank Przykładowy · przekazał(a) Ola Rekruterska");
    // Tytuł dla rekrutera wygrywa z nazwą od klienta; bez osoby przekazującej nie ma dopisku.
    const second = screen.getByRole("link", { name: /Tomasz Testowy/ });
    expect(second).toHaveTextContent("Analityk danych (BI) · Telko Przykładowe");
    expect(second).not.toHaveTextContent("przekazał(a)");
    expect(second).not.toHaveTextContent("Cpro");
    // Nordea (14.10.2026): znacznik przy nazwisku, nie na końcu ucinanej linii.
    const nordea = screen.getByRole("link", { name: /Adam Fikcyjny/ });
    expect(nordea).toHaveTextContent("Java Developer · Bank Przykładowy · przekazał(a) Ola Rekruterska");
    expect(nordea).not.toHaveTextContent("→ Cpro");
    const badge = within(nordea).getByText("do Cpro");
    expect(badge.closest(".truncate")).toBeNull();

    expect(screen.getByRole("link", { name: "Przejrzyj po kolei (3)" })).toHaveAttribute(
      "href",
      "/dashboard?wysylka=po-kolei",
    );
    expect(screen.getByRole("link", { name: "Cała lista na pulpicie" })).toHaveAttribute(
      "href",
      "/dashboard#do-wyslania",
    );
    expect(screen.getByRole("link", { name: "Pokaż rekrutacje" })).toHaveAttribute(
      "href",
      "/jobs?open=1&tosend=mine",
    );
  });

  it("jedna osoba: bez „po kolei”; lista ucięta przez serwer mówi, ile pokazano", async () => {
    apiMock.get.mockResolvedValue({
      data: { ...QUEUE, ready: [row()], ready_total: 1, not_ready_total: 0, worst_urgency: "due" },
    });
    renderButton();
    fireEvent.click(
      await screen.findByRole("button", { name: "Do wysłania do klienta: 1 osoba — ktoś czeka od wczoraj" }),
    );
    expect(await screen.findByText("1 gotowa")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Przejrzyj po kolei/ })).toBeNull();
  });

  it("więcej osób niż wierszy: dopisek „Pokazano N z M”", async () => {
    apiMock.get.mockResolvedValue({ data: { ...QUEUE, ready_total: 40 } });
    renderButton();
    fireEvent.click(await screen.findByRole("button", { name: /^Do wysłania do klienta: 40 osób/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Pokazano 3 z 40 — najdłużej czekające.")).toBeTruthy();
  });
});
