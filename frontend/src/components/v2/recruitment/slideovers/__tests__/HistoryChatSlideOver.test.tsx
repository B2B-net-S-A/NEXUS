import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), listMessages: vi.fn(), markRead: vi.fn() }));
vi.mock("@/lib/api", () => ({
  default: { get: api.get },
  jobChatApi: { listMessages: api.listMessages, markRead: api.markRead },
}));

vi.mock("@/components/v2/pages/JobChatTab", () => ({
  default: ({ jobId, readOnly }: { jobId: number; readOnly: boolean }) => (
    <div data-testid="job-chat" data-job={jobId} data-read-only={String(readOnly)} />
  ),
}));
vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: ({ compact }: { compact?: boolean }) => (
    <div data-testid="request-history" data-compact={String(Boolean(compact))} />
  ),
}));

import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";

import { HistoryChatSlideOver } from "../HistoryChatSlideOver";
import { formatDaysAgo, latestMovesFromKanban } from "../history-moves";
import { renderWithQuery } from "./test-utils";

const COLUMNS: KanbanColumn[] = [
  {
    stage: "verified",
    name: "Zweryfikowany",
    count: 1,
    items: [
      { id: 1, candidate_id: 11, stage: "verified", name: "Marek", lastname: "Zieliński", days_in_stage: 4 },
    ],
  },
  {
    stage: "cv_sent",
    name: "CV Wysłane",
    count: 2,
    items: [
      { id: 2, candidate_id: 12, stage: "cv_sent", name: "Ola", lastname: "Kot", days_in_stage: 0 },
      { id: 3, candidate_id: 13, stage: "cv_sent", name: "Jan", lastname: "Lis" },
    ],
  },
];

function renderSheet(props: Partial<React.ComponentProps<typeof HistoryChatSlideOver>> = {}) {
  return renderWithQuery(
    <HistoryChatSlideOver
      open
      onOpenChange={vi.fn()}
      jobId={7}
      clientId={3}
      columns={COLUMNS}
      {...props}
    />,
  );
}

const move = (id: number, name: string | null, to: string) => ({
  id,
  candidate_id: 100 + id,
  candidate_name: name,
  from_stage_name: "Screening",
  to_stage_name: to,
  moved_by_name: "Anna Rekruter",
  moved_at: "2026-09-20T10:00:00Z",
  source: "nexus",
});

beforeEach(() => {
  vi.clearAllMocks();
  // Domyślnie: starszy backend bez dziennika ruchów → lista z tablicy.
  api.get.mockRejectedValue({ response: { status: 404 } });
  api.listMessages.mockResolvedValue({
    data: {
      items: [
        { id: 2, content: "Klient prosi o 2 profile do piątku", author: { id: 1, name: "Ewa" }, created_at: "2026-09-20T12:00:00Z" },
        { id: 1, content: "Startujemy", author: null, created_at: "2026-09-19T09:00:00Z" },
      ],
      has_more: false,
      next_before_id: null,
    },
  });
});

describe("HistoryChatSlideOver", () => {
  it("zamknięte okno nie montuje czatu ani historii", () => {
    renderSheet({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-chat")).not.toBeInTheDocument();
    expect(screen.queryByTestId("request-history")).not.toBeInTheDocument();
  });

  it("„Wszystko”: tytuł, pięć zakładek, ruchy + skrót historii + PODGLĄD czatu (bez oznaczania jako przeczytane)", async () => {
    renderSheet({ chatUnreadCount: 3 });
    const dialog = screen.getByRole("dialog", { name: "Historia i czat" });
    for (const name of [/Wszystko/, /Czat zespołu/, /Ruchy/, /Historia requestów/, /Praca w tle/]) {
      expect(within(dialog).getByRole("tab", { name })).toBeInTheDocument();
    }
    expect(within(dialog).queryByRole("tab", { name: /Zmiany zlecenia/ })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("tab", { name: /Czat zespołu/ })).toHaveTextContent("3");
    expect(await within(dialog).findByRole("link", { name: "Ola Kot" })).toHaveAttribute(
      "href",
      "/candidates/12",
    );
    expect(within(dialog).getByTestId("request-history")).toHaveAttribute("data-compact", "true");
    // Pełny czat oznacza wiadomości jako przeczytane przy montażu — tu go NIE MA.
    expect(within(dialog).queryByTestId("job-chat")).not.toBeInTheDocument();
    expect(await within(dialog).findByText("Klient prosi o 2 profile do piątku")).toBeInTheDocument();
    expect(api.listMessages).toHaveBeenCalledWith(7, { limit: 5 });
    expect(api.markRead).not.toHaveBeenCalled();
    // Skrót do czatu niesie liczbę nieprzeczytanych i przełącza zakładkę.
    fireEvent.click(within(dialog).getByRole("button", { name: "Otwórz czat (3 nieprzeczytane)" }));
    expect(within(dialog).getByTestId("job-chat")).toBeInTheDocument();
  });

  it("„Ruchy” czytają dziennik z serwera: autor, etapy, „Pokaż więcej”", async () => {
    api.get.mockImplementation((_url: string, config: { params: { offset: number } }) =>
      Promise.resolve({
        data:
          config.params.offset === 0
            ? { items: [move(1, "Ola Kot", "Zweryfikowany")], total: 2 }
            : { items: [move(2, null, "CV Wysłane")], total: 2 },
      }),
    );
    renderSheet({ initialTab: "moves" });
    expect(await screen.findByRole("link", { name: "Ola Kot" })).toHaveAttribute("href", "/candidates/101");
    expect(screen.getByText(/Screening → Zweryfikowany/)).toBeInTheDocument();
    expect(screen.getAllByText(/Anna Rekruter/).length).toBeGreaterThan(0);
    expect(api.get).toHaveBeenCalledWith("/api/pipeline/job/7/moves", { params: { limit: 50, offset: 0 } });
    fireEvent.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    // Nazwisko zredagowane dla roli bez odczytu kandydatów.
    expect(await screen.findByRole("link", { name: "Kandydat #102" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Pokaż więcej" })).not.toBeInTheDocument());
  });

  it("awaria dziennika ruchów (nie 404) jest błędem, nie listą z tablicy", async () => {
    api.get.mockRejectedValue({ response: { status: 500, data: { detail: "boom" } } });
    renderSheet({ initialTab: "moves" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać ruchów");
    expect(screen.queryByRole("link", { name: "Ola Kot" })).not.toBeInTheDocument();
  });

  it("initialTab=chat (stary ?tab=chat) pokazuje sam czat", () => {
    renderSheet({ initialTab: "chat", readOnly: true });
    expect(screen.getByRole("tab", { name: /Czat zespołu/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("job-chat")).toHaveAttribute("data-read-only", "true");
    expect(screen.queryByTestId("request-history")).not.toBeInTheDocument();
  });

  it("initialTab=request (stary ?tab=history) pokazuje pełną historię requestów", () => {
    renderSheet({ initialTab: "request" });
    expect(screen.getByTestId("request-history")).toHaveAttribute("data-compact", "false");
    expect(screen.queryByTestId("job-chat")).not.toBeInTheDocument();
  });

  it("initialTab działa przy każdym OTWARCIU, nie tylko przy montażu", () => {
    // Okno żyje na stronie cały czas; stary link ustawia zakładkę PO montażu.
    const client = new QueryClient();
    const tree = (open: boolean, initialTab: "all" | "chat") => (
      <QueryClientProvider client={client}>
        <HistoryChatSlideOver
          open={open}
          onOpenChange={vi.fn()}
          jobId={7}
          clientId={3}
          initialTab={initialTab}
        />
      </QueryClientProvider>
    );
    const view = render(tree(false, "all"));
    view.rerender(tree(true, "chat"));
    expect(screen.getByRole("tab", { name: /Czat zespołu/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByTestId("request-history")).not.toBeInTheDocument();
  });

  it("„Praca w tle”: pusty stan dopiero po UDANYM odczycie (i przy 404 starszego backendu)", async () => {
    const view = renderSheet({ initialTab: "background" });
    const empty = "Tu pojawią się zdarzenia automatów (przegląd bazy, nowe CV, wygenerowane CV).";
    expect(await screen.findByText(empty)).toBeInTheDocument();
    view.unmount();

    let release: (value: unknown) => void = () => {};
    api.get.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    renderSheet({ initialTab: "background" });
    expect(screen.getByText("Ładowanie pracy w tle…")).toBeInTheDocument();
    expect(screen.queryByText(empty)).not.toBeInTheDocument();
    release({ data: { job_id: 7, items: [], limit: 30 } });
    expect(await screen.findByText(empty)).toBeInTheDocument();
  });

  it("„Praca w tle”: błąd to błąd z „Ponów”, nigdy pusta lista", async () => {
    api.get.mockRejectedValue({ response: { status: 500, data: { detail: "boom" } } });
    renderSheet({ initialTab: "background" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać pracy w tle");
    expect(screen.queryByText(/Tu pojawią się zdarzenia automatów/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("„Praca w tle”: zdania po polsku, tony awarii i pominięcia, „Pokaż więcej” podnosi limit", async () => {
    const events = [
      { id: 40, kind: "auto_full_review_failed", created_at: "2026-09-21T05:00:00Z", reason: "stalled", message: "Przegląd stanął bez postępu i został przerwany." },
      { id: 39, kind: "cv_auto_generate_skipped", created_at: "2026-09-20T12:00:00Z", reason: "consent_screenshot_required", candidate: { id: 11, name: "Marek Zieliński" } },
      { id: 38, kind: "auto_full_review", created_at: "2026-09-20T05:00:00Z", proposals: 52, eligible: 140 },
    ];
    const filler = Array.from({ length: 27 }, (_, i) => ({
      id: 30 - i, kind: "new_cv_proposals", created_at: "2026-09-19T05:00:00Z", count: 2, trigger: "cv_ingest",
    }));
    api.get.mockImplementation((url: string, config: { params: { limit: number } }) =>
      url.endsWith("/background-events")
        ? Promise.resolve({ data: { job_id: 7, items: [...events, ...filler].slice(0, config.params.limit), limit: config.params.limit } })
        : Promise.reject({ response: { status: 404 } }),
    );
    renderSheet({ initialTab: "background" });
    const failed = (await screen.findByText(/Automatyczny przegląd bazy nie powiódł się\. Przegląd stanął/)).closest("li");
    expect(failed).toHaveAttribute("data-tone", "failed");
    expect(failed).toHaveTextContent("Awaria:");
    const skipped = screen
      .getByText(/Marek Zieliński: CV nie zostało wygenerowane automatycznie: reguła klienta wymaga zrzutu zgody RODO\./)
      .closest("li");
    expect(skipped).toHaveAttribute("data-tone", "skipped");
    expect(screen.getByText("Automatyczny przegląd bazy: 52 nowe propozycje (wymagania spełnia 140 osób).")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/api/jobs/7/background-events", { params: { limit: 30 } });
    fireEvent.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/api/jobs/7/background-events", { params: { limit: 60 } }),
    );
  });

  it("„Wszystko” pokazuje najwyżej 5 ostatnich zdarzeń pracy w tle i skrót do zakładki", async () => {
    api.get.mockImplementation((url: string) =>
      url.endsWith("/background-events")
        ? Promise.resolve({
            data: {
              job_id: 7,
              limit: 30,
              items: Array.from({ length: 7 }, (_, i) => ({
                id: 70 - i, kind: "new_cv_proposals", created_at: "2026-09-19T05:00:00Z", count: i + 1, trigger: "cv_ingest",
              })),
            },
          })
        : Promise.reject({ response: { status: 404 } }),
    );
    renderSheet();
    const list = await screen.findByRole("list", { name: "Praca w tle" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    expect(within(list).getByText("Nowe CV w bazie: 1 propozycja.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż całą pracę w tle" }));
    expect(screen.getByRole("tab", { name: /Praca w tle/ })).toHaveAttribute("aria-selected", "true");
  });

  it("„Ruchy” (tryb zastępczy) bez wczytanego kanbana mówi o ładowaniu, nie o pustej rekrutacji", async () => {
    renderSheet({ initialTab: "moves", columns: undefined });
    expect(await screen.findByText("Ładowanie osób w rekrutacji…")).toBeInTheDocument();
  });

  it("przełączenie zakładki kliknięciem", async () => {
    renderSheet();
    const tab = screen.getByRole("tab", { name: /Ruchy/ });
    fireEvent.mouseDown(tab);
    fireEvent.click(tab);
    expect(await screen.findByText(/Ostatni ruch każdej osoby/)).toBeInTheDocument();
  });
});

describe("history-moves", () => {
  it("sortuje od najświeższego ruchu; brak liczby dni ląduje na końcu", () => {
    expect(latestMovesFromKanban(COLUMNS).map((m) => m.fullName)).toEqual([
      "Ola Kot",
      "Marek Zieliński",
      "Jan Lis",
    ]);
  });

  it("formatuje dni po polsku", () => {
    expect([0, 1, 5, null].map(formatDaysAgo)).toEqual(["dziś", "wczoraj", "5 dni temu", "—"]);
  });
});
