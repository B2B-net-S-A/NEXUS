import type React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ContractsPage from "@/app/contracts/page";
import { useAuthStore, type User } from "@/store/auth";
import {
  permissionSnapshot,
  sectionSnapshot,
} from "@/__tests__/fixtures/permission-snapshot";

const mockReplace = vi.fn();
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => ({ replace: mockReplace, push: mockPush }),
}));

vi.mock("@/components/v2/pages/ContractsListV2", () => ({
  ContractsListV2: (props: {
    toolbarLead?: React.ReactNode;
    trailingActions?: React.ReactNode;
  }) => (
    <div>
      {props.toolbarLead}
      {props.trailingActions}
      Globalny rejestr
    </div>
  ),
}));

vi.mock("@/components/contracts/ContractsClientPicker", () => ({
  ContractsClientPicker: (props: {
    onChange: (client: { id: number; name: string } | null) => void;
  }) => (
    <button type="button" onClick={() => props.onChange({ id: 12, name: "Bank Przykładowy" })}>
      Wybierz klienta
    </button>
  ),
}));

vi.mock("@/components/order-mail/OrderMailQueue", () => ({
  OrderMailQueue: (props: { modeTabs?: React.ReactNode }) => (
    <div>
      {props.modeTabs}
      Skrzynka zamówień z maila
    </div>
  ),
}));

vi.mock("@/components/order-mail/useOrderMailPendingCount", () => ({
  useOrderMailPendingCount: () => 3,
}));


const ADMIN = {
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
} as unknown as User;

function signIn(overrides: Partial<User> = {}) {
  useAuthStore.setState({ user: { ...ADMIN, ...overrides }, hydrated: true });
}

describe("ContractsPage — jedna lista (18.11.2026)", () => {
  beforeEach(() => {
    mockReplace.mockReset();
    mockPush.mockReset();
    window.history.replaceState({}, "", "/contracts");
    signIn();
  });

  afterEach(() => {
    cleanup();
    useAuthStore.setState({ user: null, hydrated: true });
  });

  it("pokazuje jedną listę bez trybów i „Zamówienia z maila” z licznikiem", async () => {
    render(<ContractsPage />);

    expect(await screen.findByText("Globalny rejestr")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByRole("tab", { name: /Obsługa kontraktorów/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Zamówienia z maila/ })).toHaveTextContent("3");
    expect(screen.getByLabelText("3 do weryfikacji")).toBeInTheDocument();
  });

  it("przycisk otwiera kolejkę pod ?view=order-mail, a „Wróć do listy kontraktów” wraca", async () => {
    window.history.replaceState({ next: "preserved" }, "", "/contracts?status=draft&page=4");
    render(<ContractsPage />);

    fireEvent.click(await screen.findByRole("button", { name: /Zamówienia z maila/ }));
    await waitFor(() =>
      expect(`${window.location.pathname}${window.location.search}`).toBe("/contracts?view=order-mail"),
    );
    expect(screen.getByText("Skrzynka zamówień z maila")).toBeInTheDocument();
    expect(window.history.state).toEqual({ next: "preserved" });

    fireEvent.click(screen.getByRole("button", { name: /Wróć do listy kontraktów/ }));
    await waitFor(() =>
      expect(`${window.location.pathname}${window.location.search}`).toBe("/contracts"),
    );
    expect(screen.getByText("Globalny rejestr")).toBeInTheDocument();
  });

  it("?view=order-mail z adresu (linki z powiadomień) otwiera kolejkę", async () => {
    window.history.replaceState({}, "", "/contracts?view=order-mail&doc=5");
    render(<ContractsPage />);

    expect(await screen.findByText("Skrzynka zamówień z maila")).toBeInTheDocument();
    expect(screen.queryByText("Globalny rejestr")).toBeNull();
  });

  it.each([
    ["ending", "/contracts?ending=30"],
    ["draft", "/contracts?status=draft&status=ready_for_signature"],
    ["active", "/contracts?status=active&status=ending"],
  ])(
    "dawny adres „Obsługi kontraktorów” (tab=%s) prowadzi na ten sam zbiór listy",
    async (tab, target) => {
      window.history.replaceState(
        {},
        "",
        `/contracts?view=operations&tab=${tab}&contractors_page=3`,
      );
      render(<ContractsPage />);

      await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(target));
      expect(screen.queryByText("Globalny rejestr")).toBeNull();
    },
  );

  it("wybór klienta otwiera jego zakładkę „Konsultanci” (18.11.2026)", async () => {
    render(<ContractsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Wybierz klienta" }));
    expect(mockPush).toHaveBeenCalledWith("/clients/12?tab=konsultanci");
    expect(screen.getByText("Globalny rejestr")).toBeInTheDocument();
  });

  it("dawny rejestr klienta pod ?client= prowadzi do zakładki „Konsultanci”", async () => {
    window.history.replaceState({}, "", "/contracts?client=12&clientName=Bank&register_page=2");
    render(<ContractsPage />);

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/clients/12?tab=konsultanci"));
    expect(screen.queryByText("Globalny rejestr")).toBeNull();
  });

  it("bez podglądu skrzynki zamówień nie ma przycisku", async () => {
    signIn({
      role: "recruiter",
      roles: ["recruiter"],
      effective_action_access: permissionSnapshot(),
      effective_section_access: sectionSnapshot([]),
    });
    render(<ContractsPage />);

    expect(await screen.findByText("Globalny rejestr")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zamówienia z maila/ })).toBeNull();
  });
});
