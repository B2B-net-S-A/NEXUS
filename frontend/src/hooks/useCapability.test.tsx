import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  useAnyCapability,
  useCapabilities,
  useCapability,
} from "@/hooks/useCapability";
import { CAPABILITY_ROLES } from "@/lib/capabilities";
import { useAuthStore, type User, type UserRole } from "@/store/auth";
import {
  accessSnapshot,
  type AccessSnapshotOptions,
} from "@/test/fixtures/access-snapshot";

const admin = {
  id: 1,
  name: "Admin",
  email: "admin@example.com",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: {
    sourcing: "write",
    pipeline: "write",
    delivery: "write",
    insights: "write",
    finance: "write",
    system_admin: "write",
  },
} satisfies User;

/** Konto w kształcie `GET /api/auth/me`: uprawnienia i wynikające z nich sekcje. */
function account(role: UserRole, options: AccessSnapshotOptions = {}): User {
  return {
    id: 7,
    name: role,
    email: `${role}@example.com`,
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    ...accessSnapshot(role, options),
  };
}

function login(user: User, realUser: User | null = null) {
  useAuthStore.setState({ user, realUser, token: "token", hydrated: true });
}

beforeEach(() => {
  login(admin);
});

describe("useCapability during impersonation", () => {
  it("keeps read navigation but suppresses mutating actions", () => {
    useAuthStore.setState({
      realUser: admin,
      user: { ...admin, id: 2 },
    });

    expect(renderHook(() => useCapability("nav.clients")).result.current).toBe(
      true,
    );
    expect(
      renderHook(() => useCapability("client.create")).result.current,
    ).toBe(false);
  });

  it("uprawnienie podglądanej osoby nie odblokowuje zapisu w „podglądzie jako”", () => {
    login(account("recruiter", { grant: ["clients_edit"] }), admin);

    expect(renderHook(() => useCapability("client.create")).result.current).toBe(false);
    expect(renderHook(() => useAnyCapability("client.create", "contact.create")).result.current).toBe(
      false,
    );
    expect(renderHook(() => useCapabilities()).result.current["client.update"]).toBe(false);
    // Nawigacja (odczyt) zostaje — admin widzi to, co widzi podglądana osoba.
    expect(renderHook(() => useCapability("nav.clients")).result.current).toBe(true);
  });
});

describe("useCapability — capability z uprawnienia", () => {
  it("rekruter z nadanym „Klienci: dodawanie i edycja” dostaje akcje klienta", () => {
    login(account("recruiter", { grant: ["clients_edit"] }));

    expect(renderHook(() => useCapability("client.create")).result.current).toBe(true);
    expect(renderHook(() => useCapability("contract.create")).result.current).toBe(false);
    expect(renderHook(() => useAnyCapability("job.create", "contact.create")).result.current).toBe(
      true,
    );
    const all = renderHook(() => useCapabilities()).result.current;
    expect(all["client.update"]).toBe(true);
    expect(all["nav.clients"]).toBe(true);
    expect(all["nav.finance"]).toBe(false);
  });

  it("Delivery Lead z wyłączonym uprawnieniem ich nie ma", () => {
    login(account("delivery_lead", { revoke: ["clients_edit"] }));

    expect(renderHook(() => useCapability("client.create")).result.current).toBe(false);
    expect(renderHook(() => useCapability("contract.create")).result.current).toBe(true);
  });

  it("useCapabilities zwraca komplet rejestru — także wpisy bez listy ról", () => {
    login(account("finance"));

    const all = renderHook(() => useCapabilities()).result.current;
    expect(Object.keys(all).sort()).toEqual(Object.keys(CAPABILITY_ROLES).sort());
    expect(all["nav.finance"]).toBe(true);
    expect(all["contract.create"]).toBe(true);
    expect(all["client.create"]).toBe(false);
  });
});
