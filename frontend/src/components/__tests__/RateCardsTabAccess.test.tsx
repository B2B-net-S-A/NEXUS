/**
 * Cennik klienta: bramka FE jest lustrem backendu, a awaria nie udaje pustki.
 *
 * Do sierpnia 2026 kontrolki wisiały na literale `["admin","delivery_lead"]` —
 * pozostałości po erze `DeliveryLeadPlus` sprzed cutoveru RBAC (#1031). Backend
 * przestawił `/api/rate-cards` na `FinanceReadUser`/`FinanceManageUser`
 * (VIEW_FINANCE / MANAGE_FINANCE), więc lista FE była JEDNOCZEŚNIE za szeroka
 * (Delivery Lead dostawał 403 przy każdym zapisie) i za wąska (rola finance,
 * jedyna nie-adminowa z tą capability, nie widziała żadnego przycisku).
 * Do tego 403 na odczycie renderowało się jako „Brak wpisów cennika".
 *
 * Test idzie przez prawdziwe `hasAnalyticsCapability` (mockowany jest tylko
 * nośnik użytkownika) i przez prawdziwą ścieżkę zapytania — czyli dokładnie
 * przez te dwie warstwy, na których siedział defekt.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

interface TestUser {
  role: string;
  capabilities: string[];
}

const authState: { user: TestUser | null } = { user: null };

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  return {
    ...actual,
    useAuthStore: (selector: (s: { user: TestUser | null }) => unknown) =>
      selector(authState),
  };
});

vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  extractErrorMsg: (e: unknown) => String(e),
}));

import { RateCardsTab } from "@/components/RateCardsTab";

const EMPTY_TEXT = /Brak wpisów cennika/;
const ADD_BUTTON = /Dodaj wpis cennika/;
const FORBIDDEN_TITLE = "Brak uprawnień";

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RateCardsTab clientId={7} />
    </QueryClientProvider>,
  );
}

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

beforeEach(() => {
  mocks.get.mockReset();
  authState.user = null;
});

describe("RateCardsTab — bramka capability", () => {
  it("Delivery Lead bez VIEW_FINANCE nie dostaje UI, które i tak zwróci 403", async () => {
    authState.user = { role: "delivery_lead", capabilities: [] };
    mocks.get.mockResolvedValue({ data: [] });

    renderTab();

    expect(await screen.findByText(FORBIDDEN_TITLE)).toBeInTheDocument();
    expect(screen.queryByText(ADD_BUTTON)).not.toBeInTheDocument();
    // Kluczowe: brak uprawnień NIE może się przedstawić jako pusty cennik.
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    // Bez uprawnień nie ma po co pytać backendu o 403.
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("finance z MANAGE_FINANCE widzi kontrolki zapisu", async () => {
    authState.user = {
      role: "finance",
      capabilities: ["view_finance", "manage_finance"],
    };
    mocks.get.mockResolvedValue({ data: [] });

    renderTab();

    expect(await screen.findByText(ADD_BUTTON)).toBeInTheDocument();
  });

  it("view_finance bez manage_finance czyta, ale nie dostaje zachęty do dodania", async () => {
    authState.user = { role: "finance", capabilities: ["view_finance"] };
    mocks.get.mockResolvedValue({ data: [] });

    renderTab();

    expect(
      await screen.findByText("Brak wpisów cennika dla tego klienta."),
    ).toBeInTheDocument();
    expect(screen.queryByText(ADD_BUTTON)).not.toBeInTheDocument();
  });
});

describe("RateCardsTab — awaria odczytu nie udaje pustki", () => {
  it("403 z backendu renderuje brak uprawnień, nie „Brak wpisów cennika”", async () => {
    authState.user = {
      role: "admin",
      capabilities: ["view_finance", "manage_finance"],
    };
    mocks.get.mockRejectedValue(httpError(403));

    renderTab();

    expect(await screen.findByText(FORBIDDEN_TITLE)).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
  });

  it("500 renderuje awarię z ponowieniem, nie „Brak wpisów cennika”", async () => {
    authState.user = {
      role: "admin",
      capabilities: ["view_finance", "manage_finance"],
    };
    mocks.get.mockRejectedValue(httpError(500));

    renderTab();

    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
  });

  it("sukces z zerem wpisów nadal pokazuje pusty stan", async () => {
    authState.user = {
      role: "admin",
      capabilities: ["view_finance", "manage_finance"],
    };
    mocks.get.mockResolvedValue({ data: [] });

    renderTab();

    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(FORBIDDEN_TITLE)).not.toBeInTheDocument();
  });
});
