import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ContractsPage from "@/app/contracts/page";
import { useAuthStore } from "@/store/auth";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

vi.mock("@/components/v2/pages/ContractsListV2", () => ({
  ContractsListV2: () => <div>Globalny rejestr</div>,
}));

vi.mock("@/components/v2/pages/ContractorsListV2", () => ({
  ContractorsListV2: () => <div>Widok operacyjny</div>,
}));

vi.mock("@/components/contracts/ContractsClientPicker", () => ({
  ContractsClientPicker: () => <div>Wybór klienta</div>,
}));

vi.mock("@/components/contracts/ClientContractRegister", () => ({
  ClientContractRegister: () => <div>Rejestr klienta</div>,
}));

describe("ContractsPage — przełączanie widoków", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        id: 1,
        email: "admin@example.com",
        name: "Admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: [],
        analytics_capabilities: [],
      },
      hydrated: true,
    });
  });

  afterEach(() => {
    cleanup();
    useAuthStore.setState({ user: null, hydrated: true });
  });

  it("nie przenosi globalnych filtrów ani strony do widoku operacyjnego", async () => {
    window.history.replaceState(
      { next: "preserved" },
      "",
      "/contracts?status=draft&contract_type=b2b&q=Nordea&page=6",
    );
    render(<ContractsPage />);

    const operations = await screen.findByRole("tab", {
      name: "Obsługa kontraktorów",
    });
    fireEvent.click(operations);

    await waitFor(() => {
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        "/contracts?view=operations&tab=active",
      );
      expect(window.history.state).toEqual({ next: "preserved" });
    });
  });

  it("nie przenosi operacyjnego tabu ani strony do świeżego rejestru", async () => {
    window.history.replaceState(
      { next: "preserved" },
      "",
      "/contracts?view=operations&tab=ending&contractors_page=7&page=9&status=draft",
    );
    render(<ContractsPage />);

    expect(await screen.findByText("Widok operacyjny")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("tab", { name: "Rejestr kontraktów" }),
    );

    await waitFor(() => {
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        "/contracts",
      );
      expect(window.history.state).toEqual({ next: "preserved" });
    });
  });

  it("queryless wejście resetuje klienta i operations bez remountu strony", async () => {
    window.history.replaceState(
      {},
      "",
      "/contracts?client=42&clientName=Nordea&register_status=draft&register_page=3",
    );
    const view = render(<ContractsPage />);
    expect(await screen.findByText("Rejestr klienta")).toBeInTheDocument();

    window.history.replaceState({}, "", "/contracts");
    view.rerender(<ContractsPage />);
    expect(await screen.findByText("Globalny rejestr")).toBeInTheDocument();
    expect(screen.queryByText("Rejestr klienta")).not.toBeInTheDocument();

    window.history.replaceState(
      {},
      "",
      "/contracts?view=operations&tab=ending&contractors_page=4",
    );
    view.rerender(<ContractsPage />);
    expect(await screen.findByText("Widok operacyjny")).toBeInTheDocument();

    window.history.replaceState({}, "", "/contracts");
    view.rerender(<ContractsPage />);
    expect(await screen.findByText("Globalny rejestr")).toBeInTheDocument();
    expect(screen.queryByText("Widok operacyjny")).not.toBeInTheDocument();
  });
});
