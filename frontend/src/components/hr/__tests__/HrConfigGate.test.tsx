import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hrConfig } from "@/app/preview/hr-fixtures";
import type { HrConfig } from "@/lib/api/hr";
import { useAuthStore, type User } from "@/store/auth";

import { HrConfigGate } from "../HrConfigGate";

const state = vi.hoisted(() => ({ data: undefined as HrConfig | undefined }));
vi.mock("@/lib/api/hr", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr")>()),
  useHrConfig: () => ({
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    data: state.data,
    refetch: vi.fn(),
  }),
}));

describe("HrConfigGate — główny wyłącznik programu (18.10.2026)", () => {
  beforeEach(() => {
    useAuthStore.setState({
      hydrated: true,
      user: { id: 1, role: "admin", roles: ["admin"] } as unknown as User,
    });
  });

  it("wyłączony program wygląda jak nieistniejąca strona, także dla admina", () => {
    state.data = { ...hrConfig({ is_admin: true }), program: false };
    render(<HrConfigGate>{() => <p>Ekran modułu</p>}</HrConfigGate>);
    expect(screen.queryByText("Ekran modułu")).toBeNull();
    expect(screen.getByText("Nie znaleziono")).toBeInTheDocument();
  });

  it("włączony program pokazuje ekran", () => {
    state.data = hrConfig({ is_admin: true });
    render(<HrConfigGate>{() => <p>Ekran modułu</p>}</HrConfigGate>);
    expect(screen.getByText("Ekran modułu")).toBeInTheDocument();
  });
});
