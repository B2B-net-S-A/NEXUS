import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchMinimumBlock } from "./ReviewBatchMinimumBlock";

const api = vi.hoisted(() => ({
  get: vi.fn(async () => ({
    data: {
      minimum: 50,
      block_enabled: true,
      pilot_user_ids: [] as number[],
      batch_size: 20,
      min_score: 65,
      max_age_days: 7,
      enabled: true,
      recruiters: [
        { id: 7, name: "Rekruter A" },
        { id: 8, name: "Rekruter B" },
      ],
    },
  })),
  put: vi.fn(async () => ({ data: { minimum: 40 } })),
}));
vi.mock("@/lib/api", () => ({ default: api }));

function renderBlock(canEdit: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReviewBatchMinimumBlock canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.get.mockClear();
  api.put.mockClear();
});

describe("ReviewBatchMinimumBlock", () => {
  it("HoR zmienia minimum i widzi potwierdzenie", async () => {
    renderBlock(true);
    const input = await screen.findByLabelText("Minimum decyzji dziennie");
    expect(input).toHaveValue(50);
    fireEvent.change(input, { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz minimum" }));
    expect(await screen.findByText("Zapisano minimum porcji dnia.")).toBeInTheDocument();
    expect(api.put).toHaveBeenCalledWith("/api/review-batch/settings", {
      minimum: 40,
      block_enabled: true,
      pilot_user_ids: [],
    });
  });

  it("bez prawa zapisu pole jest wyłączone, a zła liczba blokuje zapis", async () => {
    const { unmount } = renderBlock(false);
    expect(await screen.findByLabelText("Minimum decyzji dziennie")).toBeDisabled();
    unmount();
    renderBlock(true);
    const input = await screen.findByLabelText("Minimum decyzji dziennie");
    fireEvent.change(input, { target: { value: "0" } });
    expect(screen.getByText("Podaj liczbę od 1 do 300.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz minimum" })).toBeDisabled();
  });

  it("HoR wyłącza blokadę bez wdrożenia", async () => {
    renderBlock(true);
    const toggle = await screen.findByRole("switch");
    expect(toggle).toHaveAttribute("data-state", "checked");
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/review-batch/settings", {
        minimum: 50,
        block_enabled: false,
        pilot_user_ids: [],
      }),
    );
    expect(
      await screen.findByText("Blokada wyszukiwania wyłączona — porcja zostaje, wyszukiwanie działa."),
    ).toBeInTheDocument();
  });

  it("zaznaczenie osoby zawęża blokadę do pilota", async () => {
    renderBlock(true);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Pilot: Rekruter B" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/review-batch/settings", {
        minimum: 50,
        block_enabled: true,
        pilot_user_ids: [8],
      }),
    );
    expect(await screen.findByText("Blokada dotyczy 1 os. z pilota.")).toBeInTheDocument();
  });

  it("bez prawa zapisu nie ma listy pilota, a przełącznik jest wyłączony", async () => {
    renderBlock(false);
    expect(await screen.findByRole("switch")).toBeDisabled();
    expect(screen.queryByText("Pilot")).not.toBeInTheDocument();
  });
});
