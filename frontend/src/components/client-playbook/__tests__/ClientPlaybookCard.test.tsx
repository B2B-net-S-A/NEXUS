import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ClientPlaybookCard,
  type ClientPlaybookCardProps,
} from "@/components/client-playbook/ClientPlaybookCard";
import {
  makeClientPlaybook,
  makeEmptyClientPlaybook,
} from "@/test/fixtures/client-playbook";
import { makeCvRule } from "@/test/fixtures/cv-rule";

/**
 * Karta klienta do odczytu.
 *
 * Kontrakty, które łatwo cofnąć „przy okazji":
 *  * cztery gałęzie w kolejności błąd → ładowanie → pusto → dane; pusty stan
 *    WYŁĄCZNIE po sukcesie, a 403 to „Brak uprawnień", nigdy pustka;
 *  * akcja edycji (link `editHref` ALBO przycisk `onEdit`) tylko z capability
 *    `client_playbook.manage` — odczyt karty jest org-wide;
 *  * link dokumentu przechodzi przez allowlistę http/https (stored XSS);
 *  * awaria reguły CV nie blokuje karty, tylko dostaje podpowiedź przy fakcie;
 *  * wariant compact linkuje do POMOCY (`/help?tab=clients&client=<id>`), nie
 *    do profilu klienta — rekruter nie przejdzie przez middleware `/clients`.
 */

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    put: mocks.put,
    post: mocks.post,
    delete: mocks.delete,
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, realUser: null, hydrated: true }),
  // `hasCapability` (lib/capabilities) liczy role z tego helpera — mock musi
  // go wystawić, inaczej `useCapability` wywraca render.
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

const DL_USER = { id: 7, role: "delivery_lead", roles: ["delivery_lead"] };
const RECRUITER_USER = { id: 8, role: "recruiter", roles: ["recruiter"] };

const PLAYBOOK_URL = "/api/clients/1/playbook";
const CV_RULE_URL = "/api/clients/1/cv-rule";
const HEADER = "Karta klienta — Nordea Bank Abp";

type Handler = () => unknown;

/** Routing per URL — handler, który rzuca, daje odrzucone zapytanie. */
function routeGet(handlers: Record<string, Handler>) {
  mocks.get.mockImplementation(async (url: string) => {
    const handler = handlers[url];
    if (!handler) throw new Error(`unexpected GET ${url}`);
    return { data: handler() };
  });
}

function playbookCalls(): number {
  return mocks.get.mock.calls.filter(([url]) => url === PLAYBOOK_URL).length;
}

function renderCard(props: Partial<ClientPlaybookCardProps> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ClientPlaybookCard clientId={1} variant="full" {...props} />
    </QueryClientProvider>,
  );
}

describe("ClientPlaybookCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.user = DL_USER;
    routeGet({
      [PLAYBOOK_URL]: () => makeClientPlaybook(),
      [CV_RULE_URL]: () => makeCvRule(),
    });
  });

  it("renderuje nagłówek z nazwą i wersją, fakty, markdown i dokumenty", async () => {
    renderCard();
    expect(await screen.findByText(HEADER)).toBeInTheDocument();
    expect(screen.getByText(/wersja 3/)).toBeInTheDocument();
    expect(screen.getByText(/zaktualizował Artur/)).toBeInTheDocument();

    // Fakty (KeyFacts) — liczby, polityka stawek, off-limit z umowy.
    expect(
      screen.getByText("Maks. 180 PLN/h B2B, bez negocjacji po wysyłce CV."),
    ).toBeInTheDocument();
    expect(screen.getByText("12 mies. · Cały bank")).toBeInTheDocument();
    expect(
      screen.getByText("Skandynawski bank, zespoły produktowe, praca po angielsku."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Kandydaci z bankowością w pierwszej kolejności"),
    ).toBeInTheDocument();

    // Markdown renderuje się jako elementy, nie jako surowy tekst.
    expect(screen.getByRole("heading", { name: "Etapy" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Po akceptacji" })).toBeInTheDocument();

    const link = screen.getByRole("link", { name: "NDA klienta" });
    expect(link).toHaveAttribute("href", "https://b2bnetsa.sharepoint.com/nda");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("exists=false to pusty stan; CTA „Załóż kartę” tylko dla client_playbook.manage", async () => {
    routeGet({
      [PLAYBOOK_URL]: () => makeEmptyClientPlaybook(1, "Nordea Bank Abp"),
      [CV_RULE_URL]: () => makeCvRule(),
    });
    const editHref = "/settings/cv-rules?client=1&tab=playbook";

    const dl = renderCard({ editHref });
    const cta = await screen.findByRole("link", { name: "Załóż kartę" });
    expect(cta).toHaveAttribute("href", editHref);
    expect(screen.getByText("Ten klient nie ma jeszcze karty")).toBeInTheDocument();
    dl.unmount();

    mocks.user = RECRUITER_USER;
    renderCard({ editHref });
    expect(await screen.findByText("Ten klient nie ma jeszcze karty")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Załóż kartę" })).not.toBeInTheDocument();
  });

  it("awaria pobrania to alert z ponowieniem, nie pusty stan", async () => {
    let failuresLeft = 1;
    routeGet({
      [PLAYBOOK_URL]: () => {
        if (failuresLeft > 0) {
          failuresLeft -= 1;
          throw new Error("network down");
        }
        return makeClientPlaybook();
      },
      [CV_RULE_URL]: () => makeCvRule(),
    });
    renderCard();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać danych");
    expect(alert).toHaveTextContent("Karta może istnieć");
    expect(screen.queryByText("Ten klient nie ma jeszcze karty")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(await screen.findByText(HEADER)).toBeInTheDocument();
    expect(playbookCalls()).toBe(2);
  });

  it("403 renderuje „Brak uprawnień”, nie pustkę", async () => {
    routeGet({
      [PLAYBOOK_URL]: () => {
        throw Object.assign(new Error("Forbidden"), { response: { status: 403 } });
      },
      [CV_RULE_URL]: () => makeCvRule(),
    });
    renderCard();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Ten klient nie ma jeszcze karty")).not.toBeInTheDocument();
    // 403 nie ma czego ponawiać.
    expect(screen.queryByRole("button", { name: /Spróbuj ponownie/ })).not.toBeInTheDocument();
  });

  it("link dokumentu z niedozwolonym schematem nie jest renderowany jako <a>", async () => {
    routeGet({
      [PLAYBOOK_URL]: () =>
        makeClientPlaybook({
          documents: [{ name: "XSS", url: "javascript:alert(1)" }],
        }),
      [CV_RULE_URL]: () => makeCvRule(),
    });
    renderCard();

    await screen.findByText(HEADER);
    expect(screen.queryByRole("link", { name: /XSS/ })).not.toBeInTheDocument();
    expect(screen.getByText("XSS — nieprawidłowy link")).toBeInTheDocument();
  });

  it("fakty z reguły CV tylko gdy reguła obowiązuje", async () => {
    const active = renderCard();
    await screen.findByText(HEADER);
    expect(
      await screen.findByText("B2B_Analityk Biznesowy_Jan Kowalski.docx"),
    ).toBeInTheDocument();
    expect(await screen.findByText("EN")).toBeInTheDocument();
    active.unmount();

    routeGet({
      [PLAYBOOK_URL]: () => makeClientPlaybook(),
      [CV_RULE_URL]: () =>
        makeCvRule({
          is_active: false,
          confirmed_at: null,
          client_policy: "",
          filename_preview: null,
        }),
    });
    renderCard();
    await screen.findByText(HEADER);
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(CV_RULE_URL));
    expect(
      screen.queryByText("B2B_Analityk Biznesowy_Jan Kowalski.docx"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("B2B_{STANOWISKO}_{IMIE_NAZWISKO}")).not.toBeInTheDocument();
    expect(screen.queryByText("EN")).not.toBeInTheDocument();
  });

  it("awaria reguły CV nie blokuje karty", async () => {
    routeGet({
      [PLAYBOOK_URL]: () => makeClientPlaybook(),
      [CV_RULE_URL]: () => {
        throw new Error("cv rule down");
      },
    });
    renderCard();

    expect(await screen.findByText(HEADER)).toBeInTheDocument();
    // Podpowiedź przy obu faktach z reguły CV (nazwa pliku, język).
    expect(
      await screen.findAllByText("nie udało się sprawdzić reguły CV"),
    ).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("wariant compact: chipy, priorytet i link do pełnej karty w Pomocy, bez markdownu", async () => {
    renderCard({ variant: "compact" });

    const link = await screen.findByRole("link", { name: /Pełna karta klienta/ });
    expect(link).toHaveAttribute("href", "/help?tab=clients&client=1");
    expect(screen.getByText("SLA 5 dni")).toBeInTheDocument();
    expect(screen.getByText("min. 3 kand.")).toBeInTheDocument();
    expect(screen.getByText("limit CV 4")).toBeInTheDocument();
    expect(screen.getByText("blokada 48 h")).toBeInTheDocument();
    expect(screen.getByText("karencja 90 dni")).toBeInTheDocument();
    expect(screen.getByText("off-limit 12 mies.")).toBeInTheDocument();
    expect(await screen.findByText("CV: EN")).toBeInTheDocument();
    expect(
      screen.getByText("plik: B2B_Analityk Biznesowy_Jan Kowalski.docx"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Kandydaci z bankowością/)).toBeInTheDocument();

    expect(screen.queryByRole("heading", { name: "Etapy" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "NDA klienta" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("client-playbook-edit")).not.toBeInTheDocument();
  });

  it("link „Edytuj kartę” w wariancie full tylko z capability", async () => {
    const editHref = "/clients/1?tab=zasady";

    const dl = renderCard({ editHref });
    await screen.findByText(HEADER);
    expect(screen.getByRole("link", { name: "Edytuj kartę" })).toHaveAttribute(
      "href",
      editHref,
    );
    dl.unmount();

    mocks.user = RECRUITER_USER;
    renderCard({ editHref });
    await screen.findByText(HEADER);
    expect(screen.queryByRole("link", { name: "Edytuj kartę" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("client-playbook-edit")).not.toBeInTheDocument();
  });

  it("onEdit zamiast editHref renderuje przyciski, nie linki", async () => {
    const onEdit = vi.fn();

    const full = renderCard({ onEdit });
    await screen.findByText(HEADER);
    const edit = screen.getByTestId("client-playbook-edit");
    expect(edit.tagName).toBe("BUTTON");
    expect(screen.queryByRole("link", { name: "Edytuj kartę" })).not.toBeInTheDocument();
    fireEvent.click(edit);
    expect(onEdit).toHaveBeenCalledTimes(1);
    full.unmount();

    routeGet({
      [PLAYBOOK_URL]: () => makeEmptyClientPlaybook(1, "Nordea Bank Abp"),
      [CV_RULE_URL]: () => makeCvRule(),
    });
    renderCard({ onEdit });
    const cta = await screen.findByRole("button", { name: "Załóż kartę" });
    expect(screen.queryByRole("link", { name: "Załóż kartę" })).not.toBeInTheDocument();
    fireEvent.click(cta);
    expect(onEdit).toHaveBeenCalledTimes(2);
  });
});
