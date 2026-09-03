import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useCapability } from "@/hooks/useCapability";
import { useAuthStore, type User } from "@/store/auth";

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

beforeEach(() => {
  useAuthStore.setState({
    user: admin,
    realUser: null,
    token: "token",
    hydrated: true,
  });
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
});
