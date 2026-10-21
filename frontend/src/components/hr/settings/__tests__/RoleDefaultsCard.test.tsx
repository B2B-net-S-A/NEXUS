import type React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RoleDefault } from "@/lib/api/hr-time";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  toast: vi.fn(),
  confirm: vi.fn(async () => true),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, patch: mocks.patch, delete: mocks.del },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

vi.mock("@/components/ui/select", async () => {
  const ReactModule = await import("react");
  const SelectTrigger = (_props: { id?: string; children?: React.ReactNode }) => null;
  const SelectContent = (_props: { children?: React.ReactNode }) => null;
  const SelectItem = (_props: { value: string; children?: React.ReactNode }) => null;
  const SelectValue = (_props: { placeholder?: string }) => null;
  function Select({
    children,
    value,
    onValueChange,
  }: {
    children: React.ReactNode;
    value?: string;
    onValueChange?: (value: string) => void;
  }) {
    const elements = ReactModule.Children.toArray(children).filter(ReactModule.isValidElement);
    const trigger = elements.find((child) => child.type === SelectTrigger) as
      | React.ReactElement<{ id?: string }>
      | undefined;
    const content = elements.find((child) => child.type === SelectContent) as
      | React.ReactElement<{ children?: React.ReactNode }>
      | undefined;
    const items = ReactModule.Children.toArray(content?.props.children).filter(
      ReactModule.isValidElement,
    ) as React.ReactElement<{ value: string; children?: React.ReactNode }>[];
    return (
      <select
        id={trigger?.props.id}
        value={value}
        onChange={(event) => onValueChange?.(event.target.value)}
      >
        {items.map((item) => (
          <option key={item.props.value} value={item.props.value}>
            {item.props.children}
          </option>
        ))}
      </select>
    );
  }
  return { Select, SelectTrigger, SelectContent, SelectItem, SelectValue };
});

import { ROLE_DEFAULT_ROLES, RoleDefaultsCard, roleLabel } from "../RoleDefaultsCard";

const ITEMS: RoleDefault[] = [
  {
    id: 1,
    label: "Rekruter — standard",
    applies_to_role: "recruiter",
    project: null,
    default_description: "Rekrutacje IT",
    is_active: true,
    sort_order: 0,
  },
  {
    id: 2,
    label: "Wszyscy",
    applies_to_role: null,
    project: "Wewnętrzny",
    default_description: "Praca biurowa",
    is_active: false,
    sort_order: 1,
  },
];

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RoleDefaultsCard />
    </QueryClientProvider>,
  );
}

describe("RoleDefaultsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.confirm.mockResolvedValue(true);
    mocks.get.mockResolvedValue({ data: { items: ITEMS } });
    mocks.post.mockResolvedValue({ data: {} });
    mocks.patch.mockResolvedValue({ data: {} });
    mocks.del.mockResolvedValue({});
  });

  it("role to role NEXUSA bez wycofanych", () => {
    expect(ROLE_DEFAULT_ROLES).toContain("employee");
    expect(ROLE_DEFAULT_ROLES).toContain("recruiter");
    for (const retired of ["sourcer", "tac", "user"]) {
      expect(ROLE_DEFAULT_ROLES as readonly string[]).not.toContain(retired);
    }
    expect(roleLabel(null)).toBe("Wszystkie role");
    expect(roleLabel("employee")).toBe("Konsultant/Kontraktor");
  });

  it("lista z rolą, projektem i przełącznikiem aktywności", async () => {
    renderCard();
    expect(await screen.findByText("Rekruter — standard")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Rekruter — standardRekruter");
    expect(screen.getByText("Wszystkie role · Wewnętrzny")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Aktywny: Wszyscy" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("switch", { name: "Aktywny: Wszyscy" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/hr/time/role-defaults/2", { is_active: true }),
    );
  });

  it("dodaje opis dla roli", async () => {
    renderCard();
    await screen.findByText("Rekruter — standard");
    fireEvent.change(screen.getByLabelText("Etykieta"), { target: { value: "Pracownik biura" } });
    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "employee" } });
    fireEvent.change(screen.getByLabelText("Opis"), { target: { value: "Obsługa biura" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj opis" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/time/role-defaults", {
        label: "Pracownik biura",
        default_description: "Obsługa biura",
        applies_to_role: "employee",
        project: null,
        is_active: true,
        sort_order: 2,
      }),
    );
  });

  it("edycja zmienia rolę na wszystkie, usunięcie po potwierdzeniu", async () => {
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj: Rekruter — standard" }));
    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "__all__" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith(
        "/api/hr/time/role-defaults/1",
        expect.objectContaining({ applies_to_role: null, label: "Rekruter — standard" }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Usuń: Wszyscy" }));
    await waitFor(() => expect(mocks.del).toHaveBeenCalledWith("/api/hr/time/role-defaults/2"));
  });

  it("strzałka zmienia kolejność", async () => {
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Przesuń wyżej: Wszyscy" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(2));
    expect(mocks.patch).toHaveBeenCalledWith("/api/hr/time/role-defaults/2", { sort_order: 0 });
    expect(mocks.patch).toHaveBeenCalledWith("/api/hr/time/role-defaults/1", { sort_order: 1 });
  });

  it("awaria odczytu nie wygląda jak brak opisów", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500 } });
    renderCard();
    expect(await screen.findByRole("button", { name: /Spróbuj|Ponów/ })).toBeInTheDocument();
    expect(screen.queryByText(/Brak domyślnych opisów/)).toBeNull();
  });
});
