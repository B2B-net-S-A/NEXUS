import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ left: 4 }));

vi.mock("next/navigation", () => ({ usePathname: () => "/jobs" }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: { role: string } }) => unknown) => sel({ user: { role: "recruiter" } }),
}));
vi.mock("@/lib/novelties/api", () => ({
  useStartStatus: () => ({ enforced: false, poligon: { luki: { due: "2026-11-23" } } }),
}));
vi.mock("@/lib/novelties/logic", () => ({
  lukiLeft: () => state.left,
  formatLukiDue: () => "pn 23.11",
}));

import { PoligonLukiNotice } from "../PoligonLukiNotice";

describe("PoligonLukiNotice — odmiana liczby ćwiczeń", () => {
  beforeEach(() => {
    state.left = 4;
  });

  it.each([
    [1, "Poligon: 1 ćwiczenie"],
    [4, "Poligon: 4 ćwiczenia"],
    [5, "Poligon: 5 ćwiczeń"],
    [12, "Poligon: 12 ćwiczeń"],
  ])("%i → %s", (left, text) => {
    state.left = left;
    render(<PoligonLukiNotice />);
    expect(screen.getByRole("status")).toHaveTextContent(text);
  });
});
