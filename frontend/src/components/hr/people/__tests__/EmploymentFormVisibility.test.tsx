/**
 * Forma umowy (decyzja Artura 19.10.2026): widzą ją osoba, przełożony, admin
 * i Finanse. Kadry bez Płac dostają kartotekę bez formy — ekran nie pokazuje
 * wiersza „Forma”, a w edycji forma jest „Bez zmian (forma ukryta)” i zapis
 * jej nie wysyła. Kartoteka z konta: forma i przełożony „do uzupełnienia”.
 * Lista rozjazdów kartoteka ↔ konto z „Wyrównaj wg konta”. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountMismatches, PersonFull } from "@/lib/api/hr";

const mocks = vi.hoisted(() => ({
  person: null as unknown,
  mismatches: null as unknown,
  post: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: async (url: string) => {
      if (url === "/api/hr/people") return { data: { items: [], total: 0 } };
      if (url === "/api/hr/people/101") return { data: mocks.person };
      if (url === "/api/hr/people/account-mismatches") return { data: mocks.mismatches };
      throw Object.assign(new Error(url), { response: { status: 500 } });
    },
    post: (...args: unknown[]) => mocks.post(...args),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/components/hr/lifecycle/LifecycleProfileSection", () => ({
  LifecycleProfileSection: () => null,
}));
vi.mock("@/components/hr/payroll/PayrollProfileSection", () => ({
  PayrollProfileSection: () => null,
}));
vi.mock("@/components/hr/people/documents/PersonDocumentsSection", () => ({
  PersonDocumentsSection: () => null,
}));
vi.mock("@/components/hr/people/agreements/PersonAgreementsSection", () => ({
  PersonAgreementsSection: () => null,
}));
vi.mock("@/components/equipment/PersonEquipmentPanel", () => ({
  PersonEquipmentPanel: () => null,
}));

import { hrConfig } from "@/app/preview/hr-fixtures";
import { olaFromAccount, olaFull, olaWithoutForm } from "@/app/preview/hr-person/fixtures";

import {
  AccountMismatchesSection,
  accountTodoCount,
  mismatchOutcome,
} from "../AccountMismatchesPanel";
import { formFrom } from "../EditProfileDialog";
import { PersonProfile } from "../PersonProfile";
import { profileFormToPayload } from "../ProfileFieldsForm";

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderProfile(person: PersonFull, me: Parameters<typeof hrConfig>[0]) {
  mocks.person = person;
  // Pola zatrudnienia i pula stoją w zakładce „Nieobecności i godziny” (dawniej „Czas i przerwy”).
  window.history.replaceState(null, "", "#czas");
  render(
    <QueryClientProvider client={client()}>
      <PersonProfile userId={101} config={hrConfig(me)} />
    </QueryClientProvider>,
  );
  return screen.findByRole("heading", { level: 1, name: /Ola Przykładowa/ });
}

describe("Forma umowy na kartotece", () => {
  beforeEach(() => {
    mocks.person = null;
  });

  it("Kadry bez Płac: bez wiersza „Forma”, edycja kartoteki zostaje", async () => {
    await renderProfile(olaWithoutForm(), { people_admin: true });
    expect(screen.queryByText("Forma")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Edytuj kartotekę/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zmień formę/ })).not.toBeInTheDocument();
    // Pula bez słowa formy („Urlop” = UoP, „Płatne dni przerwy” = B2B) — karta
    // „Nieobecności <rok>” z linią puli (22.10.2026).
    expect(screen.getByText(/^Nieobecności \d{4}$/)).toBeInTheDocument();
    expect(screen.getByText(/^Pula na rok/)).toBeInTheDocument();
    expect(screen.queryByText(/Płatne dni przerwy|^Urlop \d{4}/)).not.toBeInTheDocument();
  });

  it("Finanse: forma widoczna i „Zmień formę” zamiast edycji kartoteki", async () => {
    await renderProfile(olaFull("b2b"), { payroll: true });
    // Wiersz w „Zatrudnieniu” i fakt pod wizytówką.
    expect(screen.getAllByText("Forma")).toHaveLength(2);
    expect(screen.getByRole("button", { name: /Zmień formę/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edytuj kartotekę/ })).not.toBeInTheDocument();
  });

  it("kartoteka z konta: forma i przełożony „do uzupełnienia”", async () => {
    await renderProfile(olaFromAccount(), { people_admin: true, payroll: true });
    expect(screen.getAllByText("do uzupełnienia")).toHaveLength(2);
  });
});

describe("Formularz kartoteki a ukryta forma", () => {
  it("forma ukryta: bez pól od niej zależnych, zapis bez formy", () => {
    const form = formFrom(olaWithoutForm());
    expect(form.employment_type).toBe("");
    expect(form.employment_type_blank).toBe("hidden");
    expect(form.student).toBeUndefined();
    const payload = profileFormToPayload(form);
    expect(payload).not.toHaveProperty("employment_type");
    expect(payload).not.toHaveProperty("student_contribution_exempt");
  });

  it("forma do uzupełnienia: domyślne B2B nie jest wyborem", () => {
    const form = formFrom(olaFromAccount());
    expect(form.employment_type).toBe("");
    expect(form.employment_type_blank).toBe("pending");
    expect(profileFormToPayload({ ...form, employment_type: "b2b" }).employment_type).toBe("b2b");
  });
});

const MISMATCHES: AccountMismatches = {
  items: [
    {
      user_id: 5,
      name: "Marta Fikcyjna",
      email: "marta@example.com",
      account_active: false,
      employment_status: "active",
      proposed_status: "exited",
      last_working_day: null,
      proposed_last_working_day: "2026-10-10",
      kind: "exit",
      reports: 2,
    },
    {
      user_id: 6,
      name: "Igor Bezkartoteczny",
      email: "igor@example.com",
      account_active: true,
      employment_status: null,
      proposed_status: "active",
      last_working_day: null,
      proposed_last_working_day: null,
      kind: "missing",
      reports: 0,
    },
  ],
  total: 2,
  pending: { employment_type: 1, manager: 0 },
};

describe("Rozjazdy kartoteka ↔ konto", () => {
  beforeEach(() => {
    mocks.post.mockReset();
    mocks.mismatches = MISMATCHES;
  });

  it("zdanie „po wyrównaniu” mówi status i ostatni dzień", () => {
    expect(mismatchOutcome(MISMATCHES.items[0])).toBe(
      "Zakończył współpracę, ostatni dzień 10.10.2026",
    );
    expect(mismatchOutcome(MISMATCHES.items[1])).toMatch(/Nowa kartoteka/);
  });

  it("lista po rozwinięciu, „Wyrównaj wg konta” dopiero po potwierdzeniu", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: { aligned: { exit: 1, return: 0, missing: 1 } } });
    render(
      <QueryClientProvider client={client()}>
        <AccountMismatchesSection data={MISMATCHES} />
      </QueryClientProvider>,
    );
    // Sekcja „Konta i kartoteki” w „Porządkach” (22.10.2026) nazywa pozycje
    // od razu; tabela po „Przejrzyj po kolei”.
    expect(accountTodoCount(MISMATCHES, [])).toBe(2);
    expect(screen.getByText(/Igor Bezkartoteczny: konto bez kartoteki/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Przejrzyj po kolei/ }));
    expect(screen.getByText("Konto wyłączone")).toBeInTheDocument();
    expect(screen.getAllByText(/2 osoby w zespole/).length).toBeGreaterThan(0);
    // Przepięcie zespołu — w schemacie katalogu (dawna „Struktura”).
    expect(screen.getByRole("link", { name: "Schemacie" })).toHaveAttribute(
      "href",
      "/people?view=schemat",
    );
    expect(screen.getByText("Forma do uzupełnienia: 1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Wyrównaj wg konta" }));
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(await screen.findByRole("button", { name: "Wyrównaj" }));
    expect(mocks.post).toHaveBeenCalledWith("/api/hr/people/account-mismatches/align", {
      user_ids: [5, 6],
    });
  });

  it("bez rozjazdów i braków — liczba 0 i spokojne zdanie", () => {
    const empty: AccountMismatches = { items: [], total: 0, pending: { employment_type: 0, manager: 0 } };
    expect(accountTodoCount(empty, [])).toBe(0);
    // Bez rozjazdów liczą się braki z serwera; kartoteki z katalogu mają pierwszeństwo.
    expect(accountTodoCount({ ...empty, pending: { employment_type: 2, manager: 1 } }, [])).toBe(3);
    expect(
      accountTodoCount({ ...empty, pending: { employment_type: 2, manager: 1 } }, [
        { user_id: 1, name: "Ola", what: "forma" },
      ]),
    ).toBe(1);
    render(
      <QueryClientProvider client={client()}>
        <AccountMismatchesSection data={empty} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Kartoteki zgadzają się z kontami.")).toBeInTheDocument();
  });
});
