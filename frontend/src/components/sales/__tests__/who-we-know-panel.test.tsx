/**
 * „Kogo znamy”: najpierw pięć osób, inne nazwy z CV, napis o dzienniku tylko
 * po prawdziwym zapisie, awaria nie wygląda jak pustka.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CompanyAliases, CompanyPeople, MatchedPerson } from "@/lib/api/sales";

const decide = vi.fn();
const undo = vi.fn();
const refetchAliases = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
let peopleState: Record<string, unknown>;
let aliasState: Record<string, unknown>;
let permissions: string[];

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useCompanyPeople: () => peopleState,
  useCompanyGroupPeople: () => ({ isError: false, isSuccess: false, data: undefined, refetch: vi.fn() }),
  useFillCompanyDates: () => ({ mutate: vi.fn(), isPending: false }),
  useCompanyAliases: () => aliasState,
  useDecideCompanyAlias: () => ({ mutate: decide, isPending: false }),
  useUndoCompanyAlias: () => ({ mutate: undo, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (state: { user: { permissions: string[]; role: string } }) => unknown) =>
    select({ user: { permissions, role: "recruiter" } }),
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: (_user: unknown, permission: string) => permissions.includes(permission),
}));

import { WhoWeKnowPanel } from "../WhoWeKnowPanel";

const person = (id: number, fields: Partial<MatchedPerson> = {}): MatchedPerson => ({
  candidate_id: id,
  name: "Osoba",
  lastname: `Numer${id}`,
  relationship: "current",
  title: "Programista",
  company_matched: "Firma",
  period: { start: "2024", end: null },
  email: null,
  phone: null,
  linkedin: null,
  profile_url: null,
  added_at: "2026-10-01",
  decision_role: false,
  cv_stale: false,
  ...fields,
});

const panel = (people: MatchedPerson[], fields: Partial<CompanyPeople> = {}): CompanyPeople => ({
  matched_client: null,
  counts: {
    via_us: 0,
    current: people.filter((p) => p.relationship === "current").length,
    past: 0,
    unknown: 0,
  },
  truncated: false,
  people,
  dates_backfill: null,
  read_logged: true,
  own_company: false,
  ...fields,
});

const noAliases: CompanyAliases = {
  decisions: [],
  suggestions: [],
  other_count: 0,
  other_min: 0,
  other_max: 0,
  own_cards: [],
};

const success = <T,>(data: T) => ({ data, isLoading: false, isSuccess: true, isError: false, error: null, refetch: vi.fn() });

const show = (people: CompanyPeople, aliases: CompanyAliases = noAliases) => {
  peopleState = success(people);
  aliasState = { ...success(aliases), refetch: refetchAliases };
  return render(<WhoWeKnowPanel companyId={7} companyName="Firma" />);
};

beforeEach(() => {
  decide.mockReset();
  undo.mockReset();
  refetchAliases.mockReset();
  showError.mockReset();
  permissions = ["sales_view", "sales_edit"];
});

describe("pięć osób na start", () => {
  const seven = Array.from({ length: 7 }, (_, index) => person(index + 1));

  it("pokazuje pięć pierwszych z API i przycisk z pełną liczbą", () => {
    show(panel(seven, { counts: { via_us: 0, current: 40, past: 0, unknown: 0 } }));
    const start = screen.getByRole("region", { name: /Pracują tam teraz/ });
    expect(within(start).getAllByRole("listitem")).toHaveLength(5);
    expect(within(start).getByText("Osoba Numer1")).toBeTruthy();
    expect(within(start).queryByText("Osoba Numer6")).toBeNull();
    expect(screen.getByRole("button", { name: "Pokaż wszystkich pracujących (40)" })).toBeTruthy();
  });

  it("po rozwinięciu dokłada pozostałych alfabetycznie", () => {
    show(panel([...seven.slice(0, 5), person(8, { lastname: "Zet" }), person(9, { lastname: "Alfa" })]));
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkich pracujących (7)" }));
    const rest = screen.getByRole("region", { name: "Pozostali, alfabetycznie" });
    const names = within(rest).getAllByRole("link").map((link) => link.textContent);
    expect(names).toEqual(["Osoba Alfa", "Osoba Zet"]);
  });

  it.each([1, 3, 5])("przy %i pracujących nie ma czego rozwijać", (count) => {
    show(panel(Array.from({ length: count }, (_, index) => person(index + 1))));
    expect(screen.queryByRole("button", { name: /Pokaż wszystkich pracujących/ })).toBeNull();
    expect(screen.queryByText(/Tych osób nie widać/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Pozostali, alfabetycznie" })).toBeNull();
  });

  it("przy szóstej osobie przycisk wraca", () => {
    show(panel(Array.from({ length: 6 }, (_, index) => person(index + 1))));
    expect(screen.getByRole("button", { name: "Pokaż wszystkich pracujących (6)" })).toBeTruthy();
  });

  it("gdy API ucięło listę, mówi prawdę o brakujących", () => {
    show(panel(seven.slice(0, 5), { truncated: true, counts: { via_us: 0, current: 40, past: 0, unknown: 0 } }));
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkich pracujących (40)" }));
    expect(screen.getByText(/Tych osób nie widać/)).toBeTruthy();
  });

  it("oznacza rolę decyzyjną, stare CV i datę dodania", () => {
    show(panel([person(1, { decision_role: true, cv_stale: true, added_at: "2019-03-04" }), person(2)]));
    expect(screen.getAllByText("Rola decyzyjna")).toHaveLength(1);
    expect(screen.getAllByText("CV sprzed 3 lat")).toHaveLength(1);
    expect(screen.getByText("w bazie od 04.03.2019")).toBeTruthy();
  });
});

describe("dziennik odczytu", () => {
  it("pokazuje napis tylko, gdy zapis się udał", () => {
    show(panel([person(1)], { read_logged: true }));
    expect(screen.getByText("Odczyt zapisany w dzienniku")).toBeTruthy();
  });

  it("nie twierdzi tego przy nieudanym zapisie", () => {
    show(panel([person(1)], { read_logged: false }));
    expect(screen.queryByText("Odczyt zapisany w dzienniku")).toBeNull();
  });
});

describe("inne nazwy z CV", () => {
  const aliases: CompanyAliases = {
    decisions: [{ id: 5, name: "Stara Nazwa", status: "joined" }],
    suggestions: [{ key: "firma hipoteczna", name: "Firma Hipoteczna", people: 4, current: 1 }],
    other_count: 3,
    other_min: 1,
    other_max: 2,
    own_cards: [{ id: 99, name: "Firma Leasing", current: 2 }],
  };

  it("zapisuje dołączenie i odrzucenie pełną nazwą", () => {
    show(panel([person(1)]), aliases);
    fireEvent.click(screen.getByRole("button", { name: "Dołącz: Firma Hipoteczna" }));
    expect(decide.mock.calls[0][0]).toEqual({ name: "Firma Hipoteczna", status: "joined" });
    fireEvent.click(screen.getByRole("button", { name: "Nie ta firma: Firma Hipoteczna" }));
    expect(decide.mock.calls[1][0]).toEqual({ name: "Firma Hipoteczna", status: "rejected" });
  });

  it("cofa decyzję i pokazuje firmy z własną kartą", () => {
    show(panel([person(1)]), aliases);
    fireEvent.click(screen.getByRole("button", { name: "Cofnij: Stara Nazwa" }));
    expect(undo.mock.calls[0][0]).toBe(5);
    const card = screen.getByRole("link", { name: "Firma Leasing" });
    expect(card.getAttribute("href")).toBe("/sales/companies/99");
  });

  it("bez sales_edit nie ma przycisków zapisu", () => {
    permissions = ["sales_view"];
    show(panel([person(1)]), aliases);
    expect(screen.getByText("Firma Hipoteczna")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Dołącz/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cofnij/ })).toBeNull();
  });

  it("awaria skanu nazw mówi o tym i nie chowa listy osób", () => {
    peopleState = success(panel([person(1)]));
    aliasState = { data: undefined, isLoading: false, isSuccess: false, isError: true, error: new Error("x"), refetch: refetchAliases };
    render(<WhoWeKnowPanel companyId={7} companyName="Firma" />);
    expect(screen.getByText(/Nie udało się sprawdzić innych nazw z CV/)).toBeTruthy();
    expect(screen.getByText("Osoba Numer1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(refetchAliases).toHaveBeenCalledOnce();
  });

  it("pokazuje podpowiedzi także przy pustej liście osób", () => {
    show(panel([]), aliases);
    expect(screen.getByText("Firma Hipoteczna")).toBeTruthy();
    expect(screen.getByText(/Nikt z bazy NEXUSA/)).toBeTruthy();
  });
});

describe("stany panelu", () => {
  it("awaria zapytania nie wygląda jak pusta lista", () => {
    peopleState = { data: undefined, isLoading: false, isSuccess: false, isError: true, error: new Error("x"), refetch: vi.fn() };
    aliasState = success(noAliases);
    render(<WhoWeKnowPanel companyId={7} companyName="Firma" />);
    expect(screen.queryByText(/Nikt z bazy NEXUSA/)).toBeNull();
  });

  it("karta naszej firmy mówi, czemu nie ma listy", () => {
    show(panel([], { own_company: true, read_logged: false }));
    expect(screen.getByText(/To nasza firma/)).toBeTruthy();
    expect(screen.queryByText(/Nikt z bazy NEXUSA/)).toBeNull();
    expect(screen.queryByText("Odczyt zapisany w dzienniku")).toBeNull();
  });
});
