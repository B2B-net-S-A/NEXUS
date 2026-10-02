/**
 * Wiersz „Kategoria” panelu zespołu (decyzja Artura 02.10.2026).
 *
 * Osoby z kategorii kompetencji widzą rekrutację w „Moja kategoria”, ale nad
 * nią NIE pracują — do tej zmiany stały w panelu jako „współpracownicy”.
 * Lista jest zwinięta i wczytuje się dopiero po rozwinięciu.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobCategoryRow } from "@/components/v2/jobs/JobCategoryRow";

const getMock = vi.fn();
const categoriesListMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => getMock(...args) },
  competenceCategoriesApi: {
    list: (...args: unknown[]) => categoriesListMock(...args),
  },
}));

const CATEGORIES = [
  {
    id: 2,
    slug: "software_development",
    name_pl: "Development",
    name_en: "Development",
    description: "",
    keywords: [],
    display_order: 2,
  },
];

const PEOPLE = [
  { user_id: 33, name: "Celina Wzorcowa", email: "c@example.com", role: "sourcer", is_primary: false, priority: 2 },
  { user_id: 34, name: "Darek Makietowy", email: "d@example.com", role: "recruiter", is_primary: false, priority: null },
  { user_id: 32, name: "Bartek Testowy", email: "b@example.com", role: "recruiter", is_primary: true, priority: 1 },
  { user_id: 31, name: "Anna Przykładowa", email: "a@example.com", role: "recruiter", is_primary: true, priority: 1 },
];

function renderRow(categoryId: number | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <JobCategoryRow categoryId={categoryId} />
    </QueryClientProvider>,
  );
}

const SENTENCE =
  "Te osoby widzą rekrutację w „Moja kategoria”, ale nie pracują nad nią, dopóki ktoś ich nie przydzieli.";

beforeEach(() => {
  getMock.mockReset();
  categoriesListMock.mockReset();
  categoriesListMock.mockResolvedValue(CATEGORIES);
  getMock.mockResolvedValue({ data: PEOPLE });
});

describe("JobCategoryRow", () => {
  it("pokazuje kategorię i zwinięty przycisk — listy osób nie pobiera, dopóki nikt jej nie rozwinie", async () => {
    renderRow(2);

    expect(await screen.findByText("Development")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Osoby z kategorii" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(SENTENCE)).toBeInTheDocument();
    expect(getMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("list", { name: "Osoby z kategorii" })).not.toBeInTheDocument();
  });

  it("po rozwinięciu wczytuje osoby: 1. priorytet przed 2., bez priorytetu na końcu", async () => {
    const user = userEvent.setup();
    renderRow(2);

    await user.click(screen.getByRole("button", { name: "Osoby z kategorii" }));

    const list = await screen.findByRole("list", { name: "Osoby z kategorii" });
    expect(getMock).toHaveBeenCalledWith("/api/competence-categories/2/recruiters");
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Anna Przykładowa1. priorytet",
      "Bartek Testowy1. priorytet",
      "Celina Wzorcowa2. priorytet",
      "Darek Makietowy",
    ]);
    // Po wczytaniu przycisk mówi, ile osób jest w kategorii.
    const toggle = screen.getByRole("button", { name: "4 osoby z kategorii" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.click(toggle);
    expect(screen.queryByRole("list", { name: "Osoby z kategorii" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "4 osoby z kategorii" }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("awaria listy to błąd z „Ponów”, nie „pusta kategoria”", async () => {
    getMock.mockRejectedValueOnce({ response: { status: 500, data: {} } });
    const user = userEvent.setup();
    renderRow(2);

    await user.click(screen.getByRole("button", { name: "Osoby z kategorii" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać osób z kategorii.");
    expect(screen.queryByText("Nikt nie ma dziś tej kategorii.")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: "Ponów" }));

    expect(await screen.findByRole("list", { name: "Osoby z kategorii" })).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledTimes(2);
  });

  it("w trakcie wczytywania mówi, że ładuje — nie że nikogo nie ma", async () => {
    let release: () => void = () => undefined;
    getMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () => resolve({ data: [] });
        }),
    );
    const user = userEvent.setup();
    renderRow(2);

    await user.click(screen.getByRole("button", { name: "Osoby z kategorii" }));

    expect(screen.getByRole("status")).toHaveTextContent("Ładowanie osób z kategorii…");
    expect(screen.queryByText("Nikt nie ma dziś tej kategorii.")).not.toBeInTheDocument();

    release();
    // Pusta kategoria to osobny, prawdziwy stan — dopiero po udanym odczycie.
    expect(await screen.findByText("Nikt nie ma dziś tej kategorii.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "0 osób z kategorii" })).toBeInTheDocument();
  });

  it("rekrutacja bez kategorii mówi to wprost i nie pyta o osoby", () => {
    renderRow(null);

    expect(
      screen.getByText(
        "Rekrutacja nie ma kategorii, więc nikt nie zobaczy jej w „Moja kategoria”.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(SENTENCE)).not.toBeInTheDocument();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("kategoria spoza aktywnej listy nie zostawia pustego miejsca", async () => {
    renderRow(9);

    expect(await screen.findByText("Kategoria spoza aktywnej listy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Osoby z kategorii" })).toBeInTheDocument();
  });

  it("awaria katalogu kategorii mówi, że nie udało się pobrać nazwy", async () => {
    categoriesListMock.mockRejectedValue({ response: { status: 500, data: {} } });
    renderRow(2);

    expect(
      await screen.findByText("Nie udało się pobrać nazwy kategorii"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Kategoria spoza aktywnej listy")).not.toBeInTheDocument();
  });
});
