/**
 * Haczyk przed telefonem na karcie rozmowy i teczka przed spotkaniem w „Moim dniu”.
 * Bez haczyka, z wyłączonymi zadaniami bota i przy błędzie zapytania nic się nie pokazuje.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CompanyBriefing, MyDayPrep } from "@/lib/api/sales";

let briefing: { isSuccess: boolean; data?: CompanyBriefing } = { isSuccess: false };

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useCompanyBriefing: () => briefing,
  useCompanyPeople: () => ({ isLoading: false, error: null, isSuccess: true, data: { counts: {}, people: [] }, refetch: vi.fn() }),
}));

import { CallHook } from "../calling/CallHook";
import { MyDayPrepCard } from "../MyDayPrepCard";

const hook = {
  sentence: "Widziałem, że uruchomiliście asystenta w obsłudze klienta.",
  facts: [
    { text: "Firma wdrożyła asystenta AI", url: "https://example.com/ai", published: "2026-10-20" },
    { text: "Zespół IT rośnie o dział danych", url: "javascript:alert(1)", published: "2026-09-02" },
  ],
  generated_at: "2026-11-11T15:00:00Z",
};

const ok = (data: CompanyBriefing) => ({ isSuccess: true, data });

beforeEach(() => {
  briefing = { isSuccess: false };
});

describe("haczyk na karcie rozmowy", () => {
  it("pokazuje zdanie, fakty z linkami i podpis bota", () => {
    briefing = ok({ enabled: true, briefing: null, call_hook: hook });
    render(<CallHook companyId={7} />);
    const section = screen.getByRole("region", { name: "Haczyk do rozmowy" });
    expect(section).toHaveAttribute("data-tour", "sales.calling.hook");
    expect(screen.getByText(hook.sentence)).toBeInTheDocument();
    expect(screen.getByText("Bot · sprawdź źródło")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: /źródło/ });
    // Link spoza http(s) nie staje się odnośnikiem, fakt zostaje.
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.com/ai");
    expect(screen.getByText(/Zespół IT rośnie o dział danych/)).toBeInTheDocument();
  });

  it("bez haczyka, z wyłączonym kanałem i przy błędzie nic nie pokazuje", () => {
    for (const state of [
      ok({ enabled: true, briefing: null, call_hook: null }),
      ok({ enabled: true, briefing: null }),
      ok({ enabled: false, briefing: null, call_hook: hook }),
      { isSuccess: false },
    ]) {
      briefing = state;
      const { container, unmount } = render(<CallHook companyId={7} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });
});

const prep: MyDayPrep = {
  activity_id: 41,
  company: { id: 7, name: "Firma Testowa" },
  subject: "Spotkanie kwalifikujące",
  at: "2026-11-12T09:00:00Z",
  duration_minutes: 60,
  open_opportunities: 1,
  can_create_opportunity: false,
  history: [],
  contacts: [],
};

describe("teczka przed spotkaniem", () => {
  it("karta przygotowania pokazuje punkty z bota przed spotkaniem", () => {
    briefing = ok({
      enabled: true,
      briefing: {
        mode: "meeting_prep",
        generated_at: "2026-11-11T15:00:00Z",
        points: [{ text: "Nowy program cyfryzacji", url: "https://example.com/program", published: "2026-11-02" }],
      },
    });
    const { container } = render(<MyDayPrepCard prep={prep} canEdit />);
    expect(screen.getByText(/Punkty do rozmowy przed spotkaniem/)).toBeInTheDocument();
    expect(screen.getByText(/Nowy program cyfryzacji/)).toBeInTheDocument();
    expect(container.querySelector('[data-tour="sales.my-day.prep-points"]')).not.toBeEmptyDOMElement();
  });

  it("bez punktów kontener zostaje pusty, reszta karty bez zmian", () => {
    const { container } = render(<MyDayPrepCard prep={prep} canEdit />);
    expect(screen.queryByText(/Punkty do rozmowy/)).not.toBeInTheDocument();
    expect(screen.getByText("Firma Testowa")).toBeInTheDocument();
    expect(container.querySelector('[data-tour="sales.my-day.prep-points"]')).toBeEmptyDOMElement();
  });
});
