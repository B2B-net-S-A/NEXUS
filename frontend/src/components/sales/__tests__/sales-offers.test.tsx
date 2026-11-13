/**
 * Sprzedaż → Oferty: sekcje „W toku” i „Do decyzji”, przyciski wierszy i okna decyzji.
 * Sekcje i liczniki przychodzą z API, więc test pilnuje, że ekran ich nie przelicza
 * i że awaria nie wygląda jak pusta lista.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OfferRow, Offers, OpportunityEvent, Pipeline, Stage } from "@/lib/api/sales";

const offersQuery = vi.fn();
const complete = vi.fn();
const takeOver = vi.fn();
const update = vi.fn();
const move = vi.fn();
const createActivity = vi.fn();
const replaceUrl = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
let canEdit = true;
let pipelinesData: Pipeline[] | undefined;

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({ mutate, isPending: false, variables: undefined });

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useOffers: (filters: unknown) => offersQuery(filters),
  usePipelines: () => ({ data: pipelinesData, isSuccess: pipelinesData !== undefined }),
  useCompleteActivity: () => mutation(complete),
  useTakeOverOpportunity: () => mutation(takeOver),
  useUpdateOpportunity: () => mutation(update),
  useMoveOpportunity: () => mutation(move),
  useCreateActivity: () => mutation(createActivity),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl }) }));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number } }) => unknown) => selector({ user: { id: 1 } }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    id,
    value,
    onValueChange,
    options,
  }: {
    id?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: readonly { value: string; label: string }[];
  }) => (
    <select id={id} value={value} onChange={(event) => onValueChange(event.target.value)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

import { plusDays } from "../CallLogDialogs";
import { OffersView } from "../OffersView";
import { describeEvent } from "../OpportunityHistory";
import { lostStages, offerStepText, scopeLabel, sectionHint, stageNote } from "../offers";

const stage = (id: number, key: string, name: string, outcome: Stage["outcome"]): Stage => ({
  id,
  key,
  name,
  position: id,
  probability: 0,
  outcome,
  qualifies: false,
  color: null,
});

const PIPELINES = [
  {
    id: 1,
    key: "sales",
    name: "Sprzedaż",
    is_default: true,
    stages: [
      stage(1, "lead", "Lead", "open"),
      stage(4, "offer-sent", "Oferta wysłana", "open"),
      stage(5, "not-qualified", "Niezakwalifikowany", "lost"),
      stage(7, "lost", "Przegrana", "lost"),
    ],
  },
  {
    id: 2,
    key: "atlas-it-factories",
    name: "Fabryki IT",
    is_default: false,
    stages: [stage(21, "itf-first-contact", "Pierwszy kontakt", "open"), stage(29, "itf-lost", "Przegrane", "lost")],
  },
] as unknown as Pipeline[];

function offer(overrides: Partial<OfferRow> = {}): OfferRow {
  return {
    id: 11,
    title: "Zespół analityków",
    company: { id: 3, name: "Firma Testowa" },
    pipeline_id: 1,
    pipeline_name: "Sprzedaż",
    stage: { id: 4, key: "offer-sent", name: "Oferta wysłana" },
    is_offer: true,
    owner: { id: 1, name: "Anna Przykładowa" },
    owner_in_sales: true,
    mrr_value: "20000.00",
    currency: "PLN",
    idle_since: "2026-11-01T10:00:00Z",
    idle_days: 9,
    expected_close_date: "2026-12-15",
    close_overdue: false,
    keep_open_until: null,
    postponed: false,
    section: "in_progress",
    reason: null,
    step: { activity_id: 91, kind: "task", at: "2026-11-13T08:00:00Z", subject: "Potwierdzić odbiór oferty", overdue: false },
    bot_points: null,
    ...overrides,
  };
}

const STALE = offer({
  id: 12,
  title: "Platforma danych",
  company: { id: 4, name: "Druga Firma" },
  mrr_value: "64000.00",
  idle_days: 90,
  expected_close_date: "2026-08-31",
  close_overdue: true,
  section: "to_decide",
  reason: "idle",
  step: null,
});

const ORPHAN = offer({
  id: 13,
  title: "Pierwsza rozmowa",
  company: { id: 5, name: "Trzecia Firma" },
  pipeline_id: 2,
  pipeline_name: "Fabryki IT",
  stage: { id: 21, key: "itf-first-contact", name: "Pierwszy kontakt" },
  is_offer: false,
  owner: { id: 9, name: "Jan Dawny" },
  owner_in_sales: false,
  mrr_value: null,
  idle_days: 17,
  expected_close_date: null,
  section: "to_decide",
  reason: "owner_left",
  step: null,
});

function payload(items: OfferRow[], overrides: Partial<Offers> = {}): Offers {
  const section = (name: OfferRow["section"]) => {
    const rows = items.filter((item) => item.section === name);
    return {
      count: rows.length,
      mrr: rows.reduce((sum, item) => sum + Number(item.mrr_value ?? 0), 0).toFixed(2),
    };
  };
  const totals = { in_progress: section("in_progress"), to_decide: section("to_decide") };
  return {
    scope: "all",
    items,
    totals: { mine: totals, unowned: { in_progress: { count: 0, mrr: "0" }, to_decide: { count: 1, mrr: "0" } }, all: totals },
    ...overrides,
  };
}

const ok = (data: Offers) => ({ data, isLoading: false, error: null, isSuccess: true, refetch: vi.fn() });

beforeEach(() => {
  vi.clearAllMocks();
  canEdit = true;
  pipelinesData = PIPELINES;
  offersQuery.mockReturnValue(ok(payload([offer(), STALE, ORPHAN])));
});

function rowOf(company: string): HTMLElement {
  const row = screen.getByText(company).closest("tr");
  if (!row) throw new Error(`Brak wiersza: ${company}`);
  return row;
}

describe("podpisy zakładki Oferty", () => {
  it("licznik zakresu sumuje obie sekcje, a przed odpowiedzią nie pokazuje zera", () => {
    const { totals } = payload([offer(), STALE, ORPHAN]);
    expect(scopeLabel("all", totals)).toBe("Wszystkie 3");
    expect(scopeLabel("unowned", totals)).toBe("Bez opiekuna 1");
    expect(scopeLabel("mine", undefined)).toBe("Moje");
  });

  it("nagłówek sekcji podaje pozycje i MRR, a bez kwot same pozycje", () => {
    // Intl rozdziela tysiące twardą spacją.
    expect(sectionHint({ count: 2, mrr: "64300.00" }).replace(/\s/g, " ")).toBe("2 pozycje · 64 300 zł MRR");
    expect(sectionHint({ count: 5, mrr: "0" })).toBe("5 pozycji");
    expect(sectionHint({ count: 1, mrr: "0.00" })).toBe("1 pozycja");
  });

  it("krok ma temat i dzień, a spotkanie bez tematu nazwę rodzaju", () => {
    expect(offerStepText(offer().step!)).toBe("13.11 · Potwierdzić odbiór oferty");
    expect(offerStepText({ activity_id: null, kind: "meeting", at: "2026-11-20T09:00:00Z", subject: null, overdue: false })).toBe(
      "20.11 · Spotkanie",
    );
  });

  it("etap widać tylko przy pozycji, która nie jest ofertą z głównego lejka", () => {
    expect(stageNote(offer(), 1)).toBeNull();
    expect(stageNote(offer({ is_offer: false, stage: { id: 1, key: "lead", name: "Lead" } }), 1)).toBe("Lead");
    expect(stageNote(ORPHAN, 1)).toBe("Fabryki IT: Pierwszy kontakt");
  });

  it("zamknięcie proponuje najpierw „Przegrana”, potem pozostałe etapy przegranej lejka", () => {
    expect(lostStages(PIPELINES, 1).map((item) => item.key)).toEqual(["lost", "not-qualified"]);
    expect(lostStages(PIPELINES, 2).map((item) => item.key)).toEqual(["itf-lost"]);
    expect(lostStages(undefined, 1)).toEqual([]);
  });

  it("historia szansy opisuje odłożenie datą", () => {
    const event = { kind: "updated", field: "keep_open_until", old_value: null, new_value: "2026-11-24" } as OpportunityEvent;
    expect(describeEvent(event)).toBe("Odłożone do: — → 24.11.2026");
  });
});

describe("OffersView", () => {
  it("pokazuje dwie sekcje z licznikami i MRR z API oraz liczniki zakresów", () => {
    render(<OffersView />);

    expect(screen.getByText("W toku")).toBeInTheDocument();
    expect(screen.getByText("1 pozycja · 20 000 zł MRR")).toBeInTheDocument();
    expect(screen.getByText("2 pozycje · 64 000 zł MRR")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Wszystkie 3" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Bez opiekuna 1" })).toBeInTheDocument();
    expect(screen.getByText("W toku: 1 · Do decyzji: 2")).toBeInTheDocument();
    expect(screen.getByText("termin minął w 1 pozycji")).toBeInTheDocument();

    const fresh = within(rowOf("Firma Testowa"));
    expect(fresh.getByText("9 dni")).toBeInTheDocument();
    expect(fresh.getByText("15.12.2026")).toBeInTheDocument();
    expect(fresh.getByText("13.11 · Potwierdzić odbiór oferty")).toBeInTheDocument();
    expect(within(rowOf("Druga Firma")).getByText("31.08.2026")).toHaveClass("text-destructive");
    // Pozycja spoza etapu oferty mówi, na jakim etapie i w którym lejku leży.
    expect(within(rowOf("Trzecia Firma")).getByText("Fabryki IT: Pierwszy kontakt · Pierwsza rozmowa")).toBeInTheDocument();
  });

  it("„Zrobione” odhacza krok z wiersza", () => {
    render(<OffersView />);
    fireEvent.click(within(rowOf("Firma Testowa")).getByRole("button", { name: "Zrobione" }));
    expect(complete).toHaveBeenCalledWith({ id: 91 }, expect.anything());
  });

  it("zaległy krok jest podpisany, a spotkania z kalendarza nie da się odhaczyć", () => {
    offersQuery.mockReturnValue(
      ok(
        payload([
          offer({ step: { ...offer().step!, overdue: true } }),
          offer({
            id: 14,
            company: { id: 6, name: "Czwarta Firma" },
            step: { activity_id: null, kind: "meeting", at: "2026-11-20T09:00:00Z", subject: "Warsztat", overdue: false },
          }),
        ]),
      ),
    );
    render(<OffersView />);
    expect(screen.getByText("Po terminie: 13.11 · Potwierdzić odbiór oferty")).toBeInTheDocument();
    expect(within(rowOf("Czwarta Firma")).queryByRole("button", { name: "Zrobione" })).not.toBeInTheDocument();
  });

  it("oferta w toku bez kroku ma „Zaplanuj”, a odłożona pokazuje datę powrotu", () => {
    offersQuery.mockReturnValue(
      ok(
        payload([
          offer({ step: null }),
          offer({
            id: 15,
            company: { id: 7, name: "Piąta Firma" },
            step: null,
            idle_days: 60,
            postponed: true,
            keep_open_until: "2026-11-24",
          }),
        ]),
      ),
    );
    render(<OffersView />);
    const plain = within(rowOf("Firma Testowa"));
    expect(plain.getByText("brak kroku")).toBeInTheDocument();
    fireEvent.click(plain.getByRole("button", { name: "Zaplanuj" }));
    expect(screen.getByText("Co dalej i kiedy")).toBeInTheDocument();
    expect(within(rowOf("Piąta Firma")).getByText("odłożone do 24.11")).toBeInTheDocument();
  });

  it("do decyzji: opiekun ze Sprzedaży odkłada albo zamyka, bez opiekuna można przejąć", () => {
    render(<OffersView />);

    const stale = within(rowOf("Druga Firma"));
    expect(stale.getByRole("button", { name: "Odłóż do…" })).toBeInTheDocument();
    expect(stale.getByRole("button", { name: "Zamknij z powodem" })).toBeInTheDocument();
    expect(stale.queryByRole("button", { name: "Przejmij" })).not.toBeInTheDocument();

    const orphan = within(rowOf("Trzecia Firma"));
    expect(orphan.getByText("poza Sprzedażą")).toBeInTheDocument();
    expect(orphan.queryByRole("button", { name: "Odłóż do…" })).not.toBeInTheDocument();
    fireEvent.click(orphan.getByRole("button", { name: "Przejmij" }));
    expect(takeOver).toHaveBeenCalledWith(13, expect.anything());
  });

  it("„Odłóż do…” zapisuje datę na szansie, domyślnie za dwa tygodnie", () => {
    render(<OffersView />);
    fireEvent.click(within(rowOf("Druga Firma")).getByRole("button", { name: "Odłóż do…" }));
    fireEvent.click(screen.getByRole("button", { name: "Odłóż" }));
    expect(update).toHaveBeenCalledWith({ keep_open_until: plusDays(14) }, expect.anything());
  });

  it("„Odłóż do…” nie przyjmuje dzisiejszej daty, bo oferta od razu by wróciła", () => {
    render(<OffersView />);
    fireEvent.click(within(rowOf("Druga Firma")).getByRole("button", { name: "Odłóż do…" }));
    fireEvent.change(screen.getByLabelText("Wróć do niej"), { target: { value: plusDays(0) } });
    expect(screen.getByRole("button", { name: "Odłóż" })).toBeDisabled();
  });

  it("„Zamknij z powodem” przesuwa na „Przegrana” z powodem, a etap da się zmienić", () => {
    render(<OffersView />);
    fireEvent.click(within(rowOf("Druga Firma")).getByRole("button", { name: "Zamknij z powodem" }));
    fireEvent.change(screen.getByLabelText("Powód (opcjonalnie)"), { target: { value: " wstrzymany budżet " } });
    fireEvent.click(screen.getByRole("button", { name: "Zamknij szansę" }));
    expect(move).toHaveBeenCalledWith({ id: 12, stage_id: 7, lost_reason: "wstrzymany budżet" }, expect.anything());

    fireEvent.change(screen.getByLabelText("Etap"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Powód (opcjonalnie)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Zamknij szansę" }));
    expect(move).toHaveBeenLastCalledWith({ id: 12, stage_id: 5, lost_reason: undefined }, expect.anything());
  });

  it("bez „Sprzedaż: edycja” nie ma przycisków, jest powód czekania", () => {
    canEdit = false;
    render(<OffersView />);
    expect(screen.queryByRole("button", { name: "Zrobione" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Przejmij" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zamknij z powodem" })).not.toBeInTheDocument();
    expect(within(rowOf("Druga Firma")).getByText("ponad 30 dni bez ruchu")).toBeInTheDocument();
    expect(within(rowOf("Trzecia Firma")).getByText("bez opiekuna w Sprzedaży")).toBeInTheDocument();
  });

  it("zmiana zakresu pyta serwer o ten zakres", () => {
    render(<OffersView />);
    fireEvent.click(screen.getByRole("radio", { name: "Bez opiekuna 1" }));
    expect(offersQuery).toHaveBeenLastCalledWith({ scope: "unowned", q: "" });
  });

  it("zakres z pierwszej odpowiedzi zostaje, gdy serwer po odświeżeniu wybrałby inny", () => {
    const { rerender } = render(<OffersView />);
    // Pierwsze pytanie bez zakresu, kolejne już z tym, który serwer wtedy wybrał.
    expect(offersQuery).toHaveBeenNthCalledWith(1, { scope: undefined, q: "" });
    expect(offersQuery).toHaveBeenLastCalledWith({ scope: "all", q: "" });

    // Po „Przejmij” osoba ma własną ofertę i serwer bez zakresu odpowiedziałby „Moje”.
    offersQuery.mockReturnValue(ok(payload([offer(), STALE, ORPHAN], { scope: "mine" })));
    rerender(<OffersView />);
    expect(offersQuery).toHaveBeenLastCalledWith({ scope: "all", q: "" });
    expect(screen.getByRole("radio", { name: "Wszystkie 3" })).toHaveAttribute("aria-checked", "true");
  });

  it("długa lista „Do decyzji” pokazuje 25 pozycji i resztę pod przyciskiem", () => {
    const many = Array.from({ length: 28 }, (_, index) =>
      offer({ ...STALE, id: 100 + index, company: { id: 100 + index, name: `Firma ${index + 1}` } }),
    );
    offersQuery.mockReturnValue(ok(payload(many)));
    render(<OffersView />);
    expect(screen.queryByText("Firma 26")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż pozostałe (3)" }));
    expect(screen.getByText("Firma 28")).toBeInTheDocument();
  });

  it("pusta sekcja mówi, że jest pusta, a nie znika", () => {
    offersQuery.mockReturnValue(ok(payload([offer()])));
    render(<OffersView />);
    expect(screen.getByText("Nic nie czeka na decyzję.")).toBeInTheDocument();
  });

  it("awaria zapytania nie wygląda jak pusta lista", () => {
    offersQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("boom"),
      isSuccess: false,
      refetch: vi.fn(),
    });
    render(<OffersView />);
    expect(screen.queryByText("Nie ma tu żadnej pozycji")).not.toBeInTheDocument();
    expect(screen.queryByText("W toku")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ponownie/i })).toBeInTheDocument();
  });

  it("pusty wynik po udanym zapytaniu ma pusty stan", () => {
    offersQuery.mockReturnValue(ok(payload([])));
    render(<OffersView />);
    expect(screen.getByText("Nie ma tu żadnej pozycji")).toBeInTheDocument();
  });
});

describe("punkty bota przy „Do decyzji”", () => {
  const POINTS = {
    generated_at: "2026-11-16T07:40:00Z",
    points: [
      { text: "Bank ogłosił nowy program migracji danych", url: "https://example.com/news/1", published: "2026-11-03" },
      { text: "Nowy dyrektor IT", url: "javascript:alert(1)", published: null },
      { text: "Trzeci punkt zostaje na karcie szansy", url: null, published: "2026-10-01" },
    ],
  };

  it("pokazuje do dwóch punktów z datą, podpisem i linkiem do źródła", () => {
    offersQuery.mockReturnValue(ok(payload([offer(), { ...STALE, bot_points: POINTS }])));
    render(<OffersView />);
    const row = within(rowOf("Druga Firma"));

    expect(row.queryByText("Bot · wniosek, sprawdź źródło")).not.toBeInTheDocument();
    expect(row.getByText(/Bank ogłosił nowy program migracji danych/)).toBeInTheDocument();
    expect(row.getByText("03.11.2026:", { exact: false })).toBeInTheDocument();
    expect(row.getByText(/Nowy dyrektor IT/)).toBeInTheDocument();
    expect(row.queryByText(/Trzeci punkt/)).not.toBeInTheDocument();
    // Link tylko http(s): adres z „javascript:” nie dostaje odnośnika.
    const links = row.getAllByRole("link", { name: /źródło/ });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.com/news/1");
    expect(links[0]).toHaveAttribute("target", "_blank");
  });

  it("bot sprawdził firmę i nic nie znalazł: mówi to wprost", () => {
    offersQuery.mockReturnValue(
      ok(payload([offer(), { ...STALE, bot_points: { generated_at: "2026-11-16T07:40:00Z", points: [] } }])),
    );
    render(<OffersView />);
    const row = within(rowOf("Druga Firma"));
    expect(row.getByText("Bot nie znalazł nic nowego od wysłania oferty.")).toBeInTheDocument();
  });

  it("bez punktów (null) i w „W toku” nic nie pokazuje", () => {
    offersQuery.mockReturnValue(ok(payload([offer({ bot_points: POINTS }), STALE])));
    render(<OffersView />);
    expect(screen.queryByLabelText("Punkty od bota")).not.toBeInTheDocument();
    expect(screen.queryByText("Bot · wniosek, sprawdź źródło")).not.toBeInTheDocument();
  });
});
