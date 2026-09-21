import * as React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JobDetailCompactHeader } from "@/components/v2/jobs/JobDetailCompactHeader";
import type { JobDetailView } from "@/lib/job-detail-routing";

function renderHeader(
  overrides: Partial<React.ComponentProps<typeof JobDetailCompactHeader>> = {},
) {
  const onViewChange = vi.fn<(view: JobDetailView) => void>();
  const onOpenOrder = vi.fn();
  const onOpenHistoryChat = vi.fn();
  const onOpenQuestions = vi.fn();
  const onAddCandidate = vi.fn();
  const onEdit = vi.fn();

  const { unmount } = render(
    <JobDetailCompactHeader
      title="Senior Java Developer"
      referenceNumber="REF-505734"
      badges={<span>Aktywna</span>}
      metadata={<span>Warszawa</span>}
      activeView="people"
      onViewChange={onViewChange}
      onOpenOrder={onOpenOrder}
      onOpenHistoryChat={onOpenHistoryChat}
      onOpenQuestions={onOpenQuestions}
      onAddCandidate={onAddCandidate}
      onEdit={onEdit}
      chatUnreadCount={3}
      {...overrides}
    />,
  );

  return {
    onViewChange,
    onOpenOrder,
    onOpenHistoryChat,
    onOpenQuestions,
    onAddCandidate,
    onEdit,
    unmount,
  };
}

describe("JobDetailCompactHeader", () => {
  it("zawsze pokazuje identyfikację, status i główną akcję", async () => {
    const { onAddCandidate } = renderHeader();

    expect(
      screen.getByRole("heading", { name: "Senior Java Developer" }),
    ).toBeTruthy();
    expect(screen.getByText("REF-505734")).toBeTruthy();
    expect(screen.getByText("Aktywna")).toBeTruthy();

    await userEvent.click(
      screen.getByRole("button", { name: "Dodaj kandydata" }),
    );
    expect(onAddCandidate).toHaveBeenCalledOnce();
  });

  it("nie pokazuje głównej akcji, gdy sekcja jest tylko do odczytu", () => {
    renderHeader({
      onAddCandidate: undefined,
      onEdit: undefined,
      onWriteAnnouncement: undefined,
      onGenerateInviteLink: undefined,
    });

    expect(
      screen.queryByRole("button", { name: "Dodaj kandydata" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Więcej akcji rekrutacji" }),
    ).toBeNull();
    // Przełącznik widoku i okna zostają także w trybie tylko-do-odczytu.
    expect(screen.getByRole("button", { name: /Tabela/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Zlecenie/ })).toBeTruthy();
  });

  it("przełącznik „Tabela | Tablica” zastąpił listwę dwunastu kroków", async () => {
    const { onViewChange } = renderHeader();

    const group = screen.getByRole("group", { name: "Widok rekrutacji" });
    const table = within(group).getByRole("button", { name: /Tabela/ });
    const board = within(group).getByRole("button", { name: "Tablica" });
    expect(within(group).getAllByRole("button")).toHaveLength(2);
    expect(table).toHaveAttribute("aria-pressed", "true");
    expect(board).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(board);
    expect(onViewChange).toHaveBeenCalledWith("board");

    // Dawne kroki nie są już nawigacją strony — żyją w pasku etapów tabeli.
    for (const name of ["Pipeline", "Screening", "CV do klienta", "Umowa", "Pozyskaj kandydatów"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("„Zlecenie”, „Historia i czat” i „Baza pytań” otwierają okna obok tabeli", async () => {
    const { onOpenOrder, onOpenHistoryChat, onOpenQuestions } = renderHeader();
    const nav = screen.getByRole("navigation", { name: "Sekcje rekrutacji" });

    await userEvent.click(within(nav).getByRole("button", { name: /Zlecenie/ }));
    expect(onOpenOrder).toHaveBeenCalledOnce();
    await userEvent.click(within(nav).getByRole("button", { name: /Historia i czat/ }));
    expect(onOpenHistoryChat).toHaveBeenCalledOnce();
    await userEvent.click(within(nav).getByRole("button", { name: "Baza pytań" }));
    expect(onOpenQuestions).toHaveBeenCalledOnce();
  });

  it("odznaka „brakuje N” tylko przy ZNANYCH brakach — niewiedza i zero milczą", () => {
    const { unmount } = renderHeader({ orderMissingCount: 2 });
    expect(screen.getByTestId("open-order")).toHaveTextContent("brakuje 2");
    unmount();

    const zero = renderHeader({ orderMissingCount: 0 });
    expect(screen.getByTestId("open-order")).not.toHaveTextContent("brakuje");
    zero.unmount();

    renderHeader({ orderMissingCount: null });
    expect(screen.getByTestId("open-order")).not.toHaveTextContent("brakuje");
  });

  it("licznik nieprzeczytanych czatu jest w nazwie przycisku i na odznace", () => {
    const { unmount } = renderHeader({ chatUnreadCount: 3 });
    const button = screen.getByRole("button", { name: "Historia i czat, 3 nieprzeczytane" });
    expect(button).toHaveTextContent("3");
    unmount();

    renderHeader({ chatUnreadCount: 0 });
    expect(screen.getByRole("button", { name: "Historia i czat" })).toBeTruthy();
  });

  it("licznik „w procesie” przy Tabeli tylko, gdy jest policzony — zero to wynik, nie brak danych", () => {
    const { unmount } = renderHeader();
    expect(screen.getByTestId("view-people")).toHaveTextContent(/^Tabela$/);
    unmount();

    const counted = renderHeader({ pipelineCount: 26 });
    expect(screen.getByTestId("view-people")).toHaveTextContent("Tabela26");
    counted.unmount();

    renderHeader({ pipelineCount: 0 });
    expect(screen.getByTestId("view-people")).toHaveTextContent("Tabela0");
  });

  it("pełny widok „Zlecenie i Champion”: żaden widok tabeli nie jest wciśnięty, „Zlecenie” jest bieżącą stroną", () => {
    renderHeader({ activeView: "champion" });
    expect(screen.getByTestId("view-people")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("view-board")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("open-order")).toHaveAttribute("aria-current", "page");
  });

  it("zamyka menu przed odroczonym otwarciem modala akcji", async () => {
    const { onEdit } = renderHeader();

    await userEvent.click(
      screen.getByRole("button", { name: "Więcej akcji rekrutacji" }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: "Edytuj" }));

    await waitFor(() => expect(onEdit).toHaveBeenCalledOnce());
    expect(screen.queryByRole("menuitem", { name: "Edytuj" })).toBeNull();
  });

  it("menu „…” niesie Edytuj, Szkic ogłoszenia i Wygeneruj link", async () => {
    renderHeader({ onWriteAnnouncement: vi.fn(), onGenerateInviteLink: vi.fn() });
    await userEvent.click(
      screen.getByRole("button", { name: "Więcej akcji rekrutacji" }),
    );
    for (const name of ["Edytuj", "Szkic ogłoszenia", "Wygeneruj link"]) {
      expect(await screen.findByRole("menuitem", { name })).toBeTruthy();
    }
  });

  it("narzędzia AI w menu „…” tylko gdy strona je poda (admin) — także bez innych akcji menu", async () => {
    const onOpenAiTools = vi.fn();
    const first = renderHeader({ onEdit: undefined, onOpenAiTools });
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Narzędzia AI (administrator)" }),
    );
    await waitFor(() => expect(onOpenAiTools).toHaveBeenCalledOnce());
    first.unmount();

    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await screen.findByRole("menuitem", { name: "Edytuj" });
    expect(screen.queryByRole("menuitem", { name: /Narzędzia AI/ })).toBeNull();
  });

  it("panel „Zespół i priorytet” istnieje tylko, gdy strona go poda (widok Championa)", async () => {
    // W „Tabeli" i na „Tablicy" panel żyje w oknie „Zlecenie".
    const { unmount } = renderHeader();
    expect(screen.queryByRole("button", { name: /Zespół i priorytet/ })).toBeNull();
    unmount();

    function Harness() {
      const [open, setOpen] = React.useState(false);
      return (
        <JobDetailCompactHeader
          title="Senior Java Developer"
          activeView="champion"
          onViewChange={vi.fn()}
          onOpenOrder={vi.fn()}
          onOpenHistoryChat={vi.fn()}
          onOpenQuestions={vi.fn()}
          contextOpen={open}
          onContextOpenChange={setOpen}
          contextContent={<div>Zespół operacyjny</div>}
        />
      );
    }

    render(<Harness />);
    expect(screen.queryByText("Zespół operacyjny")).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: /Zespół i priorytet/ }),
    );
    expect(await screen.findByText("Zespół operacyjny")).toBeTruthy();
  });
});

/**
 * Jobbar z makiety (k2–k8): klient w tytule, jedna linia faktów pod nim,
 * trzy liczby po prawej.
 */
describe("JobDetailCompactHeader — jobbar", () => {
  it("dokleja klienta do tytułu — bez niego nie wiadomo, czyja to rekrutacja", () => {
    renderHeader({ clientName: "PKO Bank Polski" });

    // `toHaveTextContent`, nie dopasowanie po nazwie dostępnej: implementacja
    // accname w testing-library przycina białe znaki NA GRANICY węzłów, więc
    // sprawdzałaby własny artefakt zamiast tego, co widzi użytkownik.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Senior Java Developer · PKO Bank Polski",
    );
  });

  it("bez klienta tytuł zostaje sam — żadnej kropki wiszącej w powietrzu", () => {
    renderHeader({ clientName: null });

    expect(
      screen.getByRole("heading", { name: "Senior Java Developer" }),
    ).toBeTruthy();
  });

  it("pokazuje trzy KPI kroku, a niepoliczoną liczbę rysuje jako „—”, nie zero", () => {
    renderHeader({
      kpis: [
        { key: "in-process", label: "w procesie", value: 15, tone: "neutral" },
        { key: "stalled", label: "utknęli > 7 d", value: 3, tone: "warn" },
        { key: "at-client", label: "u klienta", value: null, tone: "neutral" },
      ],
    });

    const cluster = screen.getByTestId("job-header-kpis");
    expect(within(cluster).getByText("15")).toBeTruthy();
    expect(within(cluster).getByText("utknęli > 7 d")).toBeTruthy();
    expect(within(cluster).getByText("3")).toBeTruthy();
    expect(within(cluster).getByText("—")).toBeTruthy();
    expect(within(cluster).queryByText("0")).toBeNull();
  });

  it("klaster pokazuje dokładnie te KPI, które dostał — policzone zero też", () => {
    const { unmount } = renderHeader({
      kpis: [
        { key: "screening", label: "w screeningu", value: 2, tone: "neutral" },
        {
          key: "pending",
          label: "czeka na akceptację",
          value: 1,
          tone: "warn",
        },
        { key: "verified", label: "zweryfikowani", value: 0, tone: "neutral" },
      ],
    });
    expect(screen.getByText("czeka na akceptację")).toBeTruthy();
    // Policzone zero JEST pokazywane — to wynik, nie brak danych.
    expect(
      within(screen.getByTestId("job-header-kpis")).getByText("0"),
    ).toBeTruthy();
    unmount();

    renderHeader({
      kpis: [
        { key: "in-process", label: "w procesie", value: 15, tone: "neutral" },
        { key: "stalled", label: "utknęli > 7 d", value: 0, tone: "neutral" },
        { key: "at-client", label: "u klienta", value: 0, tone: "neutral" },
      ],
    });
    expect(screen.queryByText("czeka na akceptację")).toBeNull();
    expect(screen.getByText("w procesie")).toBeTruthy();
  });

  it("bez KPI klaster w ogóle się nie renderuje", () => {
    renderHeader({ kpis: [] });
    expect(screen.queryByTestId("job-header-kpis")).toBeNull();
  });

  it("renderuje podtytuł jedną linią pod tytułem", () => {
    renderHeader({
      subtitle: "Warszawa / hybryda · deadline 30.09 · Marta K.",
    });
    expect(
      screen.getByText("Warszawa / hybryda · deadline 30.09 · Marta K."),
    ).toBeTruthy();
  });

  it("„Baza pytań” ma PEŁNĄ etykietę, nie samą ikonę", () => {
    // Regresja z produkcji: ucięta etykieta czyta się jak brak funkcji.
    renderHeader();
    const questions = screen.getByTestId("open-questions");
    expect(questions).toHaveTextContent("Baza pytań");
    expect(questions.className).not.toContain("sr-only");
  });

  it("pasek zawija się zamiast chować końcówkę za przewijaniem", () => {
    renderHeader();
    const nav = screen.getByRole("navigation", { name: "Sekcje rekrutacji" });
    expect(nav.className).toContain("flex-wrap");
    expect(nav.className).not.toContain("overflow-x-auto");
    expect(nav.parentElement?.className).toContain("flex-wrap");
  });
});
