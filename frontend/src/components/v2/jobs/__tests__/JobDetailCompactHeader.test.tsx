import * as React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    // Numer u klienta przed tytułem (15.10.2026), nie w linii dla czytnika.
    expect(screen.getByTestId("header-client-reference")).toHaveAccessibleName(
      "Numer u klienta CABP/001/2026 — kopiuj",
    );
    expect(screen.getByTestId("header-client-line")).toHaveTextContent("nasz nr REF-505734");
    expect(screen.getByTestId("header-client-line")).not.toHaveTextContent("CABP/001/2026");
  });

  it("numer u klienta przed tytułem, także po „Zwiń”; klik kopiuje cały numer (15.10.2026)", async () => {
    const onCopyClientReference = vi.fn();
    const props = {
      priority: <span data-testid="slot-priority">P1</span>,
      clientReference: "41228, 41227",
      onCopyClientReference,
    };
    for (const collapsed of [false, true]) {
      const { unmount } = renderHeader({ ...props, collapsed, onToggleCollapsed: vi.fn() });
      const title = screen.getByTestId("job-header-title");
      const chip = screen.getByTestId("header-client-reference");
      expect(chip).toHaveTextContent("41228+1");
      expect(title.parentElement).toContainElement(chip);
      expect(
        screen.getByTestId("slot-priority").compareDocumentPosition(chip) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(chip.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      await userEvent.click(chip);
      unmount();
    }
    expect(onCopyClientReference).toHaveBeenCalledTimes(2);
    expect(onCopyClientReference).toHaveBeenCalledWith("41228, 41227");
  });

  it("bez numeru u klienta nie ma znacznika", () => {
    renderHeader();
    expect(screen.queryByTestId("header-client-reference")).toBeNull();
  });

  it("laptop 1280 px: tytuł w jednej linii, status obok; nazwa od klienta w dymku tytułu (K-D3)", () => {
    renderHeader({ clientTitle: "Analityk Biznesowo-Systemowy KYC/AML", clientReference: "CABP/001/2026" });
    const title = screen.getByTestId("job-header-title");
    expect(title.className).toMatch(/(^| )truncate( |$)/);
    expect(title.className).not.toMatch(/line-clamp/);
    expect(title).toHaveAttribute(
      "title",
      "Analityk KYC/AML\nU klienta: „Analityk Biznesowo-Systemowy KYC/AML” · nr u klienta CABP/001/2026 · nasz nr REF-505734",
    );
    // Status w tym samym wierszu co tytuł (wspólny rodzic, bez zawijania).
    expect(title.parentElement).toContainElement(screen.getByText("Szukamy"));
    expect(title.parentElement?.className).not.toMatch(/flex-wrap/);
    // Linia pod tytułem nie zajmuje miejsca — zostaje dla czytnika ekranu.
    expect(screen.getByTestId("header-client-line")).toHaveClass("sr-only");
  });

  it("bez nazwy od klienta i numerów dymek tytułu to sam tytuł", () => {
    renderHeader({ referenceNumber: null });
    expect(screen.getByTestId("job-header-title")).toHaveAttribute("title", "Analityk KYC/AML");
  });

  it("fakty z ikoną zamiast etykiety (K-D2): etykieta w dymku i dla czytnika ekranu", () => {
    renderHeader();
    const fact = screen.getByTestId("job-header-fact-client");
    expect(fact.querySelector("svg")).not.toBeNull();
    expect(within(fact).getByText("Klient")).toHaveClass("sr-only");
    expect(fact).toHaveAttribute("title", "Klient: Bank Przykładowy S.A.");
    // Pierwsza ustępuje nazwa klienta, budżet nigdy.
    expect(fact.className).toMatch(/max-w-60/);
    expect(screen.getByTestId("job-header-fact-budget").className).toMatch(/shrink-0/);
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
    renderHeader({ onOpenChampions: vi.fn(), onAddByName: vi.fn() });
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

  it("zakładki z adresem to linki: środkowy przycisk i Ctrl/Cmd otwierają nową kartę", () => {
    const { onViewChange } = renderHeader({
      viewHref: (view) => (view === "board" ? "/jobs/7" : `/jobs/7?tab=${view}`),
    });
    const champion = screen.getByTestId("open-champion-profile");
    expect(champion.tagName).toBe("A");
    expect(champion).toHaveAttribute("href", "/jobs/7?tab=champion");
    expect(screen.getByTestId("view-board")).toHaveAttribute("href", "/jobs/7");

    // Ctrl/Cmd+klik i środkowy przycisk: przeglądarka otwiera kartę, widok tu się nie zmienia.
    expect(fireEvent.click(champion, { button: 0, ctrlKey: true })).toBe(true);
    expect(fireEvent.click(champion, { button: 0, metaKey: true })).toBe(true);
    expect(fireEvent.click(champion, { button: 1 })).toBe(true);
    expect(onViewChange).not.toHaveBeenCalled();

    // Zwykły klik: przełącza widok w miejscu, bez przeładowania strony.
    expect(fireEvent.click(champion, { button: 0 })).toBe(false);
    expect(onViewChange).toHaveBeenCalledWith("champion");
  });

  it("odznaka „brakuje N” przy „Profil Championa” tylko dla liczby większej od zera", () => {
    const first = renderHeader({ orderMissingCount: 2 });
    expect(screen.getByTestId("open-champion-profile")).toHaveTextContent("brakuje 2");
    first.unmount();

    renderHeader({ orderMissingCount: 0 });
    expect(screen.getByTestId("open-champion-profile")).not.toHaveTextContent("brakuje");
  });

  it("„Historia i czat” to ikona z licznikiem (K-D4); nazwa i liczba dla czytnika ekranu", async () => {
    const { onOpenHistoryChat } = renderHeader({ chatUnreadCount: 120 });
    const button = screen.getByRole("button", {
      name: "Historia i czat, ponad 99 nieprzeczytane",
    });
    expect(button).toHaveTextContent(/^99\+$/);
    expect(button).toHaveAttribute("title", "Historia i czat");
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

  it("menu „⋯”: „Pliki” z liczbą otwiera okno plików rekrutacji", async () => {
    const onOpenFiles = vi.fn();
    const first = renderHeader({ onOpenFiles, filesCount: 3 });
    const item = within(await openMenu()).getByTestId("menu-files");
    expect(item).toHaveTextContent("Pliki (3)");
    await userEvent.click(item);
    await waitFor(() => expect(onOpenFiles).toHaveBeenCalled());
    first.unmount();

    // Liczba nieznana albo zero: sama nazwa, bez „(0)”.
    renderHeader({ onOpenFiles, filesCount: 0 });
    expect(within(await openMenu()).getByTestId("menu-files")).toHaveTextContent(/^Pliki$/);
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

  it("menu „⋯”: „Championi…” otwiera okienko championów tylko roli z prawem (D2)", async () => {
    const onOpenChampions = vi.fn();
    const first = renderHeader({ onOpenChampions });
    const menu = await openMenu();
    const item = within(menu).getByTestId("toggle-champion");
    expect(item).toHaveTextContent("Championi…");
    await userEvent.click(item);
    await waitFor(() => expect(onOpenChampions).toHaveBeenCalled());
    first.unmount();

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

describe("JobDetailCompactHeader — priorytet, rekruter, źródła i „Zwiń” (K-D1–K-D5, 14.10.2026)", () => {
  it("priorytet stoi przed tytułem, „Rekruter” w linii faktów", () => {
    renderHeader({
      priority: <span data-testid="slot-priority">P1</span>,
      recruiter: <button type="button">Rekruter: Marta N.</button>,
    });
    const title = screen.getByTestId("job-header-title");
    const priority = screen.getByTestId("slot-priority");
    expect(title.parentElement).toContainElement(priority);
    expect(
      priority.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const facts = screen.getByTestId("job-header-facts");
    const recruiter = screen.getByRole("button", { name: "Rekruter: Marta N." });
    expect(facts.parentElement).toContainElement(recruiter);
    expect(facts).not.toContainElement(recruiter);
  });

  it("źródła kandydatów i „Kto dodał” w trzeciej linii nagłówka (K-D1)", () => {
    renderHeader({
      sources: <section aria-label="Kandydaci do dodania" />,
      sourcesTrailing: <button type="button">Kto dodał: wszyscy</button>,
    });
    const row = screen.getByTestId("job-header-sources-row");
    expect(row).toContainElement(screen.getByRole("region", { name: "Kandydaci do dodania" }));
    expect(row).toContainElement(screen.getByRole("button", { name: "Kto dodał: wszyscy" }));
    expect(screen.getByTestId("job-header-facts")).not.toContainElement(row);
  });

  it("bez źródeł (np. „Profil Championa”) trzeciej linii nie ma", () => {
    renderHeader();
    expect(screen.queryByTestId("job-header-sources-row")).toBeNull();
  });

  it("„Zwiń” zostawia linię tytułu z awatarami i włączonym filtrem (K-D5)", async () => {
    const onToggleCollapsed = vi.fn();
    const slots = {
      recruiter: <span data-testid="slot-recruiter" />,
      recruiterCompact: <span data-testid="slot-recruiter-compact" />,
      sources: <section aria-label="Kandydaci do dodania" />,
      collapsedExtras: <span data-testid="slot-filter" />,
      onToggleCollapsed,
    };
    const open = renderHeader(slots);
    const toggle = screen.getByTestId("job-header-collapse");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAccessibleName("Zwiń nagłówek do jednej linii");
    expect(screen.getByTestId("slot-recruiter")).toBeTruthy();
    expect(screen.queryByTestId("slot-recruiter-compact")).toBeNull();
    expect(screen.queryByTestId("slot-filter")).toBeNull();
    await userEvent.click(toggle);
    expect(onToggleCollapsed).toHaveBeenCalled();
    open.unmount();

    renderHeader({ ...slots, collapsed: true });
    expect(screen.getByTestId("job-header-collapse")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("job-header-collapse")).toHaveAccessibleName("Rozwiń nagłówek");
    expect(screen.queryByTestId("job-header-facts")).toBeNull();
    expect(screen.queryByTestId("job-header-sources-row")).toBeNull();
    expect(screen.queryByTestId("slot-recruiter")).toBeNull();
    const title = screen.getByTestId("job-header-title");
    expect(title.parentElement).toContainElement(screen.getByTestId("slot-recruiter-compact"));
    expect(title.parentElement).toContainElement(screen.getByTestId("slot-filter"));
  });

  it("bez obsługi zwijania nie ma przycisku „Zwiń”", () => {
    renderHeader();
    expect(screen.queryByTestId("job-header-collapse")).toBeNull();
  });
});
