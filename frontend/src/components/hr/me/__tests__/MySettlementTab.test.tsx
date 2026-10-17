/**
 * „Mój czas → Rozliczenie” (etap 4, M1, M2): dokument według formy.
 * B2B — „Do faktury” z pozycjami, „Kopiuj pozycje” i faktura z KSeF;
 * zlecenie — rozliczenie z potwierdzenia godzin z PDF-em, bez kopiowania;
 * awaria to komunikat z ponowieniem, nie pusty rok. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn() } }));

import { ewaSettlements, olaSettlements, settlementScene } from "@/app/preview/hr-settlements/fixtures";
import { ToastProvider } from "@/components/Toast";

import { MySettlementTab, MySettlementView } from "../MySettlementTab";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  mocks.get.mockReset();
  vi.restoreAllMocks();
});

describe("MySettlementView", () => {
  it("B2B: kroki, pozycje do faktury, kopiowanie i faktura z KSeF", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const data = olaSettlements(settlementScene());
    wrap(<MySettlementView data={data} />);

    const steps = screen.getByRole("list", { name: "Kroki rozliczenia" });
    expect(within(steps).getByText("Raport potwierdzony")).toBeInTheDocument();
    expect(within(steps).getByText(/^Do zapłaty$/)).toBeInTheDocument();
    expect(screen.getByText(/Płatne dni przerwy z umowy/)).toBeInTheDocument();
    expect(screen.getByText("Razem netto")).toBeInTheDocument();
    expect(screen.getByText(/VAT dolicza Twój program/)).toBeInTheDocument();
    expect(screen.getByText("FV 10/2026")).toBeInTheDocument();
    expect(screen.getAllByText(/•• 4521 · z białej listy VAT/).length).toBeGreaterThan(0);
    expect(screen.getByText("Poprzednie miesiące")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Kopiuj pozycje/ }));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toMatch(/Razem netto\t17\s160,00\szł$/);
    expect(await screen.findByText("Pozycje skopiowane")).toBeInTheDocument();
  });

  it("zlecenie: brutto z potwierdzenia godzin, PDF zamiast kopiowania", () => {
    wrap(<MySettlementView data={ewaSettlements(settlementScene())} />);
    expect(screen.getByText("Wynagrodzenie brutto")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz PDF/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Kopiuj pozycje/ })).toBeNull();
    expect(screen.getByText(/osobny rachunek nie jest potrzebny/)).toBeInTheDocument();
    expect(screen.queryByText(/Faktura z KSeF/)).toBeNull();
  });

  it("rok bez miesięcy mówi zdaniem, kiedy coś się pojawi", () => {
    wrap(
      <MySettlementView
        data={{ ...olaSettlements(settlementScene()), months: [] }}
      />,
    );
    expect(screen.getByText(/nie ma jeszcze miesięcy do rozliczenia/)).toBeInTheDocument();
  });
});

describe("MySettlementTab", () => {
  it("awaria zapytania to komunikat z ponowieniem, nie pusty rok", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 500 } }));
    wrap(<MySettlementTab />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wczytać rozliczenia/);
    expect(screen.queryByText(/nie ma jeszcze miesięcy/)).toBeNull();
  });

  it("wyłączony moduł (404) mówi, że rozliczeń jeszcze nie ma", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 404 } }));
    wrap(<MySettlementTab />);
    expect(await screen.findByText(/Rozliczenia nie są jeszcze włączone/)).toBeInTheDocument();
  });
});
