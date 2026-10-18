/**
 * Propozycje struktury u klienta (decyzja Artura 18.10.2026 „Propozycja
 * automatu + akcept DL”): „Zatwierdź pewne” wysyła tylko pewne i niepominięte,
 * pojedyncze „Zatwierdź” — proponowaną osobę, „Pomiń” pamięta propozycję,
 * „Zmień” pozwala wpisać nową osobę, bez prawa zatwierdzania nie ma przycisków,
 * a awaria odczytu nie wygląda jak „każdy ma menedżera”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: (...a: unknown[]) => mocks.put(...a),
    delete: (...a: unknown[]) => mocks.delete(...a),
    patch: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

// Radix Select w jsdom (jak w CadenceDialog.test.tsx).
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => undefined;
}

import { StructureProposalsPanel } from "@/components/care/structure/StructureProposalsPanel";
import { telecomStructure } from "@/app/preview/hr-client-structure/fixtures";
import {
  certainManagerChoices,
  certainReportsToChoices,
  type ClientStructureProposals,
} from "@/lib/api/structure-proposals";

const TODAY = "2026-10-19";
const TELECOM = 7002;

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

function renderPanel(data: ClientStructureProposals | Error) {
  if (data instanceof Error) mocks.get.mockRejectedValue(data);
  else mocks.get.mockResolvedValue({ data });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StructureProposalsPanel clientId={TELECOM} />
    </QueryClientProvider>,
  );
}

function row(name: string): HTMLElement {
  const item = screen.getByRole("link", { name }).closest("li");
  if (!item) throw new Error(`brak wiersza ${name}`);
  return item;
}

beforeEach(() => {
  for (const fn of [mocks.get, mocks.post, mocks.put, mocks.delete, mocks.showToast]) {
    fn.mockReset();
  }
});

describe("certainManagerChoices / certainReportsToChoices", () => {
  it("biorą tylko pewne, niepominięte propozycje z osobą", () => {
    const data = telecomStructure(TODAY);
    expect(certainManagerChoices(data)).toEqual([
      { contract_id: 9501, contact_id: 8302 },
      { contract_id: 9502, contact_id: 8302 },
    ]);
    expect(certainReportsToChoices(data)).toEqual([
      { contact_id: 8302, reports_to_contact_id: 8301 },
    ]);
  });
});

describe("StructureProposalsPanel", () => {
  it("pokazuje pewność i źródło, a „Zatwierdź pewne” wysyła dwie pozycje po potwierdzeniu", async () => {
    const data = telecomStructure(TODAY);
    mocks.post.mockResolvedValue({ data: { applied: [9501, 9502], conflicts: [], client: data } });
    renderPanel(data);
    const konrad = await screen.findByRole("link", { name: "Konrad Przykładowy" });
    const item = konrad.closest("li") as HTMLElement;
    expect(within(item).getByText("pewna")).toBeInTheDocument();
    expect(
      within(item).getByText(/Skąd: „Line Manager” na kontrakcie \(Iwona Zespołowa\)/),
    ).toBeInTheDocument();
    expect(within(row("Ernest Testowy")).getByText(/Automat nie znalazł osoby/)).toBeInTheDocument();
    expect(within(row("Lena Makietowa")).queryByText(/Automat nie znalazł osoby/)).toBeNull();
    // Pominięta pozycja nie stoi na liście głównej.
    expect(screen.queryByRole("link", { name: "Oskar Fikcyjny" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Zatwierdź pewne (2)" }));
    expect(mocks.post).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Zatwierdź" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers",
        {
          items: [
            { contract_id: 9501, contact_id: 8302 },
            { contract_id: 9502, contact_id: 8302 },
          ],
        },
      ),
    );
  });

  it("pojedyncze „Zatwierdź” i „Pomiń” wysyłają proponowaną osobę", async () => {
    const data = telecomStructure(TODAY);
    mocks.post.mockResolvedValue({ data: { applied: [9503], conflicts: [], client: data } });
    mocks.put.mockResolvedValue({ data });
    renderPanel(data);
    await screen.findByRole("link", { name: "Igor Testowy" });
    fireEvent.click(within(row("Igor Testowy")).getByRole("button", { name: "Zatwierdź" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers",
        { items: [{ contract_id: 9503, contact_id: 8303 }] },
      ),
    );
    fireEvent.click(within(row("Lena Makietowa")).getByRole("button", { name: "Pomiń" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers/9504/skip",
        { proposed_contact_id: null },
      ),
    );
  });

  it("alternatywa jednym kliknięciem i „Przywróć” pominiętej", async () => {
    const data = telecomStructure(TODAY);
    mocks.post.mockResolvedValue({ data: { applied: [9503], conflicts: [], client: data } });
    mocks.delete.mockResolvedValue({ data });
    renderPanel(data);
    await screen.findByRole("link", { name: "Igor Testowy" });
    fireEvent.click(within(row("Igor Testowy")).getByRole("button", { name: "Robert Sieciowy" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers",
        { items: [{ contract_id: 9503, contact_id: 8301 }] },
      ),
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Pominięte (1)" })[0]);
    fireEvent.click(within(row("Oskar Fikcyjny")).getByRole("button", { name: /Przywróć/ }));
    await waitFor(() =>
      expect(mocks.delete).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers/9505/skip",
      ),
    );
  });

  it("„Zmień” → nowa osoba wysyła imię i stanowisko zamiast kontaktu", async () => {
    const user = userEvent.setup();
    const data = telecomStructure(TODAY);
    mocks.post.mockResolvedValue({ data: { applied: [9504], conflicts: [], client: data } });
    renderPanel(data);
    await screen.findByRole("link", { name: "Lena Makietowa" });
    await user.click(within(row("Lena Makietowa")).getByRole("button", { name: "Zmień" }));
    await user.click(screen.getByRole("combobox", { name: "Wybierz osobę klienta" }));
    await user.click(await screen.findByRole("option", { name: "Nowa osoba…" }));
    const save = within(row("Lena Makietowa")).getByRole("button", { name: "Zapisz" });
    await user.type(screen.getByRole("textbox", { name: "Imię i nazwisko" }), "Ola");
    expect(save).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Imię i nazwisko" }), " Nowa");
    await user.type(screen.getByRole("textbox", { name: "Stanowisko" }), "Kierowniczka");
    await user.click(save);
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers",
        {
          items: [
            {
              contract_id: 9504,
              contact_id: undefined,
              new_person_name: "Ola Nowa",
              new_person_position: "Kierowniczka",
            },
          ],
        },
      ),
    );
  });

  it("„Dodaj X jako menedżera” wysyła nową osobę z pola „Line Manager”, hurt po potwierdzeniu", async () => {
    const data = telecomStructure(TODAY);
    mocks.post.mockResolvedValue({ data: { applied: [9504], conflicts: [], client: data } });
    renderPanel(data);
    await screen.findByRole("link", { name: "Lena Makietowa" });
    const lena = row("Lena Makietowa");
    expect(within(lena).getByText(/takiej osoby nie ma w kontaktach klienta/)).toBeInTheDocument();
    fireEvent.click(
      within(lena).getByRole("button", { name: "Dodaj „Wiktor Liniowy” jako menedżera" }),
    );
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers",
        { items: [{ contract_id: 9504, new_person_name: "Wiktor Liniowy" }] },
      ),
    );
    mocks.post.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj z „Line Manager” (2)" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/najwyżej 1 nowa osoba/)).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Dodaj" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/care/clients/7002/structure-proposals/managers",
        {
          items: [
            { contract_id: 9504, new_person_name: "Wiktor Liniowy" },
            { contract_id: 9506, new_person_name: "Wiktor Liniowy" },
          ],
        },
      ),
    );
  });

  it("bez prawa zatwierdzania nie ma przycisków, jest zdanie, kto zatwierdza", async () => {
    renderPanel({
      ...telecomStructure(TODAY),
      can_apply_managers: false,
      can_apply_org: false,
    });
    await screen.findByRole("link", { name: "Konrad Przykładowy" });
    for (const name of ["Zatwierdź", "Zmień", "Pomiń", /Zatwierdź pewne/, /Dodaj/]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(
      screen.getByText("Propozycje zatwierdza Delivery Lead klienta albo administrator."),
    ).toBeInTheDocument();
  });

  it("awaria odczytu to komunikat z ponowieniem, nie „każdy ma menedżera”", async () => {
    renderPanel(httpError(500));
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Każdy konsultant ma wskazanego menedżera/)).toBeNull();
  });
});
