import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const copyTextToClipboard = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));
vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (...a: unknown[]) => copyTextToClipboard(...a),
}));

import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import type { QcResult } from "@/lib/api/cvQc";
import { useAuthStore } from "@/store/auth";

function result(over: Partial<QcResult> = {}): QcResult {
  return {
    stage_id: 7,
    candidate_id: 21,
    candidate_name: "Anna Kowalczyk",
    job_id: 31,
    job_title: "Senior Java Developer",
    client_name: "PKO BP",
    passed: false,
    blocking_failed: 2,
    warnings_count: 1,
    override: null,
    run_id: 1,
    computed_at: "2026-09-24T10:00:00Z",
    cv: {
      source: "branded_draft",
      editable: true,
      stage_id: 7,
      generated_document_id: 5,
      document_id: null,
      filename: null,
      bold_known: true,
      updated_at: "2026-09-24T09:00:00Z",
      blocks: [
        { kind: "h", section: "summary", runs: [{ t: "Podsumowanie", b: false }] },
        { kind: "p", section: null, runs: [{ t: "Na co dzień ", b: false }, { t: "Java", b: true }, { t: ", Kafka i <script>x</script>.", b: false }] },
        { kind: "p", section: "role", runs: [{ t: "ING Tech — Java Developer", b: true }] },
        { kind: "li", section: null, runs: [{ t: "Moduł przelewów SEPA.", b: false }] },
      ],
    },
    original_cv: { source: "snapshot", filename: "cv.pdf", text: "…" },
    client_request: { must: ["Java", "Kafka"], nice: [] },
    checks: [
      { key: "must_in_cv", label: "Wszystkie must-have są w CV", severity: "blocking", status: "pass", summary: "2/2", items: [] },
      {
        key: "must_bolded",
        label: "Must-have pogrubione wszędzie",
        severity: "blocking",
        status: "fail",
        summary: "1 miejsce",
        items: [{ requirement: "Kafka", term: "Kafka", fix: "bold_all" }],
      },
      {
        key: "must_in_roles",
        label: "Must-have w każdym stanowisku",
        severity: "blocking",
        status: "fail",
        summary: "1 brak",
        items: [{ requirement: "Java", role: "ING Tech — Java Developer", fix: "ai" }],
      },
      {
        key: "no_unsupported",
        label: "Nic bez pokrycia w oryginale",
        severity: "blocking",
        status: "pass",
        summary: "OK",
        items: [],
      },
      {
        key: "spelling",
        label: "Pisownia technologii",
        severity: "warning",
        status: "fail",
        summary: "1 miejsce",
        items: [{ term: "Postgres", fix: "spelling" }],
      },
    ],
    ...over,
  };
}

function renderDialog(onChanged = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <CvQcDialog stageId={7} open onClose={vi.fn()} onChanged={onChanged} />
    </QueryClientProvider>,
  );
  return { qc, invalidate, onChanged };
}

describe("CvQcDialog — QC CV", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "recruiter" } } as never);
    get.mockImplementation((url: string) =>
      url === "/api/pipeline/stages/7/qc" ? Promise.resolve({ data: result() }) : Promise.reject(new Error(url)),
    );
  });

  it("werdykt, dwie grupy i CV jako tekst z zaznaczeniem braków", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Nie przechodzi · 2 blokujące")).toBeTruthy();
    const blocking = within(dialog).getByRole("region", { name: "Blokujące — bez nich CV nie wyjdzie" });
    expect(within(blocking).getByText("2 z 4 nie przechodzi")).toBeTruthy();
    expect(within(blocking).getByText("Must-have pogrubione wszędzie")).toBeTruthy();
    const warnings = within(dialog).getByRole("region", { name: "Uwagi — nie blokują" });
    expect(within(warnings).getByText("Pisownia technologii")).toBeTruthy();

    const cv = within(dialog).getByRole("article", { name: "CV firmowe" });
    // Treść CV to tekst — znacznik z CV nie staje się elementem.
    expect(cv.querySelector("script")).toBeNull();
    expect(cv).toHaveTextContent("<script>x</script>");
    // Niepogrubiona Kafka na żółto, stanowisko z brakiem Javy z czerwoną krawędzią.
    expect(within(cv).getByText("Kafka").tagName).toBe("MARK");
    expect(cv.querySelector('[data-qc-gap="true"]')).toHaveTextContent("ING Tech — Java Developer");
    expect(within(dialog).getByRole("link", { name: /Otwórz w edytorze CV/ })).toHaveAttribute(
      "href",
      "/jobs/31?candidate=21&panel=cv",
    );
  });

  it("„Pogrub wszystkie” podmienia wynik w cache i odświeża Tablicę oraz kolejki", async () => {
    post.mockResolvedValue({ data: result({ passed: true, blocking_failed: 0, checks: result().checks.map((c) => ({ ...c, status: "pass", items: [] })) }) });
    const { invalidate, onChanged } = renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Pogrub wszystkie" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/stages/7/qc/apply", { action: "bold_all", scope: "must" }),
    );
    expect(await within(dialog).findByText("QC przechodzi")).toBeTruthy();
    expect(get).toHaveBeenCalledTimes(1);
    expect(onChanged).toHaveBeenCalled();
    const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys).toEqual(expect.arrayContaining(['["kanban","31"]', '["kanban",31]', '["board-tasks"]']));
  });

  it("propozycje AI: pogrubienie z `**`, źródło, zastosowanie po edycji", async () => {
    post.mockImplementation((url: string) =>
      url.endsWith("/qc/fixes")
        ? Promise.resolve({
            data: {
              status: "ok",
              cached: false,
              fixes: [
                {
                  id: "f1",
                  check_key: "must_in_roles",
                  requirement: "Java",
                  role: "ING Tech — Java Developer",
                  current_text: "Moduł przelewów SEPA.",
                  proposed_text: "Moduł przelewów SEPA w **Java 11**.",
                  source: "original",
                  source_quote: "SEPA transfers module (Java 11)",
                },
              ],
            },
          })
        : Promise.resolve({ data: result() }),
    );
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    const ai = await within(dialog).findByRole("region", { name: "Propozycje AI" });
    await userEvent.click(within(ai).getByRole("button", { name: /Zaproponuj poprawki \(AI\)/ }));
    const proposal = await within(ai).findByRole("listitem", { name: "Propozycja: Java" });
    expect(within(proposal).getByText("Java 11").tagName).toBe("STRONG");
    expect(proposal).toHaveTextContent("Źródło: oryginalne CV — SEPA transfers module (Java 11)");

    await userEvent.click(within(proposal).getByRole("button", { name: "Edytuj" }));
    const field = within(proposal).getByRole("textbox", { name: "Treść poprawki" });
    await userEvent.clear(field);
    await userEvent.type(field, "Moduł SEPA w Java 11.");
    await userEvent.click(within(proposal).getByRole("button", { name: "Zastosuj edycję" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/stages/7/qc/apply", {
        action: "ai_fix",
        fix_id: "f1",
        text: "Moduł SEPA w Java 11.",
      }),
    );
    await waitFor(() => expect(within(ai).queryByRole("listitem", { name: "Propozycja: Java" })).toBeNull());
  });

  it("CV spoza NEXUSA (409 CV_NOT_EDITABLE) → komunikat i poprawki wyłączone", async () => {
    post.mockRejectedValue({
      response: { status: 409, data: { detail: { code: "CV_NOT_EDITABLE", message: "x" } } },
    });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Pogrub wszystkie" }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith(expect.stringMatching(/plikiem Word\/PDF spoza NEXUSA/)));
    expect(within(dialog).getByRole("button", { name: "Pogrub wszystkie" })).toBeDisabled();
  });

  it("CV z pliku (`editable: false`) — informacja od razu, bez propozycji AI", async () => {
    get.mockResolvedValue({
      data: result({ cv: { ...result().cv!, source: "document", editable: false, filename: "Anna_B2B.pdf", bold_known: false } }),
    });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect((await within(dialog).findAllByText(/plikiem Word\/PDF spoza NEXUSA/)).length).toBeGreaterThan(0);
    expect(within(dialog).getByRole("button", { name: "Pogrub wszystkie" })).toBeDisabled();
    expect(within(dialog).getByRole("region", { name: "Propozycje AI" })).toHaveTextContent(/spoza NEXUSA/);
    for (const button of within(dialog).queryAllByRole("button", { name: /Zaproponuj poprawki/ })) {
      expect(button).toBeDisabled();
    }
    expect(post).not.toHaveBeenCalled();
  });

  it("„Przepuść mimo QC” tylko dla DL i admina, z powodem min. 10 znaków", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Nie przechodzi · 2 blokujące");
    expect(within(dialog).queryByRole("region", { name: "Przepuść mimo QC" })).toBeNull();
  });

  it("Delivery Lead przepuszcza z powodem — wynik z `override`", async () => {
    useAuthStore.setState({ user: { id: 2, role: "delivery_lead" } } as never);
    post.mockResolvedValue({
      data: result({ override: { reason: "Klient prosił o skrót", by_name: "Piotr Zając", at: "2026-09-24T10:00:00Z" } }),
    });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    const form = await within(dialog).findByRole("region", { name: "Przepuść mimo QC" });
    const submit = within(form).getByRole("button", { name: "Przepuść z powodem" });
    await userEvent.type(within(form).getByRole("textbox"), "za krótko");
    expect(submit).toBeDisabled();
    await userEvent.type(within(form).getByRole("textbox"), " — klient prosił");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/stages/7/qc/override", {
        reason: "za krótko — klient prosił",
      }),
    );
    expect(await within(dialog).findByText("Przepuszczone mimo QC")).toBeTruthy();
    expect(within(dialog).queryByRole("region", { name: "Przepuść mimo QC" })).toBeNull();
  });

  it("pytanie do kandydata idzie do schowka, nic nie jest wysyłane", async () => {
    get.mockResolvedValue({
      data: result({
        checks: [
          {
            key: "no_unsupported",
            label: "Nic bez pokrycia w oryginale",
            severity: "blocking",
            status: "fail",
            summary: "1 pozycja",
            items: [{ term: "Docker", role: "Allegro", fix: "ask_candidate" }],
          },
        ],
      }),
    });
    copyTextToClipboard.mockResolvedValue(false);
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Skopiuj pytanie do kandydata/ }));
    await waitFor(() => expect(copyTextToClipboard).toHaveBeenCalledWith("Czy używał(a) Docker w Allegro?"));
    expect(showError).toHaveBeenCalledWith(expect.stringContaining("Czy używał(a) Docker w Allegro?"));
    expect(post).not.toHaveBeenCalled();
  });

  it("awaria odczytu nie jest pustką — komunikat i „Ponów”", async () => {
    get.mockRejectedValue({ response: { status: 500, data: {} } });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Nie udało się policzyć QC. Spróbuj ponownie.")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Ponów" })).toBeTruthy();
  });
});
