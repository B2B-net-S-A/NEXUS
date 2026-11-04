/**
 * Stan publikacji ogłoszenia na portalach: „do aktualizacji” po zmianie treści,
 * „zdjęte z portalu” z potwierdzeniem, przypomnienie przy zamkniętej rekrutacji
 * i odświeżenie kolumny „Ogłoszenia” listy.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

const clipboard = vi.hoisted(() => ({
  copyTextToClipboard: vi.fn(async () => true),
  copyHtmlToClipboard: vi.fn(async () => true),
}));
vi.mock("@/lib/clipboard", () => clipboard);

import { jobAdQueryKey, type JobAdState } from "@/lib/api/jobAd";
import { jobsListQueryKey } from "@/components/v2/pages/JobsListV2";

import { AdPublications, JOBS_LIST_QUERY_ROOT, type AdPublicationsApi } from "../AdPublications";
import { adState, CLIENT_FINDING, EMPTY_STATE, PRACUJ_URL, publication } from "./job-ad-fixtures";

function setup(state: JobAdState, options: { jobClosed?: boolean; fail?: unknown } = {}) {
  const api = {
    markPublished: vi.fn<AdPublicationsApi["markPublished"]>(async (_jobId, portal, url) => {
      if (options.fail) throw options.fail;
      return adState({ publications: [publication({ portal, url })] });
    }),
    markRemoved: vi.fn<AdPublicationsApi["markRemoved"]>(async (_jobId, portal) =>
      adState({ publications: [publication({ portal, removed_at: "2026-10-13T09:30:00Z" })] }),
    ),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <AdPublications
        jobId={7}
        portals={["pracuj", "jjit"]}
        state={state}
        jobClosed={options.jobClosed}
        api={api}
      />
    </QueryClientProvider>,
  );
  return { api, client, invalidate };
}

const row = (name: string) => screen.getByRole("listitem", { name: `Publikacja: ${name}` });

beforeEach(() => vi.clearAllMocks());

describe("AdPublications", () => {
  it("pokazuje oba portale w stałej kolejności", () => {
    setup(adState({ publications: [publication({ portal: "jjit", url: null })] }));
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((item) => item.getAttribute("aria-label"))).toEqual([
      "Publikacja: Pracuj.pl",
      "Publikacja: JustJoin.IT",
    ]);
    expect(row("JustJoin.IT")).toHaveTextContent("Opublikowane");
    expect(row("JustJoin.IT")).toHaveTextContent("bez linku");
    expect(within(row("JustJoin.IT")).getByRole("button", { name: "Dodaj link" })).toBeEnabled();
  });

  it("JustJoin.IT bez publikacji mówi, że wstawia się go ręcznie, i kopiuje opis", async () => {
    // Zgłoszenie 28.10.2026: „na jj muszę wchodzić i dodawać? nie widzę przycisku”.
    setup(adState());
    const card = row("JustJoin.IT");
    expect(card).toHaveTextContent("Ogłoszenie wstawiasz w panelu pracodawcy JustJoin.IT");
    fireEvent.click(within(card).getByRole("button", { name: "Kopiuj opis JustJoin.IT" }));
    await waitFor(() =>
      expect(clipboard.copyHtmlToClipboard).toHaveBeenCalledWith("<p>opis html</p>", "opis tekst"),
    );
    expect(
      await within(card).findByRole("button", { name: "Skopiowane" }),
    ).toBeInTheDocument();
    expect(row("Pracuj.pl")).not.toHaveTextContent("panelu pracodawcy");
  });

  it("opis JustJoin.IT z fragmentem blokującym się nie kopiuje", () => {
    setup(adState({ findings: [CLIENT_FINDING] }));
    expect(
      within(row("JustJoin.IT")).getByRole("button", { name: "Kopiuj opis JustJoin.IT" }),
    ).toBeDisabled();
  });

  it("bez przygotowanego ogłoszenia nie ma czego oznaczać", () => {
    setup(EMPTY_STATE);
    const button = within(row("Pracuj.pl")).getByRole("button", {
      name: "Oznacz jako opublikowane",
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Najpierw przygotuj ogłoszenie.");
  });

  it("po zmianie treści „Zaktualizowane na portalu” potwierdza tym samym linkiem", async () => {
    const { api, client, invalidate } = setup(
      adState({ publications: [publication({ outdated: true })] }),
    );
    expect(row("Pracuj.pl")).toHaveTextContent("do aktualizacji");
    fireEvent.click(
      within(row("Pracuj.pl")).getByRole("button", { name: "Zaktualizowane na portalu" }),
    );

    await waitFor(() =>
      expect(api.markPublished).toHaveBeenCalledWith(7, "pracuj", PRACUJ_URL, true),
    );
    // Okno i sekcja czytają ten sam wpis cache, a lista odświeża kolumnę.
    await waitFor(() =>
      expect(client.getQueryData<JobAdState>(jobAdQueryKey(7))?.publications[0].outdated).toBe(
        false,
      ),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [JOBS_LIST_QUERY_ROOT] });
  });

  it("dopisanie linku nie potwierdza treści — nawet gdy treść ma fragment blokujący", async () => {
    const { api } = setup({
      ...adState({ publications: [publication({ url: null, outdated: true })] }),
      can_copy: false,
    });
    // Potwierdzić treści z blokadą nie wolno…
    expect(
      within(row("Pracuj.pl")).getByRole("button", { name: "Zaktualizowane na portalu" }),
    ).toBeDisabled();
    // …ale link (np. po moderacji portalu) da się dopisać zawsze.
    fireEvent.click(within(row("Pracuj.pl")).getByRole("button", { name: "Dodaj link" }));
    fireEvent.change(within(row("Pracuj.pl")).getByRole("textbox"), {
      target: { value: PRACUJ_URL },
    });
    fireEvent.click(within(row("Pracuj.pl")).getByRole("button", { name: "Zapisz link" }));

    await waitFor(() =>
      expect(api.markPublished).toHaveBeenCalledWith(7, "pracuj", PRACUJ_URL, false),
    );
  });

  it("„Zdjęte z portalu” pyta o potwierdzenie", async () => {
    const { api } = setup(adState({ publications: [publication()] }));
    fireEvent.click(within(row("Pracuj.pl")).getByRole("button", { name: "Zdjęte z portalu" }));
    const dialog = await screen.findByRole("dialog", { name: "Ogłoszenie zdjęte z Pracuj.pl?" });
    expect(api.markRemoved).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Zdjęte z portalu" }));
    await waitFor(() => expect(api.markRemoved).toHaveBeenCalledWith(7, "pracuj"));
  });

  it("zdjęte ogłoszenie zostawia ślad i daje się oznaczyć ponownie", () => {
    setup(adState({ publications: [publication({ removed_at: "2026-10-13T09:30:00Z" })] }));
    expect(row("Pracuj.pl")).toHaveTextContent("Zdjęte z portalu");
    expect(
      within(row("Pracuj.pl")).getByRole("button", { name: "Oznacz jako opublikowane" }),
    ).toBeEnabled();
  });

  it("zamknięta rekrutacja z wiszącym ogłoszeniem przypomina o zdjęciu", () => {
    setup(adState({ publications: [publication()] }), { jobClosed: true });
    expect(row("Pracuj.pl")).toHaveTextContent(
      "Rekrutacja jest zamknięta, a ogłoszenie nadal wisi",
    );
    expect(row("JustJoin.IT")).not.toHaveTextContent("Rekrutacja jest zamknięta");
  });

  it("odmowa serwera (np. link spoza portalu) trafia do rekrutera i zostawia pole otwarte", async () => {
    setup(adState(), {
      fail: { response: { status: 422, data: { detail: "Wklej adres ogłoszenia z Pracuj.pl." } } },
    });
    fireEvent.click(
      within(row("Pracuj.pl")).getByRole("button", { name: "Oznacz jako opublikowane" }),
    );
    fireEvent.change(within(row("Pracuj.pl")).getByRole("textbox"), {
      target: { value: "https://przyklad.example/oferta" },
    });
    fireEvent.click(within(row("Pracuj.pl")).getByRole("button", { name: "Oznacz" }));

    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("Wklej adres ogłoszenia z Pracuj.pl."),
    );
    expect(within(row("Pracuj.pl")).getByRole("textbox")).toHaveValue(
      "https://przyklad.example/oferta",
    );
  });

  it("pole linku JustJoin.IT mówi, że przejdzie też link z RocketJobs", () => {
    setup(adState());
    fireEvent.click(
      within(row("JustJoin.IT")).getByRole("button", { name: "Oznacz jako opublikowane" }),
    );
    expect(
      within(row("JustJoin.IT")).getByRole("textbox", {
        name: "Link do ogłoszenia na JustJoin.IT albo RocketJobs (możesz dodać później)",
      }),
    ).toBeInTheDocument();

    fireEvent.click(
      within(row("Pracuj.pl")).getByRole("button", { name: "Oznacz jako opublikowane" }),
    );
    expect(
      within(row("Pracuj.pl")).getByRole("textbox", {
        name: "Link do ogłoszenia na Pracuj.pl (możesz dodać później)",
      }),
    ).toBeInTheDocument();
  });

  it("klucz do odświeżenia listy to pierwszy człon klucza listy rekrutacji", () => {
    const key = jobsListQueryKey({} as Parameters<typeof jobsListQueryKey>[0]);
    expect(key[0]).toBe(JOBS_LIST_QUERY_ROOT);
  });
});
