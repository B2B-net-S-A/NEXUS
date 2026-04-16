import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SavedSearchPicker } from "@/components/SavedSearchPicker";

// Mock the API module before the component is evaluated
vi.mock("@/lib/api", () => ({
  savedSearchesApi: {
    list: vi.fn().mockResolvedValue({ data: [] }),
    create: vi.fn().mockResolvedValue({
      data: {
        id: 1,
        user_id: 1,
        name: "Senior Frontend",
        entity: "candidate",
        filters: {},
        shared: false,
        description: null,
        created_at: null,
        updated_at: null,
      },
    }),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("SavedSearchPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders Filtry button", async () => {
    render(
      <SavedSearchPicker
        entity="candidate"
        currentFilters={{}}
        onApply={() => {}}
      />
    );
    expect(await screen.findByText(/Filtry/)).toBeInTheDocument();
  });

  it("opens dropdown on click and shows 'brak zapisanych'", async () => {
    const user = userEvent.setup();
    render(
      <SavedSearchPicker
        entity="candidate"
        currentFilters={{}}
        onApply={() => {}}
      />
    );
    const toggle = await screen.findByTestId("saved-searches-toggle");
    await user.click(toggle);
    await waitFor(() => {
      expect(screen.getByText(/Brak zapisanych filtr/i)).toBeInTheDocument();
    });
  });
});
