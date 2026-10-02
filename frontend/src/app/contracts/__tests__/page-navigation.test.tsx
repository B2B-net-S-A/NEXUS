import type React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ContractsPage from "@/app/contracts/page";
import { useAuthStore } from "@/store/auth";
import {
  permissionSnapshot,
  sectionSnapshot,
} from "@/__tests__/fixtures/permission-snapshot";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

vi.mock("@/components/v2/pages/ContractsListV2", () => ({
  ContractsListV2: (props: { modeTabs?: React.ReactNode; toolbarLead?: React.ReactNode }) => (
    <div>
      {props.modeTabs}
      {props.toolbarLead}
      Globalny rejestr
    </div>
  ),
}));

vi.mock("@/components/v2/pages/ContractorsListV2", () => ({
  ContractorsListV2: (props: { modeTabs?: React.ReactNode }) => (
    <div>
      {props.modeTabs}
      Widok operacyjny
    </div>
  ),
}));

vi.mock("@/components/contracts/ContractsClientPicker", () => ({
  ContractsClientPicker: () => <div>Wybór klienta</div>,
}));

vi.mock("@/components/order-mail/OrderMailQueue", () => ({
  OrderMailQueue: () => <div>Skrzynka zamówień z maila</div>,
}));

vi.mock("@/components/order-mail/useOrderMailPendingCount", () => ({
  useOrderMailPendingCount: () => 3,
}));

vi.mock("@/components/contracts/ClientContractRegister", () => ({
  ClientContractRegister: (props: { modeTabs?: React.ReactNode; toolbarLead?: React.ReactNode }) => (
    <div>
      {props.modeTabs}
      {props.toolbarLead}
      Rejestr klienta
    </div>
  ),
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

  it("Skrzynka zamówień jest trybem Kontraktów z licznikiem, a ?view=order-mail ją otwiera", async () => {
    window.history.replaceState({}, "", "/contracts?view=order-mail&doc=5");
    render(<ContractsPage />);
    expect(await screen.findByText("Skrzynka zamówień z maila")).toBeInTheDocument();
    const tab = screen.getByRole("tab", { name: /Skrzynka zamówień/ });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(tab).toHaveTextContent("3");

    fireEvent.click(screen.getByRole("tab", { name: "Rejestr kontraktów" }));
    expect(await screen.findByText("Globalny rejestr")).toBeInTheDocument();
    await waitFor(() =>
      expect(`${window.location.pathname}${window.location.search}`).toBe("/contracts"),
    );
    fireEvent.click(screen.getByRole("tab", { name: /Skrzynka zamówień/ }));
    await waitFor(() =>
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        "/contracts?view=order-mail",
      ),
    );
  });
});

describe("ContractsPage — „Obsługa kontraktorów” widzi posiadacz podglądu Delivery", () => {
  const OPERATIONS = { name: "Obsługa kontraktorów" };

  function signIn(user: Record<string, unknown>) {
    useAuthStore.setState({
      user: { id: 7, email: "osoba@example.com", name: "Osoba", ...user },
      hydrated: true,
    } as never);
  }

  beforeEach(() => {
    window.history.replaceState({}, "", "/contracts");
  });

  afterEach(() => {
    cleanup();
    useAuthStore.setState({ user: null, hydrated: true });
  });

  it.each(["delivery_lead", "talent_community_manager", "finance"])(
    "%s ma podgląd domyślnie i widzi tryb",
    async (role) => {
      signIn({ role, roles: [role] });
      render(<ContractsPage />);

      expect(await screen.findByRole("tab", OPERATIONS)).toBeInTheDocument();
    },
  );

  it("rekruter z nadanym podglądem widzi tryb i otwiera go z adresu", async () => {
    window.history.replaceState({}, "", "/contracts?view=operations&tab=active");
    signIn({
      role: "recruiter",
      roles: ["recruiter"],
      effective_action_access: permissionSnapshot("delivery_view"),
      effective_section_access: sectionSnapshot(["delivery_view"]),
    });
    render(<ContractsPage />);

    expect(await screen.findByText("Widok operacyjny")).toBeInTheDocument();
    expect(screen.getByRole("tab", OPERATIONS)).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("rekruter bez uprawnienia nie ma trybu, a ?view=operations wraca do rejestru", async () => {
    window.history.replaceState({}, "", "/contracts?view=operations&tab=active");
    signIn({ role: "recruiter", roles: ["recruiter"] });
    render(<ContractsPage />);

    expect(await screen.findByText("Globalny rejestr")).toBeInTheDocument();
    expect(screen.queryByText("Widok operacyjny")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", OPERATIONS)).not.toBeInTheDocument();
  });

  it("Talent Community Manager z wyłączonym podglądem nie widzi trybu", async () => {
    signIn({
      role: "talent_community_manager",
      roles: ["talent_community_manager"],
      effective_action_access: permissionSnapshot(),
      effective_section_access: sectionSnapshot([]),
    });
    render(<ContractsPage />);

    expect(await screen.findByText("Globalny rejestr")).toBeInTheDocument();
    expect(screen.queryByRole("tab", OPERATIONS)).not.toBeInTheDocument();
  });
});
