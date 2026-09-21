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

  it("„Praca w tle”: pusty stan z wyjaśnieniem albo przekazane zdarzenia", () => {
    const view = renderSheet({ initialTab: "background" });
    expect(
      screen.getByText(
        "Tu pojawią się zdarzenia automatów (przegląd bazy, nowe CV, wygenerowane CV).",
      ),
    ).toBeInTheDocument();
    view.unmount();

    renderSheet({
      initialTab: "background",
      backgroundEvents: [{ when: "dziś 7:00", label: "Przegląd całej bazy: 52 propozycje" }],
    });
    expect(screen.getByText("Przegląd całej bazy: 52 propozycje")).toBeInTheDocument();
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
