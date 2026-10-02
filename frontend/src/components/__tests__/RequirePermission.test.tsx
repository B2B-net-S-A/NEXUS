import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { RequirePermission } from "@/components/RequirePermission";
import { useAuthStore } from "@/store/auth";

function setAuthState(partial: Record<string, unknown>) {
  useAuthStore.setState(partial as never);
}

const SNAPSHOT_NONE = {
  delivery_view: "none",
  clients_edit: "none",
  contracts_orders_edit: "none",
  contract_status: "none",
  b2b_signature_confirmation: "none",
  recruitment_manage: "none",
  amounts_view: "none",
  amounts_edit: "none",
  finance_module: "none",
};

function gate() {
  return render(
    <RequirePermission
      permissions={["contracts_orders_edit"]}
      fallback={<p>Brak uprawnienia</p>}
    >
      <p>Nowy kontrakt</p>
    </RequirePermission>,
  );
}

describe("RequirePermission", () => {
  beforeEach(() => {
    setAuthState({ user: null, token: null, realUser: null, hydrated: false });
  });

  it("przed hydracją nie orzeka — ani dzieci, ani odmowy", () => {
    setAuthState({ user: { role: "admin", roles: ["admin"] }, hydrated: false });
    gate();
    expect(screen.queryByText("Nowy kontrakt")).not.toBeInTheDocument();
    expect(screen.queryByText("Brak uprawnienia")).not.toBeInTheDocument();
  });

  it("decyduje uprawnienie konta, nie rola", () => {
    // Rekruter z nadanym uprawnieniem widzi; Delivery Lead, któremu admin
    // je wyłączył — nie.
    setAuthState({
      user: {
        role: "recruiter",
        roles: ["recruiter"],
        effective_action_access: {
          ...SNAPSHOT_NONE,
          delivery_view: "manage",
          contracts_orders_edit: "manage",
        },
      },
      hydrated: true,
    });
    const granted = gate();
    expect(screen.getByText("Nowy kontrakt")).toBeInTheDocument();
    granted.unmount();

    setAuthState({
      user: {
        role: "delivery_lead",
        roles: ["delivery_lead"],
        effective_action_access: { ...SNAPSHOT_NONE, delivery_view: "manage" },
      },
      hydrated: true,
    });
    gate();
    expect(screen.queryByText("Nowy kontrakt")).not.toBeInTheDocument();
    expect(screen.getByText("Brak uprawnienia")).toBeInTheDocument();
  });

  it("wystarczy jedno z wymienionych uprawnień", () => {
    setAuthState({
      user: {
        role: "finance",
        roles: ["finance"],
        effective_action_access: { ...SNAPSHOT_NONE, amounts_edit: "manage" },
      },
      hydrated: true,
    });
    render(
      <RequirePermission permissions={["contracts_orders_edit", "amounts_edit"]}>
        <p>Edytuj stawki</p>
      </RequirePermission>,
    );
    expect(screen.getByText("Edytuj stawki")).toBeInTheDocument();
  });

  it("profil sprzed wdrożenia liczy uprawnienia z domyślnych ról", () => {
    setAuthState({
      user: { role: "finance", roles: ["finance"] },
      hydrated: true,
    });
    gate();
    expect(screen.getByText("Nowy kontrakt")).toBeInTheDocument();
  });
});
