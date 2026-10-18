import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { reorderedSortOrders, type TimesheetTemplate } from "@/lib/api/hr-time";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  confirm: vi.fn(async () => true),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, patch: mocks.patch, delete: mocks.del },
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

import { TemplatesDialog, moveItem } from "../TemplatesDialog";

const TEMPLATES: TimesheetTemplate[] = [
  { id: 1, name: "Code review", description: "Przegląd kodu", project: "Alfa", sort_order: 0 },
  { id: 2, name: "Daily", description: "Spotkanie zespołu", project: null, sort_order: 0 },
];

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TemplatesDialog open onOpenChange={() => undefined} />
    </QueryClientProvider>,
  );
}

describe("kolejność", () => {
  it("moveItem nie zmienia wejścia i nie wychodzi poza listę", () => {
    const list = [1, 2, 3];
    expect(moveItem(list, 0, 1)).toEqual([2, 1, 3]);
    expect(moveItem(list, 0, -1)).toEqual([1, 2, 3]);
    expect(list).toEqual([1, 2, 3]);
  });

  it("zapisuje tylko przesunięte pozycje", () => {
    expect(
      reorderedSortOrders([
        { id: 2, sort_order: 0 },
        { id: 1, sort_order: 0 },
        { id: 3, sort_order: 2 },
      ]),
    ).toEqual([{ id: 1, sort_order: 1 }]);
  });
});

describe("TemplatesDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.confirm.mockResolvedValue(true);
    mocks.get.mockResolvedValue({ data: { items: TEMPLATES, role_default: null } });
    mocks.post.mockResolvedValue({ data: {} });
    mocks.patch.mockResolvedValue({ data: {} });
    mocks.del.mockResolvedValue({});
  });

  it("dodaje szablon na końcu listy", async () => {
    renderDialog();
    expect(await screen.findByText("Code review")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nazwa"), { target: { value: " Analiza " } });
    fireEvent.change(screen.getByLabelText("Opis"), { target: { value: "Analiza wymagań" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj szablon" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/time/me/templates", {
        name: "Analiza",
        description: "Analiza wymagań",
        project: null,
        sort_order: 2,
      }),
    );
  });

  it("pusty opis nie idzie do serwera", async () => {
    renderDialog();
    await screen.findByText("Code review");
    fireEvent.change(screen.getByLabelText("Nazwa"), { target: { value: "Coś" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj szablon" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Podaj nazwę i opis szablonu.");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("edytuje istniejący szablon", async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: Code review" }));
    expect((screen.getByLabelText("Projekt") as HTMLInputElement).value).toBe("Alfa");
    fireEvent.change(screen.getByLabelText("Opis"), { target: { value: "Przegląd kodu i testy" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/hr/time/me/templates/1", {
        name: "Code review",
        description: "Przegląd kodu i testy",
        project: "Alfa",
      }),
    );
  });

  it("usuwa po potwierdzeniu", async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: "Usuń: Daily" }));
    await waitFor(() => expect(mocks.del).toHaveBeenCalledWith("/api/hr/time/me/templates/2"));
    expect(mocks.confirm).toHaveBeenCalledTimes(1);
  });

  it("strzałka przesuwa szablon i zapisuje kolejność", async () => {
    renderDialog();
    expect(await screen.findByRole("button", { name: "Przesuń wyżej: Code review" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Przesuń niżej: Code review" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/hr/time/me/templates/1", { sort_order: 1 }),
    );
    // „Daily” ma już sort_order 0 — bez zbędnego zapisu.
    expect(mocks.patch).toHaveBeenCalledTimes(1);
  });

  it("awaria odczytu nie udaje pustej listy", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500 } });
    renderDialog();
    expect(await screen.findByRole("button", { name: /Spróbuj|Ponów/ })).toBeInTheDocument();
    expect(screen.queryByText(/Nie masz jeszcze szablonów/)).toBeNull();
  });
});
