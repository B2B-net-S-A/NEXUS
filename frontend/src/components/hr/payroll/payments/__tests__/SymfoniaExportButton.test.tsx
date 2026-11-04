import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SymfoniaPreview } from "@/lib/api/hr-payments";

const download = vi.fn(async (..._args: unknown[]) => undefined);
const previewState: { value: Record<string, unknown>; enabled: boolean[] } = {
  value: {},
  enabled: [],
};

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api/hr", () => ({ downloadHrFile: (...args: unknown[]) => download(...args) }));
vi.mock("@/lib/api/hr-payments", () => ({
  paymentPaths: {
    symfoniaZip: (year: number, month: number) =>
      `/api/hr/payments/symfonia/${year}/${month}/package.zip`,
  },
  useSymfoniaPreview: (_year: number, _month: number, enabled: boolean) => {
    previewState.enabled.push(enabled);
    return previewState.value;
  },
}));

import { SymfoniaExportButton } from "../SymfoniaExportButton";

const preview: SymfoniaPreview = {
  year: 2026,
  month: 9,
  label: "wrzesień 2026",
  includes_events: true,
  includes_amounts: true,
  files: [
    { name: "zdarzenia_2026-09.xml", rows: 3 },
    { name: "premie_2026-09.xlsx", rows: 1 },
    { name: "zestawienie_2026-09.pdf", rows: null },
  ],
  people: 4,
  todo: ["Borys Wzorcowy: brak identyfikatora z Symfonii w danych do rozliczeń — osoba nie trafiła do plików."],
  notes: ["Zwolnienia lekarskie (L4) nie są w pliku — Symfonia pobiera e-ZLA z PUE ZUS."],
  totals: { "Premie · Premia sprzedażowa": "500.00" },
};

beforeEach(() => {
  download.mockClear();
  previewState.enabled = [];
  previewState.value = {
    data: preview,
    isLoading: false,
    isError: false,
    error: null,
    isSuccess: true,
  };
});

describe("Eksport do Symfonii", () => {
  it("otwarty miesiąc: przycisk nieaktywny z wyjaśnieniem, podgląd nie pyta serwera", () => {
    render(<SymfoniaExportButton year={2026} month={9} closed={false} />);
    const button = screen.getByRole("button", { name: /Eksport do Symfonii/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", expect.stringMatching(/zamkniętego miesiąca/));
    expect(previewState.enabled.every((value) => value === false)).toBe(true);
  });

  it("podgląd: pliki, sumy, lista do zrobienia; pobranie ZIP", async () => {
    render(<SymfoniaExportButton year={2026} month={9} closed />);
    fireEvent.click(screen.getByRole("button", { name: /Eksport do Symfonii/ }));
    expect(screen.getByText("Paczka dla Symfonii · wrzesień 2026")).toBeInTheDocument();
    expect(screen.getByText("Nieobecności i nadgodziny (XML)")).toBeInTheDocument();
    expect(screen.getByText("3 wierszy")).toBeInTheDocument();
    expect(screen.getByText(/500,00\szł/)).toBeInTheDocument();
    expect(screen.getByText("Do zrobienia ręcznie (1)")).toBeInTheDocument();
    expect(screen.getByText(/Borys Wzorcowy: brak identyfikatora/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pobierz paczkę (ZIP)" }));
    await vi.waitFor(() =>
      expect(download).toHaveBeenCalledWith(
        "/api/hr/payments/symfonia/2026/9/package.zip",
        "symfonia-2026-09.zip",
      ),
    );
  });

  it("błąd podglądu (np. 409) pokazuje zdanie serwera i blokuje pobranie", () => {
    previewState.value = {
      data: undefined,
      isLoading: false,
      isError: true,
      isSuccess: false,
      error: {
        response: {
          status: 409,
          data: {
            detail: {
              code: "period_open",
              message: "Paczka dla Symfonii powstaje z zamkniętego miesiąca płac.",
            },
          },
        },
      },
    };
    render(<SymfoniaExportButton year={2026} month={9} closed />);
    fireEvent.click(screen.getByRole("button", { name: /Eksport do Symfonii/ }));
    expect(screen.getByRole("alert")).toHaveTextContent(/zamkniętego miesiąca/);
    expect(screen.getByRole("button", { name: "Pobierz paczkę (ZIP)" })).toBeDisabled();
  });
});
