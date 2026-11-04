import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const listMock = vi.fn();
const updateMock = vi.fn();
const markViewedMock = vi.fn();

vi.mock("@/lib/api", () => ({
  savedSearchesApi: {
    list: (...a: unknown[]) => listMock(...a),
    update: (...a: unknown[]) => updateMock(...a),
    create: vi.fn(),
    delete: vi.fn(),
    markViewed: (...a: unknown[]) => markViewedMock(...a),
  },
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: { id: number } }) => unknown) => sel({ user: { id: 7 } }),
}));

import { SavedSearchesMenu } from "../SavedSearchesMenu";
import { decodeFilters } from "@/lib/url-filters";

/**
 * Zapis z dawnej wyszukiwarki ręcznej (kształt z produkcji, 25.09.2026).
 * Lista pokazywała na nim natywny `alert()` odsyłający do „Wyszukaj
 * manualnie” rekrutacji — ekranu, którego od #1815 nie ma — a alert
 * zamrażał kartę przeglądarki.
 */
const legacy = {
  id: 3,
  user_id: 7,
  name: "Tester manualny/automatyczny - doświadczenie bankowe",
  entity: "candidates",
  shared: true,
  description: null,
  notify_new_matches: false,
  requires_reapproval: false,
  unseen_count: 0,
  last_viewed_at: null,
  created_at: null,
  updated_at: null,
  filters: {
    q_all: [],
    q_none: [],
    skills_any: ["Selenium", "Postman"],
    skills_must: ["Testing"],
    skills_none: [],
    q_any_groups: [["bank", "bankowość", "finanse", "sektor finansowy"]],
    location_cities: [],
    experience_years_max: 6,
    experience_years_min: 2,
  },
};

const unknown = { ...legacy, id: 4, name: "Stary zapis", filters: { foo: 1 } };

function renderMenu(onApply = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SavedSearchesMenu currentQs="" onApply={onApply} />
    </QueryClientProvider>,
  );
  return onApply;
}

let alertSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  listMock.mockReset().mockResolvedValue({ data: [legacy, unknown] });
  updateMock.mockReset();
  markViewedMock.mockReset().mockResolvedValue({
    data: { previous_viewed_at: null, new_candidate_ids: [] },
  });
  alertSpy = vi.spyOn(window, "alert").mockImplementation(() => undefined);
});

afterEach(() => {
  alertSpy.mockRestore();
});

describe("SavedSearchesMenu — zapisy z dawnej wyszukiwarki ręcznej", () => {
  it("otwiera zapis na liście jako wiersze wymagań, bez natywnego okna", async () => {
    const user = userEvent.setup();
    const onApply = renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    await user.click(await screen.findByTitle(legacy.name));

    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(alertSpy).not.toHaveBeenCalled();
    const [qs, id] = onApply.mock.calls[0];
    expect(id).toBe(3);
    const decoded = decodeFilters(new URLSearchParams(qs));
    expect(decoded.qAny).toEqual([["bank", "bankowość", "finanse", "sektor finansowy"]]);
    expect(decoded.skillsPreferred).toEqual(["Testing", "Selenium", "Postman"]);
    expect(decoded.experienceMin).toBe(2);
    expect(decoded.experienceMax).toBe(6);
  });

  it("zapis w nieznanym formacie zostaje w menu z wyjaśnieniem, bez natywnego okna", async () => {
    const user = userEvent.setup();
    const onApply = renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    await user.click(await screen.findByTitle("Stary zapis"));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Zapis „Stary zapis” ma nieobsługiwany format — nie został otwarty.",
    );
    expect(onApply).not.toHaveBeenCalled();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("dzwonek na starym zapisie niczego nie zapisuje i mówi, co zrobić", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    await user.click(await screen.findByRole("button", { name: `Przełącz alert dla ${legacy.name}` }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "otwórz go i zapisz ponownie",
    );
    expect(updateMock).not.toHaveBeenCalled();
    expect(alertSpy).not.toHaveBeenCalled();
  });
});
