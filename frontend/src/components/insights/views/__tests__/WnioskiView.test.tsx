/**
 * Zakładka „Wnioski”: decyzja idzie na serwer i chowa sprawę, awaria nie wygląda jak
 * pustka, a lista osób jest tylko dla tego, kto ma dostęp do kandydatów.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WnioskiView } from "@/components/insights/views/WnioskiView";

const wnioski = vi.fn();
const wnioskiDecide = vi.fn();
const wnioskiHistory = vi.fn();
const wnioskiReasons = vi.fn();
const wnioskiCollected = vi.fn();
const wnioskiPeople = vi.fn();
let role = "admin";
let seesCandidates = true;

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/insights",
}));

vi.mock("@/lib/insights-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/insights-api")>();
  return {
    ...actual,
    insightsApi: {
      ...actual.insightsApi,
      wnioski: (...args: unknown[]) => wnioski(...args),
      wnioskiDecide: (...args: unknown[]) => wnioskiDecide(...args),
      wnioskiHistory: (...args: unknown[]) => wnioskiHistory(...args),
      wnioskiReasons: (...args: unknown[]) => wnioskiReasons(...args),
      wnioskiCollected: (...args: unknown[]) => wnioskiCollected(...args),
      wnioskiPeople: (...args: unknown[]) => wnioskiPeople(...args),
    },
  };
});

vi.mock("@/store/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/store/auth")>();
  return {
    ...actual,
    useAuthStore: (selector: (s: { user: { role: string; roles: string[] } }) => unknown) =>
      selector({ user: { role, roles: [role] } }),
    hasRole: (_user: unknown, ...roles: string[]) => roles.includes(role),
  };
});

vi.mock("@/lib/capabilities", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/capabilities")>();
  return { ...actual, holdsCapabilityGrant: () => seesCandidates };
});

vi.mock("@/lib/section-access", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/section-access")>();
  return { ...actual, hasSectionAccess: () => seesCandidates };
});

const CASE = {
  key: "konkret",
  number: "1 na 3",
  number_note: "odmowy klienta bez powodu",
  count: 60,
  sample: 180,
  title: "Klient często odmawia bez konkretu",
  why: "60 ze 180 odmów nie mówi, czego zabrakło.",
  if_yes: "Na Tablicy pojawia się wiersz.",
  risk: "Wiersz tylko informuje i niczego nie blokuje.",
  yes_label: "Tak, zleć zmianę",
  owner: "Head of Recruitment",
  owner_role: "head_of_recruitment",
  measure: "odmowy klienta bez powodu",
  certainty: "Szacunek" as const,
  evidence: [{ label: "Nordea, 42511: „Profile not matching”", value: "8 z 10" }],
};

const THUMBS = {
  ...CASE,
  key: "kciuki",
  title: "Kciuków przy dopasowaniu nikt nie używa",
  owner: "Administrator",
  owner_role: "admin",
  certainty: "Policzone" as const,
};

const summary = (cases: unknown[]) => ({
  computed_at: "2026-11-05T09:00:00+00:00",
  counted_from: "2026-10-11T22:00:00+00:00",
  counted_from_label: "12.10",
  open_count: cases.length,
  cases,
  watching: [{ text: "„CV gotowe” przeczytane", value: "17% ze 193" }],
});

const REASONS = {
  computed_at: "2026-11-05T09:00:00+00:00",
  counted_from_label: "12.10",
  total: 100,
  why_out: [
    { key: "rate", reason: "Stawka", today: 20, after: 30 },
    { key: "unread", reason: "„Inne” albo nieodczytane", today: 40, after: 10 },
  ],
  why_out_takeaway: "Odczyt opisów zmniejsza „Inne”.",
  columns: [{ key: "rate", label: "Stawka" }],
  heatmap: [{ client_id: 11, client: "Nordea", total: 50, values: [25] }],
  heatmap_takeaway: "Najbardziej odstają od całości.",
};

function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WnioskiView />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  role = "admin";
  seesCandidates = true;
  wnioski.mockResolvedValue(summary([CASE, THUMBS]));
  wnioskiDecide.mockResolvedValue({ key: "konkret", state: "approved" });
  wnioskiReasons.mockResolvedValue(REASONS);
});

describe("WnioskiView", () => {
  it("mówi „Dane na dziś” i „od 12.10”, a nie „Liczone co noc” ani „90 dni”", async () => {
    view();
    const lede = await screen.findByText(/Dane na dziś, policzone o/);
    expect(lede.textContent).toContain("od 12.10");
    expect(document.body.textContent).not.toMatch(/co noc|90 dni/);
    expect(await screen.findByRole("button", { name: "Do decyzji (2)" })).toBeTruthy();
  });

  it("„Tak” pyta przez okno i zapisuje decyzję na serwerze, a lista wraca bez sprawy", async () => {
    view();
    const row = await screen.findByTestId("decision-konkret");
    wnioski.mockResolvedValue(summary([THUMBS]));
    fireEvent.click(within(row).getByRole("button", { name: "Tak, zleć zmianę" }));
    expect(wnioskiDecide).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Zapisz decyzję" }));
    await waitFor(() => expect(wnioskiDecide).toHaveBeenCalledWith("konkret", "approved"));
    await waitFor(() => expect(screen.queryByTestId("decision-konkret")).toBeNull());
  });

  it("„Nie teraz” zapisuje od razu, bo sprawa i tak wróci", async () => {
    view();
    const row = await screen.findByTestId("decision-konkret");
    fireEvent.click(within(row).getByRole("button", { name: "Nie teraz" }));
    await waitFor(() => expect(wnioskiDecide).toHaveBeenCalledWith("konkret", "later"));
  });

  it("anulowane „Nie” niczego nie zapisuje", async () => {
    view();
    const row = await screen.findByTestId("decision-konkret");
    fireEvent.click(within(row).getByRole("button", { name: "Nie" }));
    fireEvent.click(await screen.findByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Zapisz decyzję" })).toBeNull());
    expect(wnioskiDecide).not.toHaveBeenCalled();
  });

  it("nieudana decyzja pokazuje komunikat serwera", async () => {
    wnioskiDecide.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: "Ta sprawa nie czeka już na decyzję. Odśwież widok." } },
    });
    view();
    const row = await screen.findByTestId("decision-konkret");
    fireEvent.click(within(row).getByRole("button", { name: "Nie teraz" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Odśwież widok");
  });

  it("Head of Recruitment nie ma przycisków przy sprawie Administratora", async () => {
    role = "head_of_recruitment";
    view();
    const thumbs = await screen.findByTestId("decision-kciuki");
    expect(within(thumbs).queryByRole("button", { name: "Nie teraz" })).toBeNull();
    expect(within(thumbs).getByText(/Decyduje: Administrator/)).toBeTruthy();
    const refusals = screen.getByTestId("decision-konkret");
    expect(within(refusals).getByRole("button", { name: "Nie teraz" })).toBeTruthy();
  });

  it("dowód i ryzyko są o jedno kliknięcie", async () => {
    view();
    const row = await screen.findByTestId("decision-konkret");
    expect(within(row).queryByText(/niczego nie blokuje/)).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Skąd to wiemy" }));
    expect(within(row).getByText(/niczego nie blokuje/)).toBeTruthy();
    expect(within(row).getByText("8 z 10")).toBeTruthy();
  });

  it("awaria nie wygląda jak pusta lista", async () => {
    wnioski.mockRejectedValue(new Error("500"));
    view();
    await waitFor(() => expect(wnioski).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/Nic nie czeka na decyzję/)).toBeNull());
    expect(await screen.findByRole("button", { name: /spróbuj|ponów/i })).toBeTruthy();
    expect(screen.queryByText(/Nic nie czeka na decyzję/)).toBeNull();
  });

  it("pusta lista po udanym odczycie mówi, że nic nie czeka", async () => {
    wnioski.mockResolvedValue(summary([]));
    view();
    expect(await screen.findByText(/Nic nie czeka na decyzję/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Do decyzji (0)" })).toBeTruthy();
  });

  it("klik w liczbę otwiera osoby w panelu z boku", async () => {
    wnioskiPeople.mockResolvedValue({
      total: 30,
      rows: [
        {
          candidate_id: 7,
          name: "Fikcyjna Osoba",
          rejected_at: "2026-11-01T10:00:00+00:00",
          job_id: 1,
          job_title: "Rekrutacja",
          client: "Nordea",
        },
      ],
    });
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Powody odrzuceń" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stawka, po odczytaniu: 30, pokaż osoby" }));
    const panel = await screen.findByTestId("wnioski-people-panel");
    expect(await within(panel).findByRole("link", { name: "Fikcyjna Osoba" })).toBeTruthy();
    expect(wnioskiPeople).toHaveBeenCalledWith(
      expect.objectContaining({ bucket: "rate", basis: "after" }),
      40,
    );
  });

  it("bez dostępu do kandydatów liczby są, a listy osób nie ma", async () => {
    seesCandidates = false;
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Powody odrzuceń" }));
    expect(await screen.findByText("Odsetek odrzuceń u klienta, po odczytaniu opisów")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /pokaż osoby/ })).toBeNull();
    expect(screen.getByText("50%")).toBeTruthy();
  });

  it("awaria powodów nie udaje pustego wykresu", async () => {
    wnioskiReasons.mockRejectedValue(new Error("500"));
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Powody odrzuceń" }));
    expect(await screen.findByRole("button", { name: /spróbuj|ponów/i })).toBeTruthy();
    expect(screen.queryByText("Dlaczego ludzie odpadają")).toBeNull();
  });

  it("historia pokazuje decyzje i ocenę na 100 dodanych, bez werdyktu przed terminem", async () => {
    wnioskiHistory.mockResolvedValue({
      approved: [
        {
          key: "zatrudnieni",
          title: "System dalej podsuwa ludzi, którzy pracują już gdzie indziej",
          number: "61",
          decided_at: "2026-11-03T23:00:00+00:00",
          decided_by: "Artur",
          measure: "karty od systemu dla takich osób",
          review_on: "2026-12-04",
          measure_now: null,
          change: "#3034",
        },
      ],
      deferred: [
        {
          key: "cv",
          title: "Rekruterzy najczęściej przepisują",
          number: "21%",
          decided_at: "2026-11-05T09:00:00+00:00",
          decided_by: "Fikcyjna Osoba",
          state: "rejected",
          return_on: null,
          return_count: 464,
        },
      ],
      rules: [
        {
          rule: "Stawka do 15% ponad budżet: za resztą",
          since: "27.10",
          metric: "„Za drogo”",
          before: { hits: 21, added: 2220, refused: 55, per_100: 0.9 },
          after: { hits: 11, added: 1015, refused: 107, per_100: 1.1 },
          review_on: "2026-11-26",
          verdict: null,
        },
      ],
      rules_takeaway: "Sam udział myli, więc werdykt dopiero po 30 dniach.",
    });
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Historia decyzji" }));
    const approved = await screen.findByTestId("history-approved-zatrudnieni");
    expect(approved.textContent).toContain("#3034");
    expect(approved.textContent).toContain("Ocena 04.12");
    expect(screen.getByTestId("history-deferred").textContent).toContain("Wraca, gdy liczba z 30 dni dojdzie do 464");
    expect(screen.getByText("0,9")).toBeTruthy();
    expect(screen.getByText("1,1")).toBeTruthy();
    expect(screen.getByText("Za wcześnie, ocena 26.11")).toBeTruthy();
  });

  it("awaria spisu sygnałów nie wygląda jak pusta tabela", async () => {
    wnioskiCollected.mockRejectedValue(new Error("500"));
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Co zbieramy" }));
    expect(await screen.findByRole("button", { name: /spróbuj|ponów/i })).toBeTruthy();
  });
});
