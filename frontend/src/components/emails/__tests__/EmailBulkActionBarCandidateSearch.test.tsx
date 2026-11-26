import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmailBulkActionBar } from "@/components/emails/EmailBulkActionBar";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/api", () => ({
  candidatesApi: { list: (...args: unknown[]) => mocks.list(...args) },
  microsoft365Api: { bulkAction: vi.fn() },
}));

// 26.11.2026: wyszukanie osoby w trakcie pisania pytało listę w v1, a v1 dla
// dwóch znaków czytało CV, profil i notatki całej bazy bez indeksu (na
// produkcji 90 s z palety ⌘K). Pole „Połącz z kandydatem” pyta tak samo.
describe("EmailBulkActionBar — wyszukiwanie kandydata", () => {
  it("pyta listę w v2 z tekstem dosłownym — dwa znaki nie czytają całej bazy", async () => {
    mocks.list.mockResolvedValue({ data: { items: [] } });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <EmailBulkActionBar selectedIds={[1, 2]} onClear={() => {}} />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Połącz z kandydatem/ }));
    fireEvent.change(
      screen.getByPlaceholderText("Szukaj kandydata po nazwisku, imieniu lub email…"),
      { target: { value: "qa" } },
    );

    await waitFor(() =>
      expect(mocks.list).toHaveBeenCalledWith({
        q: "qa",
        page_size: 10,
        semantics_version: 2,
        text_mode: "literal",
      }),
    );
  });
});
