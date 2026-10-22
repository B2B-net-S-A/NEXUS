/**
 * Szczegół sprawy z kontekstem opieki (makieta S4, 22.10.2026): „Kogo
 * dotyczy?” mówi, skąd propozycja (kontakt klienta, jedyny konsultant o tym
 * nazwisku), „Weź” przy sprawie bez osoby (z wersją karty), karta konsultanta
 * obok maila tylko dla obsługi Spraw, z „przedłużenie w toku” i „brak
 * otwartych”. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseDetail } from "@/lib/api/admin-cases";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...args: unknown[]) => mocks.get(...args),
    patch: (...args: unknown[]) => mocks.patch(...args),
    post: vi.fn(),
  },
  default: { get: (...args: unknown[]) => mocks.get(...args) },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.showToast }) }));

import { useAuthStore, type User } from "@/store/auth";

import { CaseDetailView } from "../CaseDetailView";

function detail(overrides: Partial<CaseDetail> = {}): CaseDetail {
  return {
    id: 41,
    title: "Przedłużenie dostępu do systemu klienta",
    area: "administration",
    priority: "P2",
    status: "new",
    due_on: "2026-10-28",
    follow_up_on: null,
    overdue: false,
    assignee: null,
    subject_user: null,
    contract: null,
    source: "mail",
    checklist_done: 0,
    checklist_total: 2,
    created_at: "2026-10-22T07:06:00Z",
    updated_at: "2026-10-22T07:06:00Z",
    closed_at: null,
    description: null,
    checklist: [
      { text: "Potwierdzić datę końca z zamówieniem", done: false },
      { text: "Odpisać klientowi", done: false },
    ],
    lifecycle_case_id: null,
    created_by: null,
    messages: [
      {
        id: 1,
        sender_email: "k.kierownicza@telekom-wzorcowy.example",
        sender_name: "Katarzyna Kierownicza",
        subject: "Dostęp do JIRA — Jakub Makietowy",
        received_at: "2026-10-22T07:05:00Z",
        body_text: "Dzień dobry, dostęp Jakuba wygasa 31.10.",
        attachments: [],
      },
    ],
    comments: [],
    can_manage: true,
    can_comment: true,
    consultant: null,
    link_suggestions: [],
    ...overrides,
  };
}

function mount(data: CaseDetail) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url === "/api/hr/config") return { data: { program: true, open_modules: { care: true } } };
    return { data };
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CaseDetailView caseId={data.id} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  // „31.10” bez roku tylko w bieżącym roku — dzień testu stały.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-22T10:00:00Z"));
  mocks.get.mockReset();
  mocks.patch.mockReset();
  mocks.showToast.mockReset();
  useAuthStore.setState({
    user: { id: 7, name: "Oliwia Skrzynkowa", role: "admin", roles: ["admin"] } as unknown as User,
    hydrated: true,
  });
});

describe("CaseDetailView · S4", () => {
  it("„Kogo dotyczy?”: kontakt klienta, jedyny konsultant o tym nazwisku i „Powiąż z Jakubem”", async () => {
    mocks.patch.mockResolvedValue({ data: detail() });
    mount(
      detail({
        link_suggestions: [
          {
            contract_id: 501,
            candidate_name: "Jakub Makietowy",
            client_name: "Telekom Wzorcowy",
            reason: "Mail z firmy klienta, w treści: Jakub Makietowy",
            sender_kind: "client_contact",
            sender_contact_name: "Katarzyna Kierownicza",
            only_match: true,
          },
        ],
      }),
    );
    const who = await screen.findByRole("region", { name: "Kogo dotyczy?" });
    expect(who).toHaveTextContent(
      "Nadawca to kontakt klienta Telekom Wzorcowy (Katarzyna Kierownicza). W treści: Jakub Makietowy — jedyny nasz konsultant o tym nazwisku u tego klienta.",
    );
    fireEvent.click(within(who).getByRole("button", { name: "Powiąż z Jakubem" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/cases/41", {
        contract_id: 501,
        expected_updated_at: "2026-10-22T07:06:00Z",
      }),
    );
    expect(within(who).getByRole("button", { name: "Inny konsultant…" })).toBeInTheDocument();
  });

  it("„Weź” przy sprawie bez osoby przypisuje mnie z wersją karty", async () => {
    mocks.patch.mockResolvedValue({ data: detail({ assignee: { id: 7, name: "Oliwia Skrzynkowa" } }) });
    mount(detail());
    fireEvent.click(await screen.findByRole("button", { name: "Weź" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/cases/41", {
        assignee_user_id: 7,
        expected_updated_at: "2026-10-22T07:06:00Z",
      }),
    );
    await waitFor(() => expect(mocks.showToast).toHaveBeenCalledWith("Sprawa jest Twoja", "success"));
  });

  it("karta konsultanta: przedłużenie w toku, opiekun z rytmem, „brak otwartych”", async () => {
    mount(
      detail({
        assignee: { id: 9, name: "Natalia Opiekuńcza" },
        contract: {
          id: 501,
          candidate_name: "Jakub Makietowy",
          client_name: "Telekom Wzorcowy",
          start_date: "2026-01-05",
          end_date: "2026-10-31",
          care_owner_user_id: 9,
          care_owner_name: "Natalia O.",
        },
        consultant: {
          contract_id: 501,
          candidate_name: "Jakub Makietowy",
          client_name: "Telekom Wzorcowy",
          role: "Java",
          form: "B2B",
          order_end_on: "2026-10-31",
          order_extension_pending: true,
          owner_user_id: 9,
          owner_name: "Natalia O.",
          cadence_label: "tylko kamienie",
          last_conversation: { on: "2026-07-13", excerpt: "Prosi o rzadki kontakt." },
          other_open_cases: 0,
          health: { level: "ok", label: "Dobrze", reasons: [] },
        },
      }),
    );
    const card = await screen.findByRole("region", { name: "Konsultant" });
    expect(card).toHaveTextContent("Java · Telekom Wzorcowy · B2B");
    expect(card).toHaveTextContent("31.10 · przedłużenie w toku");
    expect(card).toHaveTextContent("Natalia O. · rytm: tylko kamienie");
    expect(card).toHaveTextContent("13.07„Prosi o rzadki kontakt.”");
    expect(card).toHaveTextContent("Inne sprawybrak otwartych");
    expect(within(card).getByRole("link", { name: /Otwórz kartę konsultanta/ })).toHaveAttribute(
      "href",
      "/care?contract=501",
    );
    // Osoba jest przypisana — bez „Weź”.
    expect(screen.queryByRole("button", { name: "Weź" })).toBeNull();
  });

  it("osoba przypisana bez „Spraw” widzi sprawę bez karty konsultanta i bez „Weź”", async () => {
    mount(
      detail({
        can_manage: false,
        assignee: { id: 7, name: "Oliwia Skrzynkowa" },
        contract: {
          id: 501,
          candidate_name: "Jakub Makietowy",
          client_name: "Telekom Wzorcowy",
          start_date: null,
          end_date: null,
          care_owner_user_id: 9,
          care_owner_name: "Natalia O.",
        },
        consultant: null,
      }),
    );
    expect(await screen.findByText("Wiadomości · 1")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Konsultant" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Weź" })).toBeNull();
  });
});
