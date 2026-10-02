/**
 * Pasek akcji zbiorczych: „Oznacz zakończone" wysyła powód i datę, a odmowa
 * serwera zostaje na ekranie.
 *
 * Do 09.2026 `bulkMarkEnded` nie miało `catch`, a `finally` zamykało okno
 * niezależnie od wyniku: odrzucona partia (umowa `void` w zaznaczeniu → 409)
 * kończyła się zamkniętym dialogiem i niezmienioną listą, bez słowa
 * wyjaśnienia. Operacja jest atomowa, więc odmowa MUSI być widoczna.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// `vi.mock` jest hoistowane ponad zmienne modułu, więc mock musi powstać
// wewnątrz `vi.hoisted` — inaczej fabryka sięga po niezainicjalizowaną stałą.
const { bulkMarkEnded } = vi.hoisted(() => ({ bulkMarkEnded: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    default: { post: vi.fn() },
    contractsApi: { ...actual.contractsApi, bulkMarkEnded },
  };
});

import { useAuthStore } from "@/store/auth";
import { permissionSnapshot } from "@/test/fixtures/permission-snapshot";
import { ContractsBulkActionsBarV2 } from "../ContractsBulkActionsBar";

/** Pasek czyta konto z prawdziwego store'u — tak jak na ekranie. */
function signIn(user: Record<string, unknown>, realUser: unknown = null) {
  useAuthStore.setState({ user, realUser, hydrated: true } as never);
}

function renderBar(selectedIds: number[] = [7, 9]) {
  const onDone = vi.fn();
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
    <ContractsBulkActionsBarV2
      selectedIds={new Set(selectedIds)}
      onClear={vi.fn()}
      onDone={onDone}
      onSelectAllVisible={vi.fn()}
      visibleCount={12}
    />
    </QueryClientProvider>,
  );
  return { onDone };
}

function fillAndSubmit() {
  fireEvent.click(screen.getByRole("button", { name: /Oznacz zakończone/ }));
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "project_ended" },
  });
  fireEvent.change(document.querySelector('input[type="date"]')!, {
    target: { value: "2026-10-31" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zakończ" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  signIn({ id: 1, role: "delivery_lead", roles: ["delivery_lead"] });
});

afterEach(() => cleanup());

describe("ContractsBulkActionsBarV2 — Oznacz zakończone", () => {
  it("wysyła zaznaczone id wraz z powodem i datą", async () => {
    bulkMarkEnded.mockResolvedValue({ data: { requested: 2, changed: 2 } });
    const { onDone } = renderBar();

    fillAndSubmit();

    await waitFor(() =>
      expect(bulkMarkEnded).toHaveBeenCalledWith([7, 9], {
        termination_reason: "project_ended",
        terminated_at: "2026-10-31",
        termination_lessons: null,
        agreement_termination: null,
      }),
    );
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(onDone.mock.calls[0][0]).toContain("2");
  });

  it("zostawia okno otwarte i pokazuje odmowę serwera", async () => {
    bulkMarkEnded.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: { message: "Illegal contract status transition" } },
      },
    });
    const { onDone } = renderBar();

    fillAndSubmit();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Illegal contract status transition",
      ),
    );
    // Okno zostaje otwarte — użytkownik widzi, czego dyspozycja dotyczyła.
    expect(screen.getByRole("button", { name: "Zakończ" })).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
  });
});

describe("ContractsBulkActionsBarV2 — każda akcja ma własne uprawnienie", () => {
  const extendButtons = () =>
    screen.queryAllByRole("button", { name: /^\+(3|6|12)m$/ });
  const endButton = () =>
    screen.queryByRole("button", { name: /Oznacz zakończone/ });

  it("Delivery Lead (oba uprawnienia domyślnie) widzi przedłużanie i zakończenie", () => {
    renderBar();

    expect(extendButtons()).toHaveLength(3);
    expect(endButton()).toBeInTheDocument();
  });

  it("Talent Community Manager kończy współpracę, ale nie przedłuża", () => {
    signIn({ id: 2, role: "talent_community_manager" });
    renderBar();

    expect(endButton()).toBeInTheDocument();
    expect(extendButtons()).toHaveLength(0);
  });

  it("Finanse przedłużają, ale nie kończą współpracy", () => {
    signIn({ id: 3, role: "finance" });
    renderBar();

    expect(extendButtons()).toHaveLength(3);
    expect(endButton()).not.toBeInTheDocument();
  });

  it("rekruter z nadanym uprawnieniem widzi dokładnie tę akcję, którą dostał", () => {
    signIn({
      id: 4,
      role: "recruiter",
      effective_action_access: permissionSnapshot("contract_status"),
    });
    renderBar();
    expect(endButton()).toBeInTheDocument();
    expect(extendButtons()).toHaveLength(0);
    cleanup();

    signIn({
      id: 4,
      role: "recruiter",
      effective_action_access: permissionSnapshot("contracts_orders_edit"),
    });
    renderBar();
    expect(extendButtons()).toHaveLength(3);
    expect(endButton()).not.toBeInTheDocument();
  });

  it("Delivery Lead z wyłączonym zakończeniem współpracy nie widzi „Oznacz zakończone”", () => {
    signIn({
      id: 5,
      role: "delivery_lead",
      effective_action_access: permissionSnapshot("contracts_orders_edit"),
    });
    renderBar();

    expect(extendButtons()).toHaveLength(3);
    expect(endButton()).not.toBeInTheDocument();
  });

  it("konto bez żadnego z dwóch uprawnień nie dostaje paska ani zaznaczania", () => {
    signIn({ id: 6, role: "recruiter" });
    renderBar([]);

    expect(screen.queryByText(/Zaznacz widoczne/)).not.toBeInTheDocument();
    expect(endButton()).not.toBeInTheDocument();
    expect(extendButtons()).toHaveLength(0);
  });

  it("w podglądzie jako inny użytkownik pasek znika — serwer i tak odmówi zapisu", () => {
    signIn(
      { id: 7, role: "delivery_lead", roles: ["delivery_lead"] },
      { id: 1, role: "admin" },
    );
    renderBar();

    expect(endButton()).not.toBeInTheDocument();
    expect(extendButtons()).toHaveLength(0);
  });
});
