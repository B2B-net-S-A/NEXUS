import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvRuleEditor } from "@/components/cv-rules/CvRuleEditor";
import { makeClientPlaybook } from "@/test/fixtures/client-playbook";
import { makeCvRule } from "@/test/fixtures/cv-rule";

/**
 * Edytor reguły — pełna recepta DL w czterech zakładkach (Ustawienia, Podgląd,
 * Karta klienta, Historia) z progresywnym odsłanianiem.
 *
 * Cztery kontrakty, które łatwo cofnąć „przy okazji":
 *  * zakładka „Karta klienta" montuje się LENIWIE (edytor otwierany dla reguły
 *    nie strzela po kartę) i po pierwszym wejściu jest tylko chowana — szkic
 *    karty przeżywa przełączenie zakładki; na niej nie ma stopki reguły;
 *  * „Zapisz i włącz regułę" wysyła `confirm: true` i KOMPLET pól (blokady,
 *    polityka, słownik, flagi klienta) — pominięte pole w payloadzie
 *    oznaczałoby ciche wyzerowanie go na serwerze;
 *  * blokada trybu i wymagane wejścia są edytowalne w zwiniętej sekcji
 *    „Zaawansowane" w zakładce „Ustawienia";
 *  * lint woła osobny endpoint i pokazuje werdykt per linia.
 */

const mocks = vi.hoisted(() => ({
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

const RULE = makeCvRule({
  client_id: 5,
  edit_revision: 4,
  client_name: "KIR",
  generator_instructions: "Bez sekcji zainteresowań.",
});

/** Radix Tabs aktywują się na mousedown, nie na click — samo `click` w jsdom
 * nie przełącza zakładki. */
function switchTab(name: string) {
  const tab = screen.getByRole("tab", { name });
  fireEvent.mouseDown(tab);
  fireEvent.click(tab);
}

function renderEditor(onChanged = vi.fn(), initialTab?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <CvRuleEditor
        clientId={5}
        allowDelete
        onChanged={onChanged}
        initialTab={initialTab}
      />
    </QueryClientProvider>,
  );
  return Object.assign(onChanged, { unmount: view.unmount });
}

describe("CvRuleEditor", () => {
  // Scalona zakładka „Ustawienia" renderuje komplet pól naraz (dawniej rozbite
  // na trzy zakładki), więc każdy `fireEvent` przerenderowuje cięższy DOM. Pod
  // obciążeniem CI te integracyjne scenariusze RTL przekraczają domyślne 5 s —
  // to koszt jsdom, nie feature'a. Wspólny, hojny limit dla całego pliku.
  vi.setConfig({ testTimeout: 20000 });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/clients/5/cv-rule") return { data: RULE };
      if (url === "/api/clients/5/cv-rule/versions") return { data: [] };
      if (url === "/api/clients/5/cv-rule/history") return { data: [] };
      if (url === "/api/clients/5/cv-rule/feedback")
        return {
          data: {
            days: 90,
            generated_total: 0,
            with_skipped_instructions: 0,
            with_policy_enforced: 0,
            skipped_by_instruction: [],
            recent: [],
          },
        };
      if (url === "/api/clients/5/cv-rule/prompt-preview")
        return { data: { language: "pl", block: "<client_presentation_rules>\nx\n</client_presentation_rules>", is_active: true } };
      if (url === "/api/clients-lookup") return { data: [] };
      if (url === "/api/clients/5/playbook")
        return { data: makeClientPlaybook({ client_id: 5 }) };
      if (url === "/api/clients/5/playbook/history") return { data: [] };
      throw new Error(`unexpected GET ${url}`);
    });
    mocks.put.mockImplementation(async (_url: string, body: Record<string, unknown>) => ({
      data: makeCvRule({ ...RULE, ...(body as object), version: 2 }),
    }));
  });

  it("„Zapisz i włącz regułę” wysyła komplet pól z confirm=true, w tym blokady i słownik", async () => {
    const onChanged = renderEditor();
    expect(await screen.findByText("Reguły CV · wersja 1")).toBeInTheDocument();

    // Blokady, polityka i słownik siedzą pod zwiniętym „Zaawansowane".
    fireEvent.click(screen.getByRole("button", { name: /Zaawansowane/ }));

    // Zablokuj tryb + wymagany numer projektu.
    fireEvent.click(await screen.findByRole("radio", { name: "Zawsze ten tryb" }));
    fireEvent.change(screen.getByLabelText("Tryb obróbki treści"), {
      target: { value: "basic" },
    });
    fireEvent.click(screen.getByLabelText("Wymagany numer / nazwa projektu"));

    // Sekcja do pominięcia + słownik.
    fireEvent.click(screen.getByLabelText("Języki"));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj parę" }));
    fireEvent.change(screen.getByLabelText("Słownik 1: z"), {
      target: { value: "Business Analyst" },
    });
    fireEvent.change(screen.getByLabelText("Słownik 1: na"), {
      target: { value: "Analityk Biznesowy" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i włącz regułę" }));

    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.put.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/api/clients/5/cv-rule");
    expect(body.confirm).toBe(true);
    expect(body.content_mode).toBe("basic");
    expect(body.content_mode_locked).toBe(true);
    expect(body.require_project_ref).toBe(true);
    expect(body.omit_sections).toEqual(["languages"]);
    expect(body.glossary).toEqual([{ from: "Business Analyst", to: "Analityk Biznesowy" }]);
    expect(body.generator_instructions).toBe("Bez sekcji zainteresowań.");
    expect(body.cv_interactive_enabled).toBe(true);
    expect(body).toHaveProperty("cv_content_mode_cap", null);
    expect(await screen.findByText(/Zapisano i zatwierdzono \(wersja 2\)/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("edytuje zapisany szkic i zachowuje informację o działającej wersji", async () => {
    const draft = { filename_pattern: "SZKIC_{IMIE_NAZWISKO}", cv_language: "pl" as const };
    mocks.get.mockResolvedValueOnce({ data: makeCvRule({ ...RULE, draft_payload: draft }) });
    mocks.put.mockResolvedValueOnce({ data: makeCvRule({ ...RULE, edit_revision: 5, draft_payload: draft }) });
    renderEditor();
    expect(await screen.findByDisplayValue("SZKIC_{IMIE_NAZWISKO}")).toBeInTheDocument();
    expect(screen.getByText("Obowiązuje v1 · edytujesz szkic")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ confirm: false, expected_revision: 4 });
    expect(await screen.findByText(/Generator nadal stosuje opublikowaną wersję 1/)).toBeInTheDocument();
  });

  it("zachowuje lokalne pola po konflikcie wersji", async () => {
    mocks.put.mockRejectedValueOnce(new Error("Reguła została zmieniona przez inną osobę."));
    renderEditor();
    const input = await screen.findByLabelText("Wzór nazwy pliku CV");
    fireEvent.change(input, { target: { value: "MOJE_{IMIE_NAZWISKO}" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    expect(await screen.findByText("Reguła została zmieniona przez inną osobę.")).toBeInTheDocument();
    expect(input).toHaveValue("MOJE_{IMIE_NAZWISKO}");
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ expected_revision: 4 });
  });

  it("przywraca publikację do szkicu z kontrolą wersji", async () => {
    const get = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation(async (url: string) => url.endsWith("/versions")
      ? { data: [{ version: 1, published_at: "2026-09-01T12:00:00Z" }] }
      : get(url));
    mocks.post.mockResolvedValueOnce({ data: makeCvRule({ ...RULE, edit_revision: 5,
      draft_payload: { filename_pattern: "PRZYWROCONY_{IMIE_NAZWISKO}" } }) });
    renderEditor(vi.fn(), "history");
    fireEvent.click(await screen.findByRole("button", { name: "Przywróć do szkicu" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
      "/api/clients/5/cv-rule/versions/1/restore", null, { params: { expected_revision: 4 } },
    ));
    expect(await screen.findByDisplayValue("PRZYWROCONY_{IMIE_NAZWISKO}")).toBeInTheDocument();
    expect(screen.getByText(/Wersję 1 przywrócono do szkicu/)).toBeInTheDocument();
  });

  it("lint woła endpoint i pokazuje werdykt per linia", async () => {
    mocks.post.mockResolvedValue({
      data: {
        findings: [
          {
            field: "generator_instructions",
            index: 0,
            line: "Bez sekcji zainteresowań.",
            verdict: "ok",
            reason: "Reguła prezentacji.",
            suggestion: "",
          },
          {
            field: "generator_instructions",
            index: 1,
            line: "Dopisz Kubernetes.",
            verdict: "adds_facts",
            reason: "Każe dopisać technologię.",
            suggestion: "Jeśli kandydat ma Kubernetes, umieść go wyżej.",
          },
        ],
        ok_count: 1,
        adds_facts_count: 1,
        unclear_count: 0,
      },
    });
    renderEditor();
    await screen.findByText("Reguły CV · wersja 1");
    // Lint jest w zakładce „Ustawienia" (domyślnej) i zawsze widoczny.
    fireEvent.click(await screen.findByRole("button", { name: /Sprawdź instrukcje/ }));

    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/clients/5/cv-rule/lint",
        {
          generator_instructions: "Bez sekcji zainteresowań.",
          generator_instructions_en: null,
          notes: null,
        },
        expect.anything(),
      ),
    );
    expect(await screen.findByText(/dopisuje fakty — zostanie zignorowana/)).toBeInTheDocument();
    expect(screen.getByText(/1 OK · 1 do przepisania/)).toBeInTheDocument();
    expect(screen.getByText(/Jeśli kandydat ma Kubernetes/)).toBeInTheDocument();
  });

  it("usuwanie ma dwustopniowe potwierdzenie w komponencie", async () => {
    mocks.delete.mockResolvedValue({});
    renderEditor();
    await screen.findByText("Reguły CV · wersja 1");
    fireEvent.click(screen.getByRole("button", { name: "Usuń regułę" }));
    expect(mocks.delete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Tak, usuń" }));
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith("/api/clients/5/cv-rule", { params: { expected_revision: 4 } }));
  });

  it("zakładka „Karta klienta” montuje się dopiero po wejściu i zachowuje szkic po przełączeniu", async () => {
    renderEditor();
    await screen.findByText("Reguły CV · wersja 1");
    // Leniwie: edytor otwarty dla reguły nie strzela po kartę.
    expect(mocks.get).not.toHaveBeenCalledWith("/api/clients/5/playbook");

    switchTab("Karta klienta");
    const sla = await screen.findByLabelText("SLA: dni robocze na pierwszego kandydata");
    expect(mocks.get).toHaveBeenCalledWith("/api/clients/5/playbook");
    // Na zakładce karty jedynym zapisem jest „Zapisz kartę".
    expect(screen.queryByRole("button", { name: "Zapisz i włącz regułę" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz kartę" })).toBeInTheDocument();

    fireEvent.change(sla, { target: { value: "9" } });
    switchTab("Ustawienia");
    expect(screen.getByRole("button", { name: "Zapisz i włącz regułę" })).toBeInTheDocument();
    switchTab("Karta klienta");
    // Szkic przeżył przełączenie — zakładka była chowana, nie odmontowana.
    expect(screen.getByLabelText("SLA: dni robocze na pierwszego kandydata")).toHaveValue(9);
    expect(mocks.get.mock.calls.filter(([url]) => url === "/api/clients/5/playbook")).toHaveLength(1);
  });

  it("initialTab otwiera edytor na wskazanej zakładce, nieznana wartość wraca na Podstawy", async () => {
    const first = renderEditor(vi.fn(), "playbook");
    await screen.findByText("Reguły CV · wersja 1");
    expect(screen.getByRole("tab", { name: "Karta klienta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByLabelText("SLA: dni robocze na pierwszego kandydata")).toBeInTheDocument();
    first.unmount();

    renderEditor(vi.fn(), "nope");
    await screen.findByText("Reguły CV · wersja 1");
    expect(screen.getByRole("tab", { name: "Ustawienia" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
