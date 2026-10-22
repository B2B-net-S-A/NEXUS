/**
 * „Struktura u klienta” i okno opinii (etap 2, D8–D11): awaria odczytu nie
 * wygląda jak pusta struktura, czytelnik bez prawa edycji nie dostaje list
 * wyboru, „Podlega pod” nie podsuwa podwładnych (pętla), a zapis opinii
 * pomija konsultantów oznaczonych „pomiń” i tych bez żadnej oceny.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    patch: (...a: unknown[]) => mocks.patch(...a),
    put: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

import { ClientFeedbackDialog } from "@/components/care/ClientFeedbackDialog";
import { ClientPeopleTab } from "@/components/care/ClientPeopleTab";
import {
  descendantIds,
  endLabel,
  managerOptions,
  orgPeople,
} from "@/components/care/client-people-format";
import { scoresForPayload, type ClientOrg } from "@/lib/api/client-people";
import { clientOrg } from "@/app/preview/hr-client-people/fixtures";
import { bankStructure } from "@/app/preview/hr-client-structure/fixtures";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

function renderWith(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const TODAY = "2026-10-19";

/** Drzewo i propozycje automatu nad nim to dwa zapytania zakładki. */
function serve(org: ClientOrg) {
  mocks.get.mockImplementation((url: string) =>
    Promise.resolve({ data: url.endsWith("/structure-proposals") ? bankStructure() : org }),
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.patch.mockReset();
  mocks.showToast.mockReset();
});

describe("client-people-format", () => {
  it("„Podlega pod” nie podsuwa samej osoby ani jej podwładnych", () => {
    const people = orgPeople(clientOrg(TODAY));
    const director = people.find((p) => p.name === "Zenon Dyrektorski");
    expect(director).toBeDefined();
    if (!director) return;
    expect([...descendantIds(people, director.id)]).toEqual([8202]);
    expect(managerOptions(people, director).map((o) => o.name)).toEqual([
      "Katarzyna Płatnicza",
      "Michał Liniowy",
    ]);
  });

  it("koniec współpracy mówi, czy to zamówienie, czy umowa", () => {
    expect(endLabel({ end_date: "2026-11-30", end_source: "order" })).toBe(
      "zamówienie do 30.11.2026",
    );
    expect(endLabel({ end_date: "2026-11-30", end_source: "contract" })).toBe(
      "umowa do 30.11.2026",
    );
    expect(endLabel({ end_date: null, end_source: null })).toBe("bez daty końca");
  });

  it("wiersz bez ocen i „pomiń” nie idą do serwera", () => {
    expect(
      scoresForPayload(
        { 1: { quality: 4 }, 2: { quality: null }, 3: { autonomy: 5 } },
        new Set([3]),
      ),
    ).toEqual([{ contract_id: 1, quality: 4, communication: null, autonomy: null }]);
  });
});

describe("ClientPeopleTab", () => {
  it("awaria odczytu to komunikat z ponowieniem, nie pusta struktura", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderWith(<ClientPeopleTab clientId={7001} />);
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma jeszcze osób klienta/)).toBeNull();
  });

  it("czytelnik bez prawa edycji widzi strukturę bez list wyboru", async () => {
    const org: ClientOrg = {
      ...clientOrg(TODAY),
      can_edit_org: false,
      can_write_feedback: false,
    };
    serve(org);
    renderWith(<ClientPeopleTab clientId={7001} />);
    const data = await screen.findByRole("region", { name: "Data" });
    fireEvent.click(within(data).getByRole("button", { name: /Piotr Menedżerski/ }));
    const panel = screen.getByRole("complementary", { name: "Osoba: Piotr Menedżerski" });
    expect(within(panel).queryByRole("combobox", { name: "Podlega pod" })).toBeNull();
    expect(within(panel).getByText("Zenon Dyrektorski")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz opinię" })).toBeNull();
  });

  it("„Przypisz: Data” z tekstu działu zapisuje dział dopiero po kliknięciu", async () => {
    const org = clientOrg(TODAY);
    serve(org);
    mocks.patch.mockResolvedValue({ data: org });
    renderWith(<ClientPeopleTab clientId={7001} />);
    const loose = await screen.findByRole("region", { name: "Bez działu" });
    fireEvent.click(within(loose).getByRole("button", { name: /Michał Liniowy/ }));
    expect(mocks.patch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Przypisz: Data" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/care/clients/7001/contacts/8204", {
        client_area_id: 303,
      }),
    );
  });
});

describe("ClientPeopleTab · propozycje automatu", () => {
  it("sekcja jest zwinięta i nic nie zapisuje, dopóki DL nie kliknie", async () => {
    serve(clientOrg(TODAY));
    renderWith(<ClientPeopleTab clientId={7001} />);
    expect(
      await screen.findByText(/1 konsultant bez menedżera · 1 pewna propozycja/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zatwierdź" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Przejrzyj propozycje" }));
    expect(await screen.findByText(/Skąd: „Line Manager” na kontrakcie/)).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("awaria propozycji nie zasłania drzewa", async () => {
    const org = clientOrg(TODAY);
    mocks.get.mockImplementation((url: string) =>
      url.endsWith("/structure-proposals")
        ? Promise.reject(httpError(500))
        : Promise.resolve({ data: org }),
    );
    renderWith(<ClientPeopleTab clientId={7001} />);
    expect(await screen.findByRole("region", { name: "Data" })).toBeInTheDocument();
    expect(screen.queryByText("Propozycje automatu")).toBeNull();
  });
});

describe("ClientFeedbackDialog", () => {
  it("zapisuje oceny, przedłużenie i notatkę, bez pominiętych konsultantów", async () => {
    const org = clientOrg(TODAY);
    const head = orgPeople(org).find((p) => p.name === "Piotr Menedżerski");
    if (!head) throw new Error("brak osoby w danych");
    mocks.post.mockResolvedValue({ data: { id: 1, contract_ids: [9401] } });
    const onOpenChange = vi.fn();
    renderWith(
      <ClientFeedbackDialog
        clientId={7001}
        clientName="Bank Przykładowy"
        manager={{ id: head.id, name: head.name }}
        consultants={head.consultants}
        open
        onOpenChange={onOpenChange}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Jakość pracy — Michał Konsultantowy: 5" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Samodzielność — Michał Konsultantowy: 4" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Jakość pracy — Karolina Przykładowa: 3" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Pomiń: Karolina Przykładowa" }));
    fireEvent.click(screen.getByRole("radio", { name: "raczej tak" }));
    fireEvent.change(screen.getByLabelText("Co mówi klient"), {
      target: { value: "  Zespół chce zostać w tym składzie.  " },
    });
    expect(
      screen.getByText("Konsultant tej opinii nie widzi. Bez danych o zdrowiu i bez stawek.", {
        exact: false,
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz opinię" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.post.mock.calls[0];
    expect(url).toBe("/api/care/clients/7001/feedback");
    expect(body).toMatchObject({
      contact_id: head.id,
      channel: "phone",
      extension_outlook: "likely",
      note: "Zespół chce zostać w tym składzie.",
      scores: [{ contract_id: 9401, quality: 5, communication: null, autonomy: 4 }],
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("odmowa serwera zostaje w oknie jako komunikat", async () => {
    const org = clientOrg(TODAY);
    const head = orgPeople(org)[1];
    mocks.post.mockRejectedValue(
      Object.assign(new Error("HTTP 422"), {
        response: {
          status: 422,
          data: { detail: "Oceniać można tylko konsultantów pracujących u tego klienta." },
        },
      }),
    );
    renderWith(
      <ClientFeedbackDialog
        clientId={7001}
        clientName="Bank Przykładowy"
        manager={{ id: head.id, name: head.name }}
        consultants={head.consultants}
        open
        onOpenChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Zapisz opinię" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Oceniać można tylko konsultantów pracujących u tego klienta.",
    );
  });
});
