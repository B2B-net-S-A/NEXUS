import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ acceptProposal: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, skillsAdminApi: { ...actual.skillsAdminApi, ...api } };
});

import { DictionaryHintCallout } from "@/components/champion/DictionaryHintCallout";
import type { DictionaryHint } from "@/lib/dictionary-hints";

const HINT: DictionaryHint = {
  word: "excel",
  kind: "new",
  proposal_id: 11,
  word_count: 4428,
  target: null,
  add_words: [
    { name: "microsoft excel", count: 2665 },
    { name: "ms excel", count: 721 },
  ],
  canonical: "Microsoft Excel",
  category: "tools",
};

function renderHint(canCurate: boolean, rowWords: string[] = ["excel"]) {
  const onAddWords = vi.fn();
  const onKeep = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DictionaryHintCallout
        hint={HINT}
        rowWords={rowWords}
        canCurate={canCurate}
        onAddWords={onAddWords}
        onKeep={onKeep}
      />
    </QueryClientProvider>,
  );
  return { onAddWords, onKeep };
}

describe("DictionaryHintCallout — DL zmienia wiersz, słownik tylko HoR+", () => {
  it("Delivery Lead dopisuje zapisy do wiersza i nie widzi przycisku słownika", async () => {
    const user = userEvent.setup();
    const { onAddWords, onKeep } = renderHint(false);
    expect(screen.queryByRole("button", { name: /Dodaj do słownika/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj zapisy: microsoft excel, ms excel" }));
    expect(onAddWords).toHaveBeenCalledWith(["microsoft excel", "ms excel"]);
    await user.click(screen.getByRole("button", { name: "Zostaw" }));
    expect(onKeep).toHaveBeenCalled();
  });

  it("HoR+ dodaje hasło do słownika przez propozycję, błąd mówi o sobie", async () => {
    const user = userEvent.setup();
    api.acceptProposal.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 409, data: { detail: "Alias „ms excel” należy już do umiejętności X." } },
    });
    renderHint(true);
    await user.click(screen.getByRole("button", { name: "Dodaj do słownika jako „Microsoft Excel”" }));
    expect(api.acceptProposal).toHaveBeenCalledWith(11);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("znika, gdy wiersz ma już wszystkie zapisy, a osoba nie zmienia słownika", () => {
    renderHint(false, ["excel", "microsoft excel", "ms excel"]);
    expect(screen.queryByTestId("dictionary-hint")).not.toBeInTheDocument();
  });
});
