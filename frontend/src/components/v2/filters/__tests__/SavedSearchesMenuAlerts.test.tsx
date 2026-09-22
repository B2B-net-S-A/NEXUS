import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const listMock = vi.fn();
const createMock = vi.fn();
const markViewedMock = vi.fn();

vi.mock("@/lib/api", () => ({
  savedSearchesApi: {
    list: (...a: unknown[]) => listMock(...a),
    update: vi.fn(),
    create: (...a: unknown[]) => createMock(...a),
    delete: vi.fn(),
    markViewed: (...a: unknown[]) => markViewedMock(...a),
  },
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: { id: number } }) => unknown) => sel({ user: { id: 7 } }),
}));

import { SavedSearchesMenu } from "../SavedSearchesMenu";

const own = {
  id: 21,
  user_id: 7,
  name: "Java Kraków",
  entity: "candidates",
  shared: false,
  description: null,
  notify_new_matches: true,
  requires_reapproval: false,
  unseen_count: 2,
  last_viewed_at: "2026-09-20T10:00:00Z",
  created_at: null,
  updated_at: null,
  filters: { version: 2, qs: "q_all=java", api: { q_all: ["java"] } },
};

function renderMenu(onApply = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SavedSearchesMenu currentQs="q_all=java" onApply={onApply} />
    </QueryClientProvider>,
  );
  return onApply;
}

describe("SavedSearchesMenu — powiadomienia o nowych pasujących osobach", () => {
  beforeEach(() => {
    listMock.mockReset().mockResolvedValue({ data: [own] });
    createMock.mockReset().mockResolvedValue({ data: own });
    markViewedMock.mockReset().mockResolvedValue({
      data: { previous_viewed_at: "2026-09-20T10:00:00Z", new_candidate_ids: [5, 9] },
    });
  });

  it("nowy zapis ma dzwonek włączony domyślnie", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    const checkbox = await screen.findByRole("checkbox", { name: /Powiadamiaj, gdy ktoś zacznie pasować/ });
    expect(checkbox).toBeChecked();
    await user.type(screen.getByPlaceholderText("Nazwa nowego zapisu…"), "Java Kraków{Enter}");
    await waitFor(() => expect(createMock).toHaveBeenCalled());
    expect(createMock.mock.calls[0][0]).toMatchObject({ notify_new_matches: true });
  });

  it("otwarcie zapisu przekazuje osoby, które weszły do wyniku", async () => {
    const user = userEvent.setup();
    const onApply = renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    await user.click(await screen.findByTitle("Java Kraków"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(onApply.mock.calls[0][3]).toEqual([5, 9]);
  });
});
