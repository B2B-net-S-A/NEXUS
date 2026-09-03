import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CvRulesSettingsPage, { type CvRulesOverview } from "./page";
import { makeEmptyClientPlaybook } from "@/test/fixtures/client-playbook";
import { makeCvRuleRow } from "@/test/fixtures/cv-rule";

/**
 * Ekran „Reguły CV per klient" po przebudowie na zarządzanie (09.2026).
 *
 * Trzy rzeczy, które łatwo cofnąć „przy okazji":
 *  * Delivery Lead widzi domyślnie SWÓJ portfel, ale filtr da się wyłączyć —
 *    zawężenie jest wygodą, nie granicą (backend zapisu nie skopuje);
 *  * akcje (dodaj / zatwierdź / edytuj / usuń) widzi rola z `client.update`,
 *    reszta ma czysty odczyt — inaczej recruiter wypełniałby formularz i
 *    dostawał 403 na zapisie;
 *  * awaria pobrania NIE MOŻE wyglądać jak pusta lista.
 */

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  search: "",
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, realUser: null, hydrated: true }),
  // `hasCapability` (lib/capabilities) liczy role z tego helpera — mock musi
  // go wystawić, inaczej `useCapability("client.update")` wywraca render.
  getUserRoles: (user: { role?: string; roles?: string[] } | null) =>
    user ? Array.from(new Set([user.role, ...(user.roles ?? [])])) : [],
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    post: mocks.post,
    put: mocks.put,
    delete: mocks.delete,
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
}));

const DL_USER = {
  id: 7,
  role: "delivery_lead",
  roles: ["delivery_lead"],
  data_scope: {
    kind: "delivery_clients",
    user_id: 7,
    allowed_client_ids: [1],
    allowed_tac_user_ids: [],
    allowed_operator_user_ids: [],
  },
};

const RECRUITER_USER = { id: 8, role: "recruiter", roles: ["recruiter"] };
const TAC_USER = { id: 9, role: "tac", roles: ["tac"] };

const OVERVIEW: CvRulesOverview = {
  rules: [
    makeCvRuleRow({
      client_id: 1,
      client_name: "Nordea Bank Abp",
      seed_key: "profil-championa-wzor-nordea-docx",
      template_label: "Nordea",
      template_url: "https://example.com/nordea.docx",
    }),
    makeCvRuleRow({
      client_id: 2,
      client_name: "Tauron Polska Energia",
      filename_pattern: "B2B_Tauron_{STANOWISKO}_{IMIE_NAZWISKO}",
      spaces_to_underscores: true,
      cv_language: "pl",
      notes: "Maks. 3 rekomendacje.",
      generator_instructions: "Bez sekcji zainteresowań.",
      content_mode: "basic",
      content_mode_locked: true,
      require_project_ref: true,
      is_active: false,
      confirmed_at: null,
      confirmed_by_name: null,
      client_policy: "",
      filename_preview: null,
      version: 3,
      updated_at: "2026-09-01T10:00:00Z",
    }),
  ],
  unassigned_templates: [
    {
      seed_key: "profil-championa-wzor-bnp-paribas-docx",
      label: "BNP PARIBAS",
      template_url: null,
    },
  ],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CvRulesSettingsPage />
    </QueryClientProvider>,
  );
}

describe("CvRulesSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/settings/cv-rules") return { data: OVERVIEW };
      throw new Error(`unexpected GET ${url}`);
    });
    mocks.post.mockResolvedValue({ data: { ...OVERVIEW.rules[1], is_active: true } });
  });

  it("Delivery Lead startuje na swoim portfelu, może go wyłączyć i zatwierdza w miejscu", async () => {
    mocks.user = DL_USER;
    renderPage();

    expect(await screen.findByText("Nordea Bank Abp")).toBeInTheDocument();
    expect(screen.getByText("Twój klient")).toBeInTheDocument();
    // Klient spoza portfela jest odfiltrowany, ale NIE ukryty na stałe.
    expect(screen.queryByText("Tauron Polska Energia")).not.toBeInTheDocument();
    expect(screen.getByText(/pokazuję 1/)).toBeInTheDocument();

    const onlyMine = screen.getByLabelText("Tylko moi klienci");
    expect(onlyMine).toBeChecked();
    fireEvent.click(onlyMine);
    expect(await screen.findByText("Tauron Polska Energia")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: /Dodaj regułę/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Edytuj regułę: Tauron Polska Energia" }),
    ).toBeInTheDocument();
    // Obowiązująca reguła nie ma już czego zatwierdzać.
    expect(
      screen.queryByRole("button", { name: "Zatwierdź regułę: Nordea Bank Abp" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Zatwierdź regułę: Tauron Polska Energia" }),
    );
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/clients/2/cv-rule/confirm"),
    );

    // Szablony bez reguły idą osobną sekcją, z akcją dla roli edytującej.
    expect(screen.getByText("BNP PARIBAS")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Wskaż klienta dla szablonu: BNP PARIBAS" }),
    ).toBeInTheDocument();
  });

  it("„Dodaj regułę” otwiera okno z pickerem klienta", async () => {
    mocks.user = DL_USER;
    renderPage();
    await screen.findByText("Nordea Bank Abp");

    fireEvent.click(screen.getByRole("button", { name: /Dodaj regułę/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Nowa reguła CV")).toBeInTheDocument();
    expect(screen.getByText("Wybierz klienta…")).toBeInTheDocument();
  });

  it("rola bez client.update widzi pełną listę bez żadnej akcji", async () => {
    mocks.user = RECRUITER_USER;
    renderPage();

    expect(await screen.findByText("Nordea Bank Abp")).toBeInTheDocument();
    expect(screen.getByText("Tauron Polska Energia")).toBeInTheDocument();
    expect(screen.queryByLabelText("Tylko moi klienci")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj regułę/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edytuj regułę/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zatwierdź regułę/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń regułę/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Wskaż klienta/ })).not.toBeInTheDocument();
    expect(screen.getByText("BNP PARIBAS")).toBeInTheDocument();
  });

  it("TAC edytuje kartę klienta, ale reguł CV nie prowadzi — zero akcji", async () => {
    // Decyzja produktowa 02.09.2026: bramka zapisu to DeliveryLeadPlus, nie TacPlus.
    mocks.user = TAC_USER;
    renderPage();

    expect(await screen.findByText("Nordea Bank Abp")).toBeInTheDocument();
    expect(screen.getByText("instrukcje AI")).toBeInTheDocument();
    expect(screen.getByText("tryb: Przepisanie")).toBeInTheDocument();
    expect(screen.getByText("wymagane wejścia")).toBeInTheDocument();
    expect(screen.getByText("wersja 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj regułę/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edytuj regułę/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zatwierdź regułę/ })).not.toBeInTheDocument();
  });

  it("?client=<id> otwiera edytor tego klienta od razu", async () => {
    mocks.user = DL_USER;
    mocks.search = "client=2";
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/settings/cv-rules") return { data: OVERVIEW };
      if (url === "/api/clients/2/cv-rule") return { data: OVERVIEW.rules[1] };
      if (url.startsWith("/api/clients/2/cv-rule/")) return { data: [] };
      throw new Error(`unexpected GET ${url}`);
    });
    renderPage();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(
      await screen.findByText("Reguły CV — Tauron Polska Energia"),
    ).toBeInTheDocument();
    mocks.search = "";
  });

  it("?client=2&tab=playbook otwiera edytor na zakładce Karta klienta", async () => {
    // Link „Załóż kartę" z karty klienta (rekrutacja, profil) prowadzi tu
    // z `&tab=playbook` — edytor ma wystartować na karcie, nie na Podstawach.
    mocks.user = DL_USER;
    mocks.search = "client=2&tab=playbook";
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/settings/cv-rules") return { data: OVERVIEW };
      if (url === "/api/clients/2/cv-rule") return { data: OVERVIEW.rules[1] };
      if (url === "/api/clients/2/playbook") return { data: makeEmptyClientPlaybook(2) };
      if (url === "/api/clients/2/playbook/history") return { data: [] };
      if (url.startsWith("/api/clients/2/cv-rule/")) return { data: [] };
      throw new Error(`unexpected GET ${url}`);
    });
    renderPage();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Karta klienta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      await screen.findByLabelText("SLA: dni robocze na pierwszego kandydata"),
    ).toBeInTheDocument();
    mocks.search = "";
  });

  it("awaria pobrania renderuje się jako błąd z ponowieniem, nie jako pustka", async () => {
    mocks.user = DL_USER;
    mocks.get.mockRejectedValue(new Error("network down"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się pobrać danych",
    );
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/i })).toBeInTheDocument();
    expect(
      screen.queryByText("Żaden klient nie ma jeszcze reguł CV"),
    ).not.toBeInTheDocument();
  });

  it("zero reguł to pusty stan z akcją, a szablony bez reguły nadal są widoczne", async () => {
    mocks.user = DL_USER;
    mocks.get.mockResolvedValue({
      data: { rules: [], unassigned_templates: OVERVIEW.unassigned_templates },
    });
    renderPage();

    expect(
      await screen.findByText("Żaden klient nie ma jeszcze reguł CV"),
    ).toBeInTheDocument();
    expect(screen.getByText("BNP PARIBAS")).toBeInTheDocument();
  });
});
