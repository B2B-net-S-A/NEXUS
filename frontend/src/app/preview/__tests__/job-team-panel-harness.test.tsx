/**
 * Harness `/preview/job-team-panel` (decyzja Artura 02.10.2026): zakładka
 * „Zespół” dla trzech rekrutacji i trzech osób.
 *
 * Test montuje CAŁĄ stronę harnessu na prawdziwej warstwie API i sprawdza dwie
 * rzeczy, których strażnik czytający źródła nie widzi: że żadne żądanie nie
 * dochodzi do sieci (także po kliknięciach) i że każda osoba widzi swoje
 * przyciski — Delivery Lead nie rozstrzyga propozycji automatu, Head of
 * Recruitment sam rekrutacji nie bierze, rekruter nikogo nie przydziela.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Axios,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ search: "" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/job-team-panel",
}));
// Zakładka „Zespół” ich nie montuje, a ciągną za sobą pół aplikacji.
vi.mock("@/components/AppShell", () => ({ EditJobModal: () => null }));
vi.mock("@/components/v2/modals/AddCandidatesQuickModal", () => ({
  AddCandidatesQuickModal: () => null,
}));

import { api } from "@/lib/api";
import JobTeamPanelPreviewPage from "../job-team-panel/page";

/** Żądania, które doszły do warstwy transportu — w harnessie ma ich być ZERO. */
const sent: InternalAxiosRequestConfig[] = [];
/**
 * Każda PRÓBA żądania, także odrzucona przez interceptor harnessu. Sam pusty
 * `sent` nie odróżnia „wszystko zasiane” od „niezasiane zapytanie padło po
 * cichu na interceptorze” — dlatego liczymy też próby.
 */
const attempts = vi.spyOn(Axios.prototype, "request");
const attemptedUrls = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

beforeAll(() => {
  const adapter: AxiosAdapter = async (config) => {
    sent.push(config);
    return { data: {}, status: 200, statusText: "OK", headers: {}, config } as AxiosResponse;
  };
  api.defaults.adapter = adapter;
});

afterEach(() => {
  sent.length = 0;
  attempts.mockClear();
});

async function renderAs(persona: "dl" | "hor" | "recruiter" | null) {
  nav.search = persona ? `as=${persona}` : "";
  render(<JobTeamPanelPreviewPage />);
  await screen.findByRole("heading", { name: "Podgląd: zakładka „Zespół” rekrutacji" });
  return {
    proposal: screen.getByRole("region", { name: "Propozycja automatu" }),
    staffed: screen.getByRole("region", { name: "Rekruter i druga osoba" }),
    empty: screen.getByRole("region", { name: "Bez rekrutera" }),
  };
}

/** Nazwy przycisków wiersza „Rekruter” w danej rekrutacji. */
function recruiterActions(section: HTMLElement): string[] {
  return within(within(section).getByTestId("job-recruiters"))
    .queryAllByRole("button")
    .map((button) => (button.getAttribute("aria-label") ?? button.textContent ?? "").trim());
}

describe("/preview/job-team-panel", () => {
  it("domyślnie patrzy Delivery Lead: przydziela i dokłada ludzi, propozycji automatu nie rozstrzyga", async () => {
    const { proposal, staffed, empty } = await renderAs(null);

    expect(screen.getByRole("link", { name: "Delivery Lead" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(recruiterActions(proposal)).toEqual(["Przypisz…", "Biorę"]);
    expect(within(proposal).getByText("Czeka na akceptację Head of Recruitment")).toBeInTheDocument();
    expect(recruiterActions(staffed)).toEqual([
      "Zdejmij Bartek Testowy",
      "Zdejmij Celina Wzorcowa",
      "Dołącz",
      "Zmień rekrutera",
      "+ Dodaj osobę",
    ]);
    expect(recruiterActions(empty)).toEqual(["Przypisz…", "Biorę"]);
    // Delivery Lead zmienia też swoje pole, termin i priorytet.
    expect(within(staffed).getByRole("button", { name: "Zmień: Termin" })).toBeInTheDocument();
    expect(within(staffed).getByRole("radiogroup", { name: "Priorytet" })).toBeInTheDocument();
  });

  it("Head of Recruitment: Akceptuj / Zmień / Odrzuć i „Przypisz…”, bez „Biorę”", async () => {
    const { proposal, staffed, empty } = await renderAs("hor");

    expect(recruiterActions(proposal)).toEqual([
      "Akceptuj",
      "Zmień propozycję: Anna Przykładowa",
      "Odrzuć",
      "Przypisz…",
    ]);
    expect(recruiterActions(staffed)).toEqual([
      "Zdejmij Bartek Testowy",
      "Zdejmij Celina Wzorcowa",
      "Zmień rekrutera",
      "+ Dodaj osobę",
    ]);
    expect(recruiterActions(empty)).toEqual(["Przypisz…"]);
    // Priorytet ustawia, ale Delivery Leada i terminu nie zmienia (pełna edycja).
    expect(
      within(within(empty).getByRole("radiogroup", { name: "Priorytet" })).getByRole("radio", {
        name: "Przyjmujemy kandydatów",
      }),
    ).toBeChecked();
    expect(within(empty).queryByRole("button", { name: "Zmień: Termin" })).not.toBeInTheDocument();
  });

  it("rekruter: „Biorę” przy wolnej rekrutacji, „Dołącz” przy zajętej — bez przydzielania i bez decyzji o propozycji", async () => {
    const { proposal, staffed, empty } = await renderAs("recruiter");

    expect(recruiterActions(proposal)).toEqual(["Biorę", "+ Dodaj osobę"]);
    expect(recruiterActions(staffed)).toEqual([
      "Zdejmij Celina Wzorcowa",
      "Dołącz",
      "+ Dodaj osobę",
    ]);
    expect(recruiterActions(empty)).toEqual(["Biorę", "+ Dodaj osobę"]);
    for (const section of [proposal, staffed, empty]) {
      expect(within(section).queryByRole("radiogroup", { name: "Priorytet" })).not.toBeInTheDocument();
      expect(within(section).queryByRole("button", { name: /^Zmień: / })).not.toBeInTheDocument();
    }
    expect(within(proposal).getByText("P1 Pilne")).toBeInTheDocument();
  });

  it("trzy rekrutacje pokazują trzy stany wiersza „Kategoria” i „Rekruter”", async () => {
    const { proposal, staffed, empty } = await renderAs("hor");

    expect(await within(proposal).findByText("Development")).toBeInTheDocument();
    expect(within(staffed).getByText("przydzielił(a) Gosia D.")).toBeInTheDocument();
    expect(
      within(within(empty).getByTestId("job-recruiters")).getByText("Bez rekrutera"),
    ).toBeInTheDocument();
    expect(
      within(empty).getByText(
        "Rekrutacja nie ma kategorii, więc nikt nie zobaczy jej w „Moja kategoria”.",
      ),
    ).toBeInTheDocument();
    expect(within(empty).getByText("nie ustawiono")).toBeInTheDocument();
  });

  it.each(["dl", "hor", "recruiter"] as const)(
    "wejście jako %s nie próbuje żadnego zapytania — każdy klucz jest zasiany",
    async (persona) => {
      const { staffed } = await renderAs(persona);
      await within(staffed).findByText("Development");

      expect(attemptedUrls()).toEqual([]);
      expect(sent).toEqual([]);
    },
  );

  it("listy otwierane kliknięciem też czytają zasiew, nie sieć", async () => {
    const user = userEvent.setup();
    const { proposal, staffed } = await renderAs("hor");

    // Osoby z kategorii: liczba znana z zasiewu, lista po rozwinięciu.
    await user.click(within(staffed).getByRole("button", { name: "4 osoby z kategorii" }));
    const people = await within(staffed).findByRole("list", { name: "Osoby z kategorii" });
    expect(within(people).getAllByRole("listitem")).toHaveLength(4);

    // „+ Dodaj osobę” i „Zmień” przy propozycji — ten sam katalog osób.
    await user.click(within(staffed).getByRole("button", { name: "+ Dodaj osobę" }));
    expect(await screen.findByRole("option", { name: /Anna Przykładowa/ })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.click(
      within(proposal).getByRole("button", { name: "Zmień propozycję: Anna Przykładowa" }),
    );
    expect(await screen.findByRole("option", { name: /Darek Makietowy/ })).toBeInTheDocument();
    await user.keyboard("{Escape}");

    // Lista Delivery Leadów w wierszu „Delivery Lead” (Head of Recruitment jej
    // nie edytuje, ale nazwisko czyta z tego samego zasiewu).
    expect(within(staffed).getByText("Gosia Delivery")).toBeInTheDocument();

    expect(attemptedUrls()).toEqual([]);
    expect(sent).toEqual([]);
  });

  it("przyciski niczego nie zapisują: żądanie odpada na interceptorze harnessu, zanim trafi do sieci", async () => {
    const user = userEvent.setup();
    const { proposal } = await renderAs("recruiter");

    await user.click(within(proposal).getByRole("button", { name: "Biorę" }));

    expect(await screen.findByText("Nie udało się wziąć rekrutacji.")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(proposal).getByRole("button", { name: "Biorę" })).toBeEnabled(),
    );
    // Próba była (kliknięcie działa)…
    expect(attemptedUrls()).toEqual(["POST /api/jobs/101/claim"]);
    // …ale do transportu nie doszło nic.
    expect(sent).toEqual([]);
  });
});
