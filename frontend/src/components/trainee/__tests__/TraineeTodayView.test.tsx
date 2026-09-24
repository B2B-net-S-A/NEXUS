import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PREVIEW_NOW,
  applyPreviewCall,
  previewDoneToday,
  previewToday,
} from "@/components/trainee/preview-fixtures";
import { TraineeTodayView } from "@/components/trainee/TraineeTodayView";
import { traineeApi, traineeKeys, type TraineeToday } from "@/lib/api/trainee";

const REAL = { ...traineeApi };

function renderView(today: TraineeToday | null, props: Parameters<typeof TraineeTodayView>[0] = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  if (today) client.setQueryData(traineeKeys.today(), today);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<TraineeTodayView now={PREVIEW_NOW} traineeName="Ola Test" {...props} />, { wrapper });
}

beforeEach(() => {
  let state = previewToday();
  Object.assign(traineeApi, {
    today: vi.fn(async () => state),
    saveCall: vi.fn(async (itemId: number, body: Parameters<typeof traineeApi.saveCall>[1]) => {
      const next = applyPreviewCall(state, itemId, body);
      state = next.today;
      return next.response;
    }),
    saveOutcome: vi.fn(),
  });
});

afterEach(() => {
  Object.assign(traineeApi, REAL);
});

describe("TraineeTodayView", () => {
  it("awaria listy to błąd z ponowieniem, nigdy pusta lista", async () => {
    traineeApi.today = vi.fn(async () => {
      throw new Error("500");
    });
    renderView(null);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać listy telefonów");
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText("Nikt nie czeka na telefon.")).not.toBeInTheDocument();
  });

  it("dzień wolny ma własny komunikat", () => {
    renderView({ ...previewToday(), status: "not_workday", items: [] });
    expect(screen.getByText("Dziś nie ma listy telefonów")).toBeInTheDocument();
  });

  it("dzień zaliczony pokazuje ekran końca dnia i pozwala wrócić do zamkniętych", () => {
    renderView(previewDoneToday());
    expect(screen.getByRole("heading", { name: "Dzień zaliczony" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Wróć do listy/ }));
    expect(screen.getByRole("button", { name: /Zamknięte · 70/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("bez odpowiedzi o B2B rozmowy nie da się zapisać", () => {
    renderView(previewToday());
    fireEvent.click(screen.getByRole("button", { name: "Zapisz rozmowę" }));
    expect(screen.getByText(/Zaznacz, czy pracuje na B2B/)).toBeInTheDocument();
    expect(traineeApi.saveCall).not.toHaveBeenCalled();
  });

  it("„Nie, tylko etat”: czerwona informacja, reszta formularza znika", () => {
    renderView(previewToday());
    const card = screen.getByRole("region", { name: "Rozmowa" });
    expect(within(card).getByLabelText("Minimalna stawka B2B netto")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Nie, tylko etat" }));
    expect(within(card).getByRole("button", { name: "Nie, tylko etat" })).toHaveAttribute("aria-pressed", "true");
    expect(within(card).getByText(/wypadnie z list telefonów i z wyszukiwarki AI/)).toBeInTheDocument();
    expect(within(card).queryByLabelText("Minimalna stawka B2B netto")).not.toBeInTheDocument();
    expect(within(card).queryByText("Praca i biuro")).not.toBeInTheDocument();
  });

  it("zapis rozmowy wysyła ciało z kontraktu, pokazuje status i przechodzi do następnej osoby", async () => {
    renderView(previewToday());
    const card = screen.getByRole("region", { name: "Rozmowa" });
    expect(within(card).getByRole("heading", { name: "Tomasz Zieliński" })).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Tak, już na B2B" }));
    fireEvent.change(within(card).getByLabelText("Minimalna stawka B2B netto"), { target: { value: "145" } });
    fireEvent.click(within(card).getByRole("button", { name: "Hybrydowo" }));
    fireEvent.click(within(card).getByRole("button", { name: "Zapisz rozmowę" }));

    await waitFor(() => expect(traineeApi.saveCall).toHaveBeenCalledTimes(1));
    expect(traineeApi.saveCall).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        b2b_willingness: "b2b",
        min_rate: { value: 145, unit: "hour" },
        remote_modes: ["hybrid"],
      }),
    );
    expect(await screen.findByText(/Zapisano w profilu: Tomasz Zieliński/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Rozmowa" })).getByRole("heading", { name: "Magdalena Kowal" }),
    ).toBeInTheDocument();
  });
});
