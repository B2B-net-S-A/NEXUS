import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, put: mocks.put },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

import { OnboardingPackTab } from "../OnboardingPackTab";
import { packFixture } from "./pack-fixture";

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OnboardingPackTab clientId={7} />
    </QueryClientProvider>,
  );
}

function apiError(status: number, detail: string) {
  return Object.assign(new Error(detail), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

describe("OnboardingPackTab", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.put.mockReset();
    mocks.toast.mockReset();
  });

  it("pokazuje cztery części pakietu z danymi z serwera", async () => {
    mocks.get.mockResolvedValue({ data: packFixture() });
    renderTab();
    expect(await screen.findByRole("region", { name: "Sprzęt" })).toBeInTheDocument();
    for (const name of ["Pierwszy dzień", "Dokumenty od konsultanta", "Dostępy"]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    expect(screen.getByDisplayValue("Laptop 14 cali")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Zaświadczenie o niekaralności")).toBeInTheDocument();
    expect(screen.getByText(/dotyczy 2 kontraktów/)).toBeInTheDocument();
    // Bez zmian nie ma czego zapisać.
    expect(screen.getByRole("button", { name: "Zapisz pakiet" })).toBeDisabled();
  });

  it("zapisuje zmianę z wersją, od której zaczęła się edycja", async () => {
    mocks.get.mockResolvedValue({ data: packFixture() });
    mocks.put.mockResolvedValue({ data: packFixture({ version: 4 }) });
    renderTab();
    const place = await screen.findByLabelText("Gdzie");
    fireEvent.change(place, { target: { value: "ul. Testowa 1, recepcja A" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz pakiet" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const [url, payload] = mocks.put.mock.calls[0];
    expect(url).toBe("/api/client-onboarding/clients/7/pack");
    expect(payload.expected_version).toBe(3);
    expect(payload.first_day.place).toBe("ul. Testowa 1, recepcja A");
    expect(payload.documents).toHaveLength(1);
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Pakiet zapisany", "success"));
  });

  it("nie wysyła pozycji bez nazwy i mówi, co poprawić", async () => {
    mocks.get.mockResolvedValue({ data: packFixture() });
    renderTab();
    await screen.findByRole("region", { name: "Dokumenty od konsultanta" });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj dokument" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz pakiet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Uzupełnij nazwę/);
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("odmowa serwera (cudza zmiana) zostaje na ekranie", async () => {
    mocks.get.mockResolvedValue({ data: packFixture() });
    mocks.put.mockRejectedValue(
      apiError(409, "Ktoś zmienił pakiet w międzyczasie — odśwież i wprowadź zmiany jeszcze raz."),
    );
    renderTab();
    fireEvent.change(await screen.findByLabelText("Co zabrać"), { target: { value: "dowód" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz pakiet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/zmienił pakiet w międzyczasie/);
  });

  it("recepcja edytuje sprzęt, resztę widzi tylko do odczytu", async () => {
    mocks.get.mockResolvedValue({
      data: packFixture({ can_edit: { equipment: true, rest: false } }),
    });
    renderTab();
    const documents = await screen.findByRole("region", { name: "Dokumenty od konsultanta" });
    expect(within(documents).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(documents).getByText("Zaświadczenie o niekaralności")).toBeInTheDocument();
    expect(
      within(documents).getByText(/5 dni rob\. przed startem · wymagane · z plikiem/),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("Laptop 14 cali")).toBeInTheDocument();
    expect(screen.getByText(/Z uprawnieniem „Sprzęt” zmieniasz część sprzętową/)).toBeInTheDocument();
  });

  it("bez prawa zapisu nie ma przycisku „Zapisz pakiet”", async () => {
    mocks.get.mockResolvedValue({
      data: packFixture({ can_edit: { equipment: false, rest: false } }),
    });
    renderTab();
    await screen.findByRole("region", { name: "Sprzęt" });
    expect(screen.queryByRole("button", { name: "Zapisz pakiet" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj/ })).not.toBeInTheDocument();
  });

  it("awaria odczytu nie wygląda jak pusty pakiet", async () => {
    mocks.get.mockRejectedValue(apiError(500, "błąd"));
    renderTab();
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Sprzęt" })).not.toBeInTheDocument();
  });
});
