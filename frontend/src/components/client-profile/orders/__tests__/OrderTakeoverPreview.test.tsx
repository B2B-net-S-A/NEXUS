/**
 * Harness `/preview/order-takeover` jest PUBLICZNY — obiecuje zero zapytań
 * do API i pokazuje stany z ticketu 09.2026 (zastępstwo, zaplanowane).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
    post: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
  },
}));

import OrderTakeoverPreview from "@/app/preview/order-takeover/page";
import { api } from "@/lib/api";

describe("Harness /preview/order-takeover", () => {
  it("pokazuje zastępstwo i zastępstwo zaplanowane bez zapytań", () => {
    render(<OrderTakeoverPreview />);
    expect(screen.getByText("Zastępstwo")).toBeInTheDocument();
    expect(screen.getByText(/Przejęła po: Konrad Odchodzący · 187 MD \(1:1\)/)).toBeInTheDocument();
    expect(screen.getByText("Zaplanowane zastępstwo od 01.11.2026")).toBeInTheDocument();
    expect(screen.getByText("Zastępstwo od 01.11.2026")).toBeInTheDocument();
    expect(vi.mocked(api.get)).not.toHaveBeenCalled();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  });
});
