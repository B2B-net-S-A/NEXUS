import * as React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JobDetailCompactHeader } from "@/components/v2/jobs/JobDetailCompactHeader";
import type { JobDetailView } from "@/lib/job-detail-routing";
import type { JobHeaderFact } from "@/lib/job-header-facts";

const FACTS: JobHeaderFact[] = [
  { key: "client", label: "Klient", value: "Bank Przykładowy S.A." },
  { key: "budget", label: "Budżet", value: "do 93,00 PLN/h" },
  { key: "work_mode", label: "Tryb pracy", value: "Zdalnie" },
];

function renderHeader(
  overrides: Partial<React.ComponentProps<typeof JobDetailCompactHeader>> = {},
) {
  const onViewChange = vi.fn<(view: JobDetailView) => void>();
  const onOpenOrder = vi.fn();
  const onOpenHistoryChat = vi.fn();
  const onOpenQuestions = vi.fn();

  const { unmount } = render(
    <JobDetailCompactHeader
      title="Analityk KYC/AML"
      referenceNumber="REF-505734"
      badges={<span>Szukamy</span>}
      facts={FACTS}
      activeView="board"
      onViewChange={onViewChange}
      onOpenOrder={onOpenOrder}
      onOpenHistoryChat={onOpenHistoryChat}
      onOpenQuestions={onOpenQuestions}
      chatUnreadCount={3}
      {...overrides}
    />,
  );

  return { onViewChange, onOpenOrder, onOpenHistoryChat, onOpenQuestions, unmount };
}

async function openMenu() {
  await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
  return screen.findByRole("menu");
}

describe("JobDetailCompactHeader", () => {
  it("na górze: tytuł stanowiska, status i linia z nazwą od klienta", () => {
    renderHeader({
      clientTitle: "Analityk Biznesowo-Systemowy KYC/AML",
      clientReference: "CABP/001/2026",
    });

    expect(screen.getByRole("heading", { level: 1, name: "Analityk KYC/AML" })).toBeTruthy();
    expect(screen.getByText("Szukamy")).toBeTruthy();
    expect(screen.getByTestId("header-client-title")).toHaveTextContent(
      "U klienta: „Analityk Biznesowo-Systemowy KYC/AML”",
    );
    expect(screen.getByTestId("header-client-reference")).toHaveTextContent(
      "nr u klienta CABP/001/2026",
    );
    expect(screen.getByTestId("header-client-line")).toHaveTextContent("nasz nr REF-505734");
  });

  it("bez nazwy od klienta i numerów linii pod tytułem nie ma", () => {
    renderHeader({ referenceNumber: null });
    expect(screen.queryByTestId("header-client-line")).toBeNull();
  });

  it("trzy wyróżnione fakty: klient, budżet, tryb pracy", () => {
    renderHeader();
    const facts = screen.getByTestId("job-header-facts");
    expect(within(facts).getByText("Klient")).toBeTruthy();
    expect(within(facts).getByText("Bank Przykładowy S.A.")).toBeTruthy();
    expect(within(facts).getByText("Budżet")).toBeTruthy();
    expect(within(facts).getByText("do 93,00 PLN/h")).toBeTruthy();
    expect(within(facts).getByText("Tryb pracy")).toBeTruthy();
    expect(within(facts).getByText("Zdalnie")).toBeTruthy();
  });

  it("brak wartości faktu to „nie podano”, nie pustka", () => {
    renderHeader({
      facts: [
        { key: "client", label: "Klient", value: "Bank Przykładowy S.A." },
        { key: "budget", label: "Budżet", value: null },
        { key: "work_mode", label: "Tryb pracy", value: null },
      ],
    });
    expect(
      within(screen.getByTestId("job-header-fact-budget")).getByText("nie podano"),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("job-header-fact-work_mode")).getByText("nie podano"),
    ).toBeTruthy();
  });

  it("nie ma liczników, ścieżki ani przycisków, które zeszły do menu i na kafle", () => {
    renderHeader({ onToggleChampion: vi.fn(), onAddByName: vi.fn() });
    expect(screen.queryByTestId("job-header-kpis")).toBeNull();
    expect(screen.queryByTestId("job-recruitment-path")).toBeNull();
    expect(screen.queryByText(/Najbliższy krok/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Dodaj kandydatów" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Podobne rekrutacje/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /mamy championa/i })).toBeNull();
  });

  it("zakładki przełączają widok; bieżący ma aria-current", async () => {
    const { onViewChange } = renderHeader();
    const nav = screen.getByRole("navigation", { name: "Widok rekrutacji" });
    expect(within(nav).getByTestId("view-board")).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByTestId("open-champion-profile")).not.toHaveAttribute("aria-current");

    await userEvent.click(within(nav).getByTestId("open-champion-profile"));
    expect(onViewChange).toHaveBeenCalledWith("champion");
  });

  it("odznaka „brakuje N” przy „Zlecenie i Champion” tylko dla liczby większej od zera", () => {
    const first = renderHeader({ orderMissingCount: 2 });
    expect(screen.getByTestId("open-champion-profile")).toHaveTextContent("brakuje 2");
    first.unmount();

    renderHeader({ orderMissingCount: 0 });
    expect(screen.getByTestId("open-champion-profile")).not.toHaveTextContent("brakuje");
  });

  it("„Historia i czat” mówi o nieprzeczytanych także czytnikowi ekranu", async () => {
    const { onOpenHistoryChat } = renderHeader({ chatUnreadCount: 120 });
    const button = screen.getByRole("button", {
      name: "Historia i czat, ponad 99 nieprzeczytane",
    });
    expect(button).toHaveTextContent("99+");
    await userEvent.click(button);
    expect(onOpenHistoryChat).toHaveBeenCalled();
  });

  it("menu „⋯”: skrót zlecenia i baza pytań są zawsze", async () => {
    const { onOpenOrder, onOpenQuestions } = renderHeader();
    const menu = await openMenu();
    await userEvent.click(within(menu).getByTestId("open-order"));
    await waitFor(() => expect(onOpenOrder).toHaveBeenCalled());

    const again = await openMenu();
    await userEvent.click(within(again).getByTestId("open-questions"));
    await waitFor(() => expect(onOpenQuestions).toHaveBeenCalled());
  });

  it("menu „⋯”: „Zespół” mówi, kto jest rekruterem, i otwiera panel zespołu", async () => {
    const onOpenTeam = vi.fn();
    const first = renderHeader({ onOpenTeam, teamSummary: "Rekruter: Marta N. +1" });
    const item = within(await openMenu()).getByTestId("menu-team");
    expect(item).toHaveTextContent("Zespół");
    expect(item).toHaveTextContent("Rekruter: Marta N. +1");
    await userEvent.click(item);
    await waitFor(() => expect(onOpenTeam).toHaveBeenCalled());
    first.unmount();

    renderHeader();
    expect(within(await openMenu()).queryByTestId("menu-team")).toBeNull();
  });

  it("menu „⋯”: „Mamy championa” tylko dla roli z prawem i z etykietą stanu", async () => {
    const onToggleChampion = vi.fn();
    const first = renderHeader({ onToggleChampion, championFound: false });
    const menu = await openMenu();
    const item = within(menu).getByTestId("toggle-champion");
    expect(item).toHaveTextContent("Oznacz: mamy championa");
    await userEvent.click(item);
    await waitFor(() => expect(onToggleChampion).toHaveBeenCalled());
    first.unmount();

    const second = renderHeader({ onToggleChampion, championFound: true });
    expect(within(await openMenu()).getByTestId("toggle-champion")).toHaveTextContent(
      "Cofnij „Mamy championa”",
    );
    second.unmount();

    renderHeader();
    expect(within(await openMenu()).queryByTestId("toggle-champion")).toBeNull();
  });

  it("menu „⋯”: dodanie po nazwisku, z pliku CV i przegląd całej bazy przez AI", async () => {
    const onAddByName = vi.fn();
    const onAddFromCv = vi.fn();
    const onStartFullReview = vi.fn();
    const onOpenMyPeople = vi.fn();
    renderHeader({ onAddByName, onAddFromCv, onStartFullReview, onOpenMyPeople });

    await userEvent.click(within(await openMenu()).getByTestId("menu-add-by-name"));
    await waitFor(() => expect(onAddByName).toHaveBeenCalled());
    await userEvent.click(within(await openMenu()).getByTestId("menu-add-from-cv"));
    await waitFor(() => expect(onAddFromCv).toHaveBeenCalled());
    const review = within(await openMenu()).getByTestId("menu-full-review");
    expect(review).toHaveTextContent("Przeszukaj całą bazę (AI)");
    await userEvent.click(review);
    await waitFor(() => expect(onStartFullReview).toHaveBeenCalled());
    const mine = within(await openMenu()).getByTestId("menu-my-people");
    expect(mine).toHaveTextContent("Moi ludzie do tej rekrutacji");
    await userEvent.click(mine);
    await waitFor(() => expect(onOpenMyPeople).toHaveBeenCalled());
  });

  it("bez prawa dodawania menu nie ma sekcji „Kandydaci”", async () => {
    renderHeader();
    const menu = await openMenu();
    expect(within(menu).queryByText("Kandydaci")).toBeNull();
    expect(within(menu).queryByTestId("menu-full-review")).toBeNull();
    expect(within(menu).queryByTestId("menu-my-people")).toBeNull();
  });

  it("menu „⋯”: puste kolumny Tablicy — etykieta mówi, co zrobi kliknięcie", async () => {
    const onToggleEmptyColumns = vi.fn();
    const first = renderHeader({ onToggleEmptyColumns, emptyColumnsHidden: true });
    const item = within(await openMenu()).getByTestId("toggle-empty-columns");
    expect(item).toHaveTextContent("Pokaż puste kolumny");
    await userEvent.click(item);
    await waitFor(() => expect(onToggleEmptyColumns).toHaveBeenCalled());
    first.unmount();

    renderHeader({ onToggleEmptyColumns, emptyColumnsHidden: false });
    expect(within(await openMenu()).getByTestId("toggle-empty-columns")).toHaveTextContent(
      "Ukryj puste kolumny",
    );
  });

  it("menu „⋯”: pozycje zależne od uprawnień pojawiają się tylko z funkcją", async () => {
    const onEdit = vi.fn();
    const onCloseJob = vi.fn();
    const onCopyLink = vi.fn();
    const onOpenAiTools = vi.fn();
    const first = renderHeader({
      onEdit,
      onCloseJob,
      onCopyLink,
      onOpenAiTools,
      clientCardHref: "/help?tab=clients&client=7",
    });
    const menu = await openMenu();
    expect(within(menu).getByRole("menuitem", { name: "Edytuj" })).toBeTruthy();
    expect(within(menu).getByTestId("open-client-card")).toHaveAttribute(
      "href",
      "/help?tab=clients&client=7",
    );
    expect(within(menu).getByTestId("copy-job-link")).toBeTruthy();
    expect(within(menu).getByTestId("open-ai-tools")).toBeTruthy();
    await userEvent.click(within(menu).getByTestId("close-job"));
    await waitFor(() => expect(onCloseJob).toHaveBeenCalled());
    first.unmount();

    renderHeader();
    const bare = await openMenu();
    expect(within(bare).queryByRole("menuitem", { name: "Edytuj" })).toBeNull();
    expect(within(bare).queryByTestId("close-job")).toBeNull();
    expect(within(bare).queryByTestId("open-ai-tools")).toBeNull();
    expect(within(bare).queryByTestId("toggle-empty-columns")).toBeNull();
  });

  it("z listy „Do przejrzenia” zakładka „Tablica” jest powrotem", async () => {
    const { onViewChange } = renderHeader({ activeView: "people" });
    const board = screen.getByTestId("view-board");
    expect(board).not.toHaveAttribute("aria-current");
    await userEvent.click(board);
    expect(onViewChange).toHaveBeenCalledWith("board");
  });
  it("menu „⋯”: „Otwórz ponownie…” dla zamkniętej, „Dokończ i opublikuj…” dla szkicu (04.10.2026)", async () => {
    const onReopenJob = vi.fn();
    const closed = renderHeader({ onReopenJob });
    const menu = await openMenu();
    expect(within(menu).getByTestId("reopen-job")).toHaveTextContent("Otwórz ponownie…");
    expect(within(menu).queryByTestId("finish-job")).toBeNull();
    await userEvent.click(within(menu).getByTestId("reopen-job"));
    await waitFor(() => expect(onReopenJob).toHaveBeenCalled());
    closed.unmount();

    const onFinishJob = vi.fn();
    const draft = renderHeader({ onFinishJob });
    const draftMenu = await openMenu();
    expect(within(draftMenu).queryByTestId("reopen-job")).toBeNull();
    await userEvent.click(within(draftMenu).getByTestId("finish-job"));
    await waitFor(() => expect(onFinishJob).toHaveBeenCalled());
    draft.unmount();

    renderHeader();
    const bare = await openMenu();
    expect(within(bare).queryByTestId("reopen-job")).toBeNull();
    expect(within(bare).queryByTestId("finish-job")).toBeNull();
  });
});
