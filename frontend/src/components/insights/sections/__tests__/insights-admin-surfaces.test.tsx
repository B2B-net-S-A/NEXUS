/**
 * Panele ADMINA: zakładanie kampanii i nadawanie plakietek ostrzeżeń.
 *
 * Powstały, bo bez nich obie funkcje są martwe na produkcji — baner nie ma
 * czego pokazać, a tabela `user_performance_flags` zostaje pusta na zawsze.
 * Testy pilnują trzech rzeczy, które łatwo zgubić przy sprzątaniu:
 *
 * 1. Kontrolki widzi WYŁĄCZNIE admin (ukrycie to wygoda, nie bramka — zapis
 *    i tak stoi na `AdminUser` po stronie serwera).
 * 2. Kontrolka plakietek renderuje się także przy ZERZE plakietek — inaczej
 *    pierwszego ostrzeżenia nie da się nadać nikomu.
 * 3. Formularz kampanii odmawia odwróconego okna po polsku, zamiast wysyłać
 *    je do bazy i odbijać się o CHECK-a.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  role: { current: "admin" as string },
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    patch: (...a: unknown[]) => mocks.patch(...a),
    delete: (...a: unknown[]) => mocks.del(...a),
  },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: { user: { role: string } }) => unknown) =>
    selector({ user: { role: mocks.role.current } }),
}));

import { InsightsCampaignAdmin } from "@/components/insights/sections/InsightsCampaignAdmin";
import {
  InsightsFlagAdmin,
  assignableTypes,
} from "@/components/insights/sections/InsightsFlagAdmin";
import type { PerformanceFlag } from "@/lib/insights-flags-api";

const TYPES = [
  {
    value: "weak_results" as const,
    label: "Słabe wyniki",
    description: "Bardzo słabe wyniki, wymagana nagła poprawa",
    severity: "critical" as const,
  },
  {
    value: "procedures" as const,
    label: "Procedury",
    description: "Nieprzestrzeganie procedur",
    severity: "warning" as const,
  },
];

const FLAG: PerformanceFlag = {
  id: 7,
  user_id: 42,
  flag_type: "weak_results",
  label: "Słabe wyniki",
  description: "Bardzo słabe wyniki, wymagana nagła poprawa",
  severity: "critical",
  note: null,
  is_active: true,
  created_at: "2026-08-01T09:00:00+02:00",
  created_by_id: 1,
  created_by_name: "Admin",
  cleared_at: null,
  cleared_by_id: null,
  cleared_by_name: null,
};

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.role.current = "admin";
  mocks.get.mockResolvedValue({ data: { campaigns: [] } });
  mocks.post.mockResolvedValue({ data: {} });
  mocks.patch.mockResolvedValue({ data: {} });
  mocks.del.mockResolvedValue({ data: undefined });
});

describe("InsightsCampaignAdmin", () => {
  it("nie renderuje się dla nie-admina", () => {
    mocks.role.current = "recruiter";
    const { container } = renderWithClient(<InsightsCampaignAdmin />);
    expect(container).toBeEmptyDOMElement();
  });

  it("nie rusza sieci, dopóki panel jest zwinięty", () => {
    renderWithClient(<InsightsCampaignAdmin />);
    // Lista kampanii jest admin-only i nikomu nie jest potrzebna, zanim
    // ktoś faktycznie otworzy panel.
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("odmawia odwróconego okna PO POLSKU, zamiast wysyłać je do bazy", async () => {
    renderWithClient(<InsightsCampaignAdmin />);
    fireEvent.click(screen.getByRole("button", { name: /Kampanie/ }));

    fireEvent.change(await screen.findByLabelText("Nazwa kampanii"), {
      target: { value: "Jesienna" },
    });
    fireEvent.change(screen.getByLabelText("Data startu"), {
      target: { value: "2026-10-01" },
    });
    fireEvent.change(screen.getByLabelText("Data końca"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Załóż i pokaż baner/ }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Data końca jest wcześniejsza/,
    );
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("zakłada kampanię od razu aktywną — inaczej baner dalej nic nie pokazuje", async () => {
    renderWithClient(<InsightsCampaignAdmin />);
    fireEvent.click(screen.getByRole("button", { name: /Kampanie/ }));

    fireEvent.change(await screen.findByLabelText("Nazwa kampanii"), {
      target: { value: "Jesienna" },
    });
    fireEvent.change(screen.getByLabelText("Data startu"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByLabelText("Data końca"), {
      target: { value: "2026-10-31" },
    });
    fireEvent.change(screen.getByLabelText("Cel netto"), {
      target: { value: "40" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Załóż i pokaż baner/ }),
    );

    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0][1]).toMatchObject({
      name: "Jesienna",
      start_date: "2026-09-01",
      end_date: "2026-10-31",
      target_net: 40,
      is_active: true,
    });
  });
});

describe("InsightsFlagAdmin", () => {
  it("nie renderuje się dla nie-admina", () => {
    mocks.role.current = "recruiter";
    const { container } = renderWithClient(
      <InsightsFlagAdmin userId={42} userName="Jan" flags={[]} types={TYPES} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("pozwala nadać PIERWSZĄ plakietkę osobie, która nie ma żadnej", async () => {
    renderWithClient(
      <InsightsFlagAdmin userId={42} userName="Jan" flags={[]} types={TYPES} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Zarządzaj ostrzeżeniami/ }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /Nadaj: Słabe wyniki/ }),
    );

    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0][1]).toMatchObject({
      user_id: 42,
      flag_type: "weak_results",
    });
  });

  it("nie proponuje typu, który już wisi — przycisk pewny 409 to gorszy interfejs niż jego brak", async () => {
    renderWithClient(
      <InsightsFlagAdmin
        userId={42}
        userName="Jan"
        flags={[FLAG]}
        types={TYPES}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Zarządzaj ostrzeżeniami/ }),
    );

    expect(
      await screen.findByRole("button", { name: /Nadaj: Procedury/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Nadaj: Słabe wyniki/ }),
    ).toBeNull();
  });

  it("mówi Zdejmij, nie Usuń — wygaszamy, nie kasujemy historii ocen", async () => {
    renderWithClient(
      <InsightsFlagAdmin
        userId={42}
        userName="Jan"
        flags={[FLAG]}
        types={TYPES}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Zarządzaj ostrzeżeniami/ }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Zdejmij" }));

    await waitFor(() => expect(mocks.patch).toHaveBeenCalled());
    expect(mocks.patch.mock.calls[0][0]).toBe(
      "/api/insights/performance-flags/7",
    );
    // Wygaszenie, nie DELETE — historia ocen jest tym, co czyni je uczciwymi.
    expect(mocks.patch.mock.calls[0][1]).toEqual({ is_active: false });
    expect(mocks.del).not.toHaveBeenCalled();
  });

  it("assignableTypes odsiewa typy już nadane", () => {
    expect(assignableTypes(TYPES, []).map((t) => t.value)).toEqual([
      "weak_results",
      "procedures",
    ]);
    expect(assignableTypes(TYPES, [FLAG]).map((t) => t.value)).toEqual([
      "procedures",
    ]);
  });
});

describe("Awaria zapisu nie moze wygladac jak brak reakcji", () => {
  it("nieudane przelaczenie banera mowi, ze serwer odmowil", async () => {
    mocks.get.mockResolvedValue({
      data: {
        campaigns: [
          {
            id: 3,
            name: "Jesienna",
            emoji: null,
            start_date: "2026-09-01",
            end_date: "2026-10-31",
            target_net: 40,
            is_active: false,
            created_at: null,
          },
        ],
      },
    });
    mocks.patch.mockRejectedValue({
      response: { data: { detail: "Kampania zostala usunieta." } },
    });

    renderWithClient(<InsightsCampaignAdmin />);
    fireEvent.click(screen.getByRole("button", { name: /Kampanie/ }));
    fireEvent.click(
      await screen.findByRole("button", { name: /Pokaz baner|Pokaż baner/ }),
    );

    // Bez tej galezi panel wyglada dokladnie tak jak przed klikiem, wiec
    // odmowa serwera czyta sie jako „przycisk nie dziala".
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Kampania zostala usunieta/,
    );
  });

  it("nieudane nadanie plakietki mowi, ze serwer odmowil", async () => {
    mocks.post.mockRejectedValue({
      response: { data: { detail: "Ta osoba ma juz to ostrzezenie." } },
    });

    renderWithClient(
      <InsightsFlagAdmin userId={42} userName="Jan" flags={[]} types={TYPES} />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: /Zarzadzaj ostrzezeniami|Zarządzaj ostrzeżeniami/,
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: /Nadaj: Slabe wyniki|Nadaj: Słabe wyniki/,
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Ta osoba ma juz to ostrzezenie/,
    );
  });
});
