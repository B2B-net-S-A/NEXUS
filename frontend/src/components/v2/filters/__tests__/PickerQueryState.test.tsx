import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

// Awaria zapytania nie może renderować się jako „Brak klientów.” — pickery
// filtrów listy kandydatów pokazują ładowanie i błąd z „Ponów”.

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    default: { get: vi.fn() },
    competenceCategoriesApi: { list: vi.fn() },
  };
});

import api, { competenceCategoriesApi } from "@/lib/api";
import { UserMultiSelect } from "@/components/v2/filters/UserMultiSelect";
import { ClientMultiSelect } from "@/components/v2/filters/ClientMultiSelect";
import { CompetenceCategoryMultiSelect } from "@/components/v2/filters/CompetenceCategoryMultiSelect";
import { RecruitmentMultiSelect } from "@/components/v2/filters/RecruitmentMultiSelect";
import { AddedByMultiSelect } from "@/components/v2/filters/AddedByMultiSelect";
import { TalentPoolMultiSelect } from "@/components/v2/filters/TalentPoolMultiSelect";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const get = vi.mocked(api.get);
const listCategories = vi.mocked(competenceCategoriesApi.list);

beforeEach(() => {
  get.mockReset();
  listCategories.mockReset();
});

describe("ClientMultiSelect", () => {
  it("shows an error with retry instead of „Brak klientów” when the lookup fails", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("500"));
    renderWithQuery(<ClientMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Dowolny klient/i }));

    expect(await screen.findByText("Nie udało się pobrać listy klientów.")).toBeInTheDocument();
    expect(screen.queryByText("Brak klientów.")).not.toBeInTheDocument();

    get.mockResolvedValueOnce({ data: [{ id: 7, name: "Bank Testowy" }] });
    await user.click(screen.getByRole("button", { name: /Ponów/i }));
    expect(await screen.findByText("Bank Testowy")).toBeInTheDocument();
  });

  it("shows loading, not the empty message, while the lookup is pending", async () => {
    const user = userEvent.setup();
    get.mockReturnValueOnce(new Promise(() => {}));
    renderWithQuery(<ClientMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Dowolny klient/i }));

    expect(await screen.findByText("Ładowanie klientów…")).toBeInTheDocument();
    expect(screen.queryByText("Brak klientów.")).not.toBeInTheDocument();
  });

  it("still says „Brak klientów” for a real empty result", async () => {
    const user = userEvent.setup();
    get.mockResolvedValueOnce({ data: [] });
    renderWithQuery(<ClientMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Dowolny klient/i }));
    expect(await screen.findByText("Brak klientów.")).toBeInTheDocument();
  });
});

describe("UserMultiSelect", () => {
  it("shows an error with retry instead of „Brak użytkowników”", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("503"));
    renderWithQuery(<UserMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Dowolny rekruter/i }));

    expect(await screen.findByText("Nie udało się pobrać listy osób.")).toBeInTheDocument();
    expect(screen.queryByText("Brak użytkowników.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ponów/i })).toBeInTheDocument();
  });
});

describe("CompetenceCategoryMultiSelect", () => {
  it("shows an error with retry instead of „Brak opcji”", async () => {
    const user = userEvent.setup();
    listCategories.mockRejectedValueOnce(new Error("500"));
    renderWithQuery(<CompetenceCategoryMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Kategoria: dowolna/i }));

    expect(await screen.findByText("Nie udało się pobrać kategorii.")).toBeInTheDocument();
    expect(screen.queryByText("Brak opcji.")).not.toBeInTheDocument();

    listCategories.mockResolvedValueOnce([
      {
        id: 1,
        slug: "infrastructure_operations",
        name_pl: "Infra & Operations",
        name_en: "Infra",
        description: "",
        keywords: [],
        display_order: 1,
      },
    ] as never);
    await user.click(screen.getByRole("button", { name: /Ponów/i }));
    await waitFor(() =>
      expect(screen.getByText("Infra & Operations")).toBeInTheDocument(),
    );
  });
});

describe("RecruitmentMultiSelect", () => {
  it("shows an error with retry instead of „Brak rekrutacji”", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("500"));
    renderWithQuery(<RecruitmentMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Dowolna rekrutacja/i }));

    expect(
      await screen.findByText("Nie udało się pobrać listy rekrutacji."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak rekrutacji.")).not.toBeInTheDocument();

    get.mockResolvedValueOnce({ data: [{ id: 3, title: "Java Developer" }] });
    await user.click(screen.getByRole("button", { name: /Ponów/i }));
    expect(await screen.findByText("Java Developer")).toBeInTheDocument();
  });

  it("shows loading, not the empty message, while the lookup is pending", async () => {
    const user = userEvent.setup();
    get.mockReturnValueOnce(new Promise(() => {}));
    renderWithQuery(<RecruitmentMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Dowolna rekrutacja/i }));

    expect(await screen.findByText("Ładowanie rekrutacji…")).toBeInTheDocument();
    expect(screen.queryByText("Brak rekrutacji.")).not.toBeInTheDocument();
  });

  it("still says „Brak rekrutacji” for a real empty result", async () => {
    const user = userEvent.setup();
    get.mockResolvedValueOnce({ data: [] });
    renderWithQuery(<RecruitmentMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Dowolna rekrutacja/i }));
    expect(await screen.findByText("Brak rekrutacji.")).toBeInTheDocument();
  });
});

describe("AddedByMultiSelect", () => {
  it("shows an error with retry instead of „Brak użytkowników”", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("503"));
    // Bez pozycji „Import systemowy” — przy niej cmdk nie pokazuje pustego
    // stanu nawet przy pustym katalogu, więc test niczego by nie dowodził.
    renderWithQuery(
      <AddedByMultiSelect value={[]} onChange={vi.fn()} includeSystem={false} />,
    );
    await user.click(screen.getByRole("button", { name: /Wszyscy dodający/i }));

    expect(await screen.findByText("Nie udało się pobrać listy osób.")).toBeInTheDocument();
    expect(screen.queryByText("Brak użytkowników.")).not.toBeInTheDocument();

    get.mockResolvedValueOnce({ data: [{ id: 5, name: "Marta Nowak", role: "recruiter" }] });
    await user.click(screen.getByRole("button", { name: /Ponów/i }));
    expect(await screen.findByText("Marta Nowak")).toBeInTheDocument();
  });

  it("shows the error even when the system-import entry is listed", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("503"));
    renderWithQuery(<AddedByMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Wszyscy dodający/i }));

    expect(await screen.findByText("Nie udało się pobrać listy osób.")).toBeInTheDocument();
    expect(screen.getByText("Import systemowy")).toBeInTheDocument();
  });

  it("still says „Brak użytkowników” for a real empty result", async () => {
    const user = userEvent.setup();
    get.mockResolvedValueOnce({ data: [] });
    renderWithQuery(
      <AddedByMultiSelect value={[]} onChange={vi.fn()} includeSystem={false} />,
    );
    await user.click(screen.getByRole("button", { name: /Wszyscy dodający/i }));
    expect(await screen.findByText("Brak użytkowników.")).toBeInTheDocument();
  });
});

describe("TalentPoolMultiSelect", () => {
  it("shows an error with retry instead of „Brak pul”", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("500"));
    renderWithQuery(<TalentPoolMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Wszystkie pule/i }));

    expect(await screen.findByText("Nie udało się pobrać listy pul.")).toBeInTheDocument();
    expect(screen.queryByText("Brak pul.")).not.toBeInTheDocument();

    get.mockResolvedValueOnce({ data: [{ id: 9, name: "Java Senior", candidate_count: 3 }] });
    await user.click(screen.getByRole("button", { name: /Ponów/i }));
    expect(await screen.findByText("Java Senior")).toBeInTheDocument();
  });

  it("shows loading, not the empty message, while the lookup is pending", async () => {
    const user = userEvent.setup();
    get.mockReturnValueOnce(new Promise(() => {}));
    renderWithQuery(<TalentPoolMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Wszystkie pule/i }));

    expect(await screen.findByText("Ładowanie pul…")).toBeInTheDocument();
    expect(screen.queryByText("Brak pul.")).not.toBeInTheDocument();
  });

  it("still says „Brak pul” for a real empty result", async () => {
    const user = userEvent.setup();
    get.mockResolvedValueOnce({ data: [] });
    renderWithQuery(<TalentPoolMultiSelect value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /Wszystkie pule/i }));
    expect(await screen.findByText("Brak pul.")).toBeInTheDocument();
  });
});
