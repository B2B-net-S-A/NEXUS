import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// Okno Radix w jsdom po odrzuconym zapytaniu zgłasza błąd przy sprzątaniu testu
// (poza kodem ekranu), więc treść okna sprawdzamy bez niego.
vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({ title, children, footer }: { title: string; children: ReactNode; footer: ReactNode }) => (
    <div role="dialog" aria-label={title}>
      {children}
      {footer}
    </div>
  ),
}));

import { RebateCorrectionDialog } from "@/components/clients/invoicing/issue/RebateCorrectionDialog";

describe("szkic korekty rabatu — odmowa serwera", () => {
  it("brak przekroczenia: powód z serwera, XML niedostępny", async () => {
    get.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: "W miesiącu październik 2026 obrót nie przekroczył progu rabatu — korekty nie ma." },
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RebateCorrectionDialog query={{ clientId: 11, year: 2026, month: 10, currency: "PLN" }} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/nie przekroczył progu/)).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Szkic korekty rabatu za październik 2026" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz XML (szkic)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Wystaw korektę" })).toBeDisabled();
  });
});
