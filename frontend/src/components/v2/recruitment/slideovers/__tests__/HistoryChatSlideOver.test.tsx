import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

describe("HistoryChatSlideOver", () => {
  it("zamknięte okno nie montuje czatu ani historii", () => {
    renderSheet({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-chat")).not.toBeInTheDocument();
    expect(screen.queryByTestId("request-history")).not.toBeInTheDocument();
  });

  it("„Wszystko”: tytuł, pięć zakładek, ruchy + skrót historii + pełny czat", () => {
    renderSheet({ chatUnreadCount: 3 });
    const dialog = screen.getByRole("dialog", { name: "Historia i czat" });
    for (const name of [/Wszystko/, /Czat zespołu/, /Ruchy/, /Zmiany zlecenia/, /Praca w tle/]) {
      expect(within(dialog).getByRole("tab", { name })).toBeInTheDocument();
    }
    expect(within(dialog).getByRole("tab", { name: /Czat zespołu/ })).toHaveTextContent("3");
    expect(within(dialog).getByRole("link", { name: "Ola Kot" })).toHaveAttribute(
      "href",
      "/candidates/12",
    );
    expect(within(dialog).getByTestId("request-history")).toHaveAttribute("data-compact", "true");
    expect(within(dialog).getByTestId("job-chat")).toBeInTheDocument();
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

  it("„Ruchy” bez wczytanego kanbana mówi o ładowaniu, nie o pustej rekrutacji", () => {
    renderSheet({ initialTab: "moves", columns: undefined });
    expect(screen.getByText("Ładowanie osób w rekrutacji…")).toBeInTheDocument();
  });

  it("przełączenie zakładki kliknięciem", () => {
    renderSheet();
    const tab = screen.getByRole("tab", { name: /Ruchy/ });
    fireEvent.mouseDown(tab);
    fireEvent.click(tab);
    expect(screen.getByText(/Ostatni ruch każdej osoby/)).toBeInTheDocument();
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
