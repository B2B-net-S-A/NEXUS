import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchMinimumBlock } from "./ReviewBatchMinimumBlock";

const api = vi.hoisted(() => ({
  get: vi.fn(async () => ({ data: { minimum: 50, batch_size: 20, min_score: 65, enabled: true } })),
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
    expect(api.put).toHaveBeenCalledWith("/api/review-batch/settings", { minimum: 40 });
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
});
