import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvRuleEditor } from "@/components/cv-rules/CvRuleEditor";
import { makeClientPlaybook } from "@/test/fixtures/client-playbook";
import { makeCvRule } from "@/test/fixtures/cv-rule";

/**
 * Edytor reguły — pełna recepta DL w sześciu zakładkach.
 *
 * Cztery kontrakty, które łatwo cofnąć „przy okazji":
 *  * zakładka „Karta klienta" montuje się LENIWIE (edytor otwierany dla reguły
 *    nie strzela po kartę) i po pierwszym wejściu jest tylko chowana — szkic
 *    karty przeżywa przełączenie zakładki; na niej nie ma stopki reguły;
 *  * „Zapisz i zatwierdź" wysyła `confirm: true` i KOMPLET pól (blokady,
 *    polityka, słownik, flagi klienta) — pominięte pole w payloadzie
 *    oznaczałoby ciche wyzerowanie go na serwerze;
 *  * blokada trybu i wymagane wejścia są edytowalne w zakładce Generator;
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
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/clients/5/cv-rule") return { data: RULE };
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

  it("„Zapisz i zatwierdź” wysyła komplet pól z confirm=true, w tym blokady i słownik", async () => {
    const onChanged = renderEditor();
    expect(await screen.findByText("Reguły CV · wersja 1")).toBeInTheDocument();

    // Generator: zablokuj tryb + wymagany numer projektu.
    switchTab("Generator");
    fireEvent.click(await screen.findByRole("radio", { name: "Zawsze ten tryb" }));
    fireEvent.change(screen.getByLabelText("Tryb obróbki treści"), {
      target: { value: "basic" },
    });
    fireEvent.click(screen.getByLabelText("Wymagany numer / nazwa projektu"));

    // Treść: sekcja do pominięcia + słownik.
    switchTab("Treść i AI");
    fireEvent.click(await screen.findByLabelText("Języki"));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj parę" }));
    fireEvent.change(screen.getByLabelText("Słownik 1: z"), {
      target: { value: "Business Analyst" },
    });
    fireEvent.change(screen.getByLabelText("Słownik 1: na"), {
      target: { value: "Analityk Biznesowy" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz i zatwierdź" }));

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
    switchTab("Treść i AI");
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
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith("/api/clients/5/cv-rule"));
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
    expect(screen.queryByRole("button", { name: "Zapisz i zatwierdź" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz kartę" })).toBeInTheDocument();

    fireEvent.change(sla, { target: { value: "9" } });
    switchTab("Podstawy");
    expect(screen.getByRole("button", { name: "Zapisz i zatwierdź" })).toBeInTheDocument();
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
    expect(screen.getByRole("tab", { name: "Podstawy" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
