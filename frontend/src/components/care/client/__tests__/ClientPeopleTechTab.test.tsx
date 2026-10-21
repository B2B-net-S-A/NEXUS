/**
 * Zakładka klienta „Ludzie i technologie” (22.10.2026): widok „Działy”
 * składa karty z mapy i drzewa (kropka zdrowia, żółta ramka otwartej
 * rekrutacji, „Szukają”), pasek „Do zatwierdzenia” pokazuje JEDNĄ propozycję
 * i zatwierdza ją trasą panelu propozycji, konto spoza kręgu D11 nie dostaje
 * drzewa ani paska, a awaria drzewa nie udaje pustej struktury. Dane fikcyjne.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), showToast: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));
vi.mock("@/components/care/UnlinkedCardsPanel", () => ({ UnlinkedCardsPanel: () => null }));

import { ClientPeopleTechTab } from "@/components/care/client/ClientPeopleTechTab";
import type { PeopleView } from "@/components/care/client/people-tech-format";
import { clientOrgWithHealth, peopleTechMap } from "@/app/preview/hr-client-people/fixtures";
import { bankStructure } from "@/app/preview/hr-client-structure/fixtures";
import { useAuthStore, type User } from "@/store/auth";

const TODAY = "2026-10-22";

const dl = {
  id: 102,
  email: "dl@example.com",
  name: "Kamil Testowy",
  role: "delivery_lead",
  roles: ["delivery_lead"],
} as unknown as User;
const finance = {
  id: 109,
  email: "fin@example.com",
  name: "Piotr Finansowy",
  role: "finance",
  roles: ["finance"],
} as unknown as User;

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

function serve({ orgFails = false } = {}) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/tech-map")) return { data: peopleTechMap(TODAY) };
    if (url.endsWith("/org")) {
      if (orgFails) throw httpError(500);
      return { data: clientOrgWithHealth(TODAY) };
    }
    if (url.endsWith("/structure-proposals")) return { data: bankStructure() };
    if (url === "/api/care/owners") return { data: { items: [] } };
    throw new Error(`niezasiane: ${url}`);
  });
}

function renderTab(view: PeopleView = "dzialy") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onViewChange = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ClientPeopleTechTab clientId={7001} view={view} onViewChange={onViewChange} />
    </QueryClientProvider>,
  );
  return { onViewChange };
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.showToast.mockReset();
  useAuthStore.setState({ user: dl, hydrated: true });
});

describe("ClientPeopleTechTab · Działy", () => {
  it("karta działu: menedżer z „Podlega pod”, kropka zdrowia, ramka rekrutacji, „Szukają”", async () => {
    serve();
    renderTab();
    const payments = await screen.findByRole("article", { name: "Dział Płatności" });
    expect(payments.className).toContain("border-warning");
    expect(within(payments).getByText("Katarzyna Płatnicza")).toBeInTheDocument();
    expect(within(payments).getByText(/Szukają:/).parentElement).toHaveTextContent(
      "Java Developer, DevOps Engineer (OpenShift), Java, QA",
    );
    // Konsultantka z „Ryzyko” — kropka i etykieta dla czytnika.
    expect(within(payments).getByRole("link", { name: /Anna .*Ryzyko/ })).toHaveAttribute(
      "href",
      "/care?contract=9404",
    );
    expect(within(payments).getByText("Komu podlega Katarzyna Płatnicza?")).toBeInTheDocument();
    const data = screen.getByRole("article", { name: "Dział Data" });
    expect(data.className).not.toContain("border-warning");
    expect(within(data).getByText(/podlega pod: Zenon Dyrektorski/)).toBeInTheDocument();
    // Dział bez sygnału schowany jak na mapie.
    expect(screen.queryByRole("article", { name: "Dział CI/CD i chmura" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie działy (4)" }));
    expect(screen.getByRole("article", { name: "Dział CI/CD i chmura" })).toBeInTheDocument();
    // Liczby kompletności nagłówka.
    expect(
      screen.getByText(/5 naszych konsultantów · 2 z 4 działów z naszymi · 4 z 5 z menedżerem/),
    ).toBeInTheDocument();
  });

  it("pasek „Do zatwierdzenia”: jedna propozycja, zatwierdzenie idzie trasą propozycji", async () => {
    serve();
    mocks.post.mockResolvedValue({
      data: { applied: [9405], conflicts: [], client: { ...bankStructure(), managers: [] } },
    });
    renderTab();
    const bar = await screen.findByRole("region", { name: "Do zatwierdzenia" });
    expect(within(bar).getByText("Michał Liniowy")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Wszystkie propozycje (2)" })).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(within(bar).getByRole("button", { name: "Zatwierdź" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/care/clients/7001/structure-proposals/managers",
        { items: [{ contract_id: 9405, contact_id: 8204 }] },
      ),
    );
  });

  it("przełącznik widoków: Działy · Drzewo osób · Mapa", async () => {
    serve();
    const { onViewChange } = renderTab();
    await screen.findByRole("article", { name: "Dział Płatności" });
    fireEvent.click(screen.getByRole("radio", { name: "Mapa" }));
    expect(onViewChange).toHaveBeenCalledWith("mapa");
    expect(screen.getByRole("radio", { name: "Drzewo osób" })).toBeInTheDocument();
  });

  it("awaria drzewa: komunikat z ponowieniem, karty z mapy zostają", async () => {
    serve({ orgFails: true });
    renderTab();
    expect(await screen.findByRole("alert")).toHaveTextContent(/menedżerów z mapy/);
    expect(await screen.findByRole("article", { name: "Dział Płatności" })).toBeInTheDocument();
  });
});

describe("ClientPeopleTechTab · konto spoza kręgu D11", () => {
  it("Finanse: działy z mapy, bez drzewa, paska propozycji i zapisu opinii", async () => {
    useAuthStore.setState({ user: finance, hydrated: true });
    serve();
    renderTab("drzewo");
    // „Drzewo” w adresie nie otwiera drzewa — wraca widok Działy.
    expect(await screen.findByRole("article", { name: "Dział Płatności" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Drzewo osób" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Do zatwierdzenia" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Zapisz opinię/ })).toBeNull();
    const urls = mocks.get.mock.calls.map(([url]) => url as string);
    expect(urls.some((url) => url.endsWith("/org"))).toBe(false);
    expect(urls.some((url) => url.endsWith("/structure-proposals"))).toBe(false);
  });
});
