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
// Edytor CV (dynamiczny import) — zaślepka zapisuje, który dokument otwarto.
const editorProps = vi.fn();
vi.mock("next/dynamic", () => ({
  default: () => (props: Record<string, unknown>) => {
    editorProps(props);
    return <div data-testid="cv-editor" />;
  },
}));

import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import type { QcCheck, QcResult } from "@/lib/api/cvQc";
import { useAuthStore } from "@/store/auth";

const QC_URL = "/api/pipeline/stages/7/qc";

const passing = (key: string, label: string, severity: QcCheck["severity"]): QcCheck => ({
  key,
  label,
  severity,
  status: "pass",
  summary: "OK",
  items: [],
});

function result(over: Partial<QcResult> = {}): QcResult {
  return {
    stage_id: 7,
    candidate_id: 21,
    candidate_name: "Anna Kowalczyk",
    job_id: 31,
    job_title: "Senior Java Developer",
    client_name: "Bank Przykładowy",
    passed: false,
    blocking_failed: 2,
    warnings_count: 2,
    override: null,
    run_id: 1,
    computed_at: "2026-10-02T10:00:00Z",
    cv: {
      source: "branded_draft",
      editable: true,
      stage_id: 7,
      generated_document_id: 5,
      document_id: null,
      filename: null,
      bold_known: true,
      updated_at: "2026-10-02T09:00:00Z",
      blocks: [
        { kind: "h", section: "summary", runs: [{ t: "Podsumowanie", b: false }] },
        { kind: "p", section: null, runs: [{ t: "Na co dzień ", b: false }, { t: "Java", b: true }, { t: ", Kafka i <script>x</script>.", b: false }] },
        { kind: "h", section: "experience", runs: [{ t: "Doświadczenie", b: false }] },
        { kind: "p", section: "role", runs: [{ t: "Firma Alfa — Java Developer", b: true }] },
        { kind: "li", section: null, runs: [{ t: "Moduł przelewów SEPA.", b: false }] },
        { kind: "p", section: "rodo", runs: [{ t: "Wyrażam zgodę na przetwarzanie moich danych osobowych.", b: false }] },
      ],
    },
    original_cv: { source: "snapshot", filename: "cv.pdf", text: "…" },
    client_request: { must: ["Java", "Kafka"], nice: ["Docker"], critical: ["Java"], critical_source: "suggested" },
    checks: [
      passing("cv_present", "CV firmowe jest przygotowane", "blocking"),
      {
        key: "critical_skills",
        label: "Umiejętności krytyczne są w CV i opisane w rolach",
        severity: "blocking",
        status: "fail",
        summary: "0/1",
        items: [
          {
            requirement: "Java",
            role: "Firma Alfa — Java Developer",
            detail: "Brak w tej roli, a w oryginale jest.",
            fix: "ai",
            role_index: 0,
          },
        ],
      },
      {
        key: "no_unsupported",
        label: "CV nie twierdzi niczego spoza oryginału",
        severity: "blocking",
        status: "fail",
        summary: "1 do wyjaśnienia",
        items: [{ requirement: "Docker", term: "Docker", detail: "Jest w CV, a nie ma tego w oryginale.", fix: "remove_term" }],
      },
      passing("client_rules", "Reguły klienta (stawki, kontakt, zgoda RODO)", "blocking"),
      {
        key: "must_bolded",
        label: "Must-have są pogrubione",
        severity: "warning",
        status: "fail",
        summary: "1/2",
        items: [{ requirement: "Kafka", term: "Kafka", fix: "bold_all" }],
      },
      {
        key: "spelling",
        label: "Pisownia technologii",
        severity: "warning",
        status: "fail",
        summary: "1 do poprawy",
        items: [{ term: "Postgres", detail: "„Postgres” → „PostgreSQL”", fix: "spelling" }],
      },
      passing("dates", "Każda rola ma daty", "warning"),
    ],
    ...over,
  };
}

const passed = (over: Partial<QcResult> = {}): QcResult =>
  result({
    passed: true,
    blocking_failed: 0,
    checks: result().checks.map((c) => (c.severity === "blocking" ? { ...c, status: "pass", items: [] } : c)),
    ...over,
  });

function renderDialog(props: Partial<React.ComponentProps<typeof CvQcDialog>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  const onChanged = vi.fn();
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <CvQcDialog stageId={7} open onClose={onClose} onChanged={onChanged} {...props} />
    </QueryClientProvider>,
  );
  const keys = () => invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
  return { qc, keys, onChanged, onClose };
}

const serve = (data: QcResult) =>
  get.mockImplementation((url: string) => (url === QC_URL ? Promise.resolve({ data }) : Promise.reject(new Error(url))));

describe("CvQcDialog — QC CV", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "recruiter" } } as never);
    serve(result());
  });

  it("mówi, co sprawdza, i dzieli wynik na: do poprawy, warto poprawić, w porządku", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Do poprawy: 2 rzeczy")).toBeTruthy();

    const explainer = within(dialog).getByRole("region", { name: "Co sprawdza QC" });
    expect(explainer).toHaveTextContent("Umiejętności krytyczne: Java — podpowiedź z historii rekrutacji");
    expect(within(explainer).getByRole("link", { name: "profilu Championa" })).toHaveAttribute(
      "href",
      "/jobs/31?tab=champion",
    );

    const tasks = within(dialog).getByRole("region", { name: "Do poprawy przed wysłaniem" });
    expect(within(tasks).getByText("Do poprawy przed wysłaniem (2)")).toBeTruthy();
    expect(within(tasks).getByText("Java — brak opisu w 1 roli")).toBeTruthy();
    expect(within(tasks).getByText("umiejętność krytyczna")).toBeTruthy();
    expect(within(tasks).getByText("Docker — jest w CV, a nie ma tego w oryginale")).toBeTruthy();
    // Uwagi nie są rzeczami do poprawy.
    expect(within(tasks).queryByText("Must-have są pogrubione")).toBeNull();

    const notes = within(dialog).getByRole("region", { name: "Warto poprawić — nie blokuje" });
    expect(within(notes).getByText("Must-have są pogrubione")).toBeTruthy();
    expect(within(notes).getByText("Pisownia technologii")).toBeTruthy();
    expect(within(dialog).getByRole("region", { name: "W porządku" })).toHaveTextContent("W porządku (3)");
  });

  it("CV jako tekst: braki zaznaczone przy roli, klauzula RODO poza rolą", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    const cv = await within(dialog).findByRole("article", { name: "CV firmowe" });
    // Treść CV to tekst — znacznik z CV nie staje się elementem.
    expect(cv.querySelector("script")).toBeNull();
    expect(cv).toHaveTextContent("<script>x</script>");
    // Niepogrubiona Kafka na żółto, rola bez opisu umiejętności krytycznej na czerwono.
    expect(within(cv).getByText("Kafka").tagName).toBe("MARK");
    const gap = cv.querySelector('[data-qc-gap="blocking"]');
    expect(gap).toHaveTextContent("Firma Alfa — Java Developer");
    expect(gap).toHaveTextContent("Java — w oryginale jest w tej roli, tu brakuje opisu");
    // Do 02.10.2026 klauzula zgody dostawała czerwoną krawędź ostatniej roli.
    const rodo = cv.querySelector('[data-qc-rodo="true"]');
    expect(rodo).toHaveTextContent("Wyrażam zgodę");
    expect(rodo?.closest("[data-qc-gap]")).toBeNull();
  });

  it("brak opisu, który nie blokuje, ma bursztynową krawędź", async () => {
    serve(
      passed({
        checks: [
          ...passed().checks,
          {
            key: "must_in_roles",
            label: "Pozostałe wymagania opisane w rolach z oryginału",
            severity: "warning",
            status: "fail",
            summary: "1 do uzupełnienia",
            items: [{ requirement: "Kafka", role: "Firma Alfa — Java Developer", fix: "ai", role_index: 0 }],
          },
        ],
      }),
    );
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    const cv = await within(dialog).findByRole("article", { name: "CV firmowe" });
    expect(cv.querySelector('[data-qc-gap="note"]')).toHaveTextContent("(nie blokuje)");
    expect(cv.querySelector('[data-qc-gap="blocking"]')).toBeNull();
    expect(within(dialog).getByText("QC przechodzi")).toBeTruthy();
    expect(within(dialog).getByText("Nic nie blokuje wysyłki tego CV.")).toBeTruthy();
    // Zdania AI dopisuje też do uwag — sekcja zostaje mimo zaliczonego QC.
    expect(within(dialog).getByRole("region", { name: "Propozycje AI" })).toBeTruthy();
  });

  it("bez CV firmowego jedyną rzeczą do zrobienia jest wygenerowanie CV", async () => {
    serve(
      result({
        blocking_failed: 1,
        cv: null,
        checks: [
          {
            key: "cv_present",
            label: "CV firmowe jest przygotowane",
            severity: "blocking",
            status: "fail",
            summary: "Brak CV firmowego",
            items: [{ detail: "Nie ma jeszcze CV firmowego dla tej rekrutacji.", fix: "generate_cv" }],
          },
          { key: "critical_skills", label: "x", severity: "blocking", status: "skip", summary: "Brak CV", items: [] },
        ],
      }),
    );
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Do poprawy: 1 rzecz")).toBeTruthy();
    const tasks = within(dialog).getByRole("region", { name: "Do poprawy przed wysłaniem" });
    expect(within(tasks).getByText("Nie ma jeszcze CV firmowego dla tej rekrutacji.")).toBeTruthy();
    expect(within(tasks).getByRole("link", { name: "Wygeneruj CV" })).toHaveAttribute(
      "href",
      "/cv-generator?candidate_id=21&job_id=31",
    );
    expect(within(dialog).queryByRole("region", { name: "Propozycje AI" })).toBeNull();
    // Reszty nie dało się sprawdzić — nie udajemy, że jest „w porządku”.
    expect(within(dialog).getByRole("region", { name: "Nie sprawdzono" })).toHaveTextContent("Nie sprawdzono (1)");
    expect(within(dialog).queryByRole("region", { name: "W porządku" })).toBeNull();
  });

  it("rekrutacja bez umiejętności krytycznych mówi to wprost", async () => {
    serve(passed({ client_request: { must: ["Java"], nice: [], critical: [], critical_source: "none" } }));
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("region", { name: "Co sprawdza QC" })).toHaveTextContent(
      "Ta rekrutacja nie ma umiejętności krytycznych",
    );
  });

  it("„Otwórz w edytorze CV” otwiera edytor sprawdzanego CV etapu, a po zamknięciu QC liczy się od nowa (runda 10, F22)", async () => {
    // Produkcja 26.09.2026: link prowadził do panelu osoby, który dla karty
    // w „QC CV” pokazywał CV tylko do odczytu.
    serve(result({ cv: { ...result().cv!, stage_id: 5 } }));
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Otwórz w edytorze CV" }));
    expect(await screen.findByTestId("cv-editor")).toBeInTheDocument();
    const props = editorProps.mock.lastCall![0] as { stageId?: number; generatedId?: number; onOpenChange: (o: boolean) => void };
    expect(props.stageId).toBe(5);
    expect(props.generatedId).toBeUndefined();
    const before = get.mock.calls.filter(([u]) => u === QC_URL).length;
    props.onOpenChange(false);
    await waitFor(() => expect(get.mock.calls.filter(([u]) => u === QC_URL).length).toBeGreaterThan(before));
  });

  it("„Poprawię w edytorze” na karcie otwiera ten sam edytor", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Poprawię w edytorze" }));
    expect(await screen.findByTestId("cv-editor")).toBeInTheDocument();
  });

  it("CV z pliku (bez edycji) — zamiast edytora link do panelu osoby", async () => {
    serve(result({ cv: { ...result().cv!, source: "document", editable: false, stage_id: null } }));
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("link", { name: /Otwórz panel osoby/ })).toHaveAttribute(
      "href",
      "/jobs/31?candidate=21&panel=cv",
    );
    expect(within(dialog).queryByRole("button", { name: "Otwórz w edytorze CV" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Poprawię w edytorze" })).toBeNull();
  });

  it("„Pogrub wszystkie” w uwadze podmienia wynik w cache i odświeża Tablicę oraz kolejki", async () => {
    post.mockResolvedValue({ data: passed() });
    const { keys, onChanged } = renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Must-have są pogrubione/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Pogrub wszystkie" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(`${QC_URL}/apply`, { action: "bold_all", scope: "must" }));
    expect(await within(dialog).findByText("QC przechodzi")).toBeTruthy();
    expect(get).toHaveBeenCalledTimes(1);
    expect(onChanged).toHaveBeenCalled();
    expect(keys()).toEqual(expect.arrayContaining(['["kanban","31"]', '["kanban",31]', '["board-tasks"]']));
  });

  it("zamknięcie okna odświeża Tablicę — chip QC nie zostaje stary", async () => {
    const { keys, onClose } = renderDialog();
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Do poprawy: 2 rzeczy");
    expect(keys()).not.toContain('["kanban",31]');
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(keys()).toEqual(expect.arrayContaining(['["kanban","31"]', '["kanban",31]', '["board-tasks"]']));
  });

  it("propozycje AI: przycisk z karty, pogrubienie z `**`, źródło, zastosowanie po edycji", async () => {
    post.mockImplementation((url: string) =>
      url.endsWith("/qc/fixes")
        ? Promise.resolve({
            data: {
              status: "ok",
              cached: false,
              fixes: [
                {
                  id: "f1",
                  check_key: "critical_skills",
                  requirement: "Java",
                  role: "Firma Alfa — Java Developer",
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
    await userEvent.click(await within(dialog).findByRole("button", { name: /Dopisz zdania z oryginału \(AI\)/ }));
    const ai = within(dialog).getByRole("region", { name: "Propozycje AI" });
    const proposal = await within(ai).findByRole("listitem", { name: "Propozycja: Java" });
    expect(within(proposal).getByText("Java 11").tagName).toBe("STRONG");
    expect(proposal).toHaveTextContent("Źródło: oryginalne CV — SEPA transfers module (Java 11)");

    await userEvent.click(within(proposal).getByRole("button", { name: "Edytuj" }));
    const field = within(proposal).getByRole("textbox", { name: "Treść poprawki" });
    await userEvent.clear(field);
    await userEvent.type(field, "Moduł SEPA w Java 11.");
    await userEvent.click(within(proposal).getByRole("button", { name: "Zastosuj edycję" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`${QC_URL}/apply`, {
        action: "ai_fix",
        fix_id: "f1",
        text: "Moduł SEPA w Java 11.",
      }),
    );
    await waitFor(() => expect(within(ai).queryByRole("listitem", { name: "Propozycja: Java" })).toBeNull());
  });

  it("treść spoza oryginału: usunięcie z CV albo pytanie do kandydata", async () => {
    post.mockResolvedValue({ data: passed() });
    copyTextToClipboard.mockResolvedValue(false);
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Skopiuj pytanie do kandydata/ }));
    // Pytanie idzie do schowka — nic nie jest wysyłane.
    await waitFor(() => expect(copyTextToClipboard).toHaveBeenCalledWith("Czy używał(a) Docker? W którym projekcie?"));
    expect(showError).toHaveBeenCalledWith(expect.stringContaining("Czy używał(a) Docker?"));
    expect(post).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Usuń „Docker” z CV" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(`${QC_URL}/apply`, { action: "remove_term", term: "Docker" }));
  });

  it("CV spoza NEXUSA (409 CV_NOT_EDITABLE) → komunikat i poprawki wyłączone", async () => {
    post.mockRejectedValue({
      response: { status: 409, data: { detail: { code: "CV_NOT_EDITABLE", message: "x" } } },
    });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Usuń „Docker” z CV" }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith(expect.stringMatching(/plikiem Word\/PDF spoza NEXUSA/)));
    expect(within(dialog).getByRole("button", { name: "Usuń „Docker” z CV" })).toBeDisabled();
  });

  it("CV z pliku (`editable: false`) — informacja od razu, bez propozycji AI", async () => {
    serve(result({ cv: { ...result().cv!, source: "document", editable: false, filename: "Anna_B2B.pdf", bold_known: false } }));
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect((await within(dialog).findAllByText(/plikiem Word\/PDF spoza NEXUSA/)).length).toBeGreaterThan(0);
    expect(within(dialog).getByRole("button", { name: "Usuń „Docker” z CV" })).toBeDisabled();
    expect(within(dialog).getByRole("region", { name: "Propozycje AI" })).toHaveTextContent(/spoza NEXUSA/);
    expect(within(dialog).getByRole("button", { name: /Dopisz zdania z oryginału/ })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("„Przepuść mimo QC…” widzą tylko Delivery Lead i admin", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Do poprawy: 2 rzeczy");
    expect(within(dialog).queryByRole("button", { name: "Przepuść mimo QC…" })).toBeNull();
  });

  it("Delivery Lead przepuszcza gotowym powodem — bez wpisywania czegokolwiek", async () => {
    useAuthStore.setState({ user: { id: 2, role: "delivery_lead" } } as never);
    post.mockResolvedValue({
      data: result({ override: { reason: "Klient prosił o krótsze CV", by_name: "Piotr Zając", at: "2026-10-02T10:00:00Z" } }),
    });
    renderDialog();
    const dialog = await screen.findByRole("dialog", { name: /Anna Kowalczyk/ });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Przepuść mimo QC…" }));
    const form = await screen.findByRole("dialog", { name: "Przepuść mimo QC" });
    // Okno mówi, z czym CV pójdzie dalej.
    expect(form).toHaveTextContent("CV pójdzie dalej z 2 niepoprawionymi rzeczami:");
    expect(form).toHaveTextContent("Java — brak opisu w 1 roli");
    await userEvent.click(within(form).getByRole("radio", { name: "Klient prosił o krótsze CV" }));
    await userEvent.click(within(form).getByRole("button", { name: "Przepuść CV" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(`${QC_URL}/override`, { reason_code: "client_short_cv" }));
    expect(await screen.findByText("Przepuszczone mimo QC")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Przepuść mimo QC" })).toBeNull());
    expect(screen.queryByRole("button", { name: "Przepuść mimo QC…" })).toBeNull();
    expect(screen.getByText(/przez Piotr Zając/)).toHaveTextContent("Klient prosił o krótsze CV");
  });

  it("zaliczone QC wygrywa z dawnym obejściem — jak chip na Tablicy", async () => {
    serve(passed({ override: { reason: "Klient prosił o skrót", by_name: "Piotr Zając", at: "2026-09-24T10:00:00Z" } }));
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("QC przechodzi")).toBeTruthy();
    expect(within(dialog).queryByText(/Przepuszczone mimo QC/)).toBeNull();
  });

  it("„Przesuń dalej” jest w oknie tylko, gdy wołający umie przesunąć kartę", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Do poprawy: 2 rzeczy");
    expect(within(dialog).queryByRole("button", { name: /Przesuń dalej/ })).toBeNull();
  });

  it("„Przesuń dalej” czeka, aż nic nie będzie blokować", async () => {
    const onMoveNext = vi.fn();
    renderDialog({ onMoveNext });
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Do poprawy: 2 rzeczy");
    expect(within(dialog).getByRole("button", { name: /Przesuń dalej/ })).toBeDisabled();
    expect(onMoveNext).not.toHaveBeenCalled();
  });

  it("„Przesuń dalej” po zaliczeniu woła ruch i odświeża Tablicę", async () => {
    serve(passed());
    const onMoveNext = vi.fn();
    const { keys } = renderDialog({ onMoveNext });
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("QC przechodzi");
    await userEvent.click(within(dialog).getByRole("button", { name: /Przesuń dalej/ }));
    expect(onMoveNext).toHaveBeenCalledWith(expect.objectContaining({ candidate_id: 21, job_id: 31 }));
    expect(keys()).toEqual(expect.arrayContaining(['["kanban","31"]', '["kanban",31]']));
  });

  it("„Przesuń dalej” działa też po obejściu", async () => {
    serve(result({ override: { reason: "Klient prosił o krótsze CV", by_name: "Piotr Zając", at: "2026-10-02T10:00:00Z" } }));
    const onMoveNext = vi.fn();
    renderDialog({ onMoveNext });
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Przepuszczone mimo QC");
    expect(within(dialog).getByRole("status")).toHaveTextContent("przez Piotr Zając");
    await userEvent.click(within(dialog).getByRole("button", { name: /Przesuń dalej/ }));
    expect(onMoveNext).toHaveBeenCalledTimes(1);
  });

  it("awaria odczytu nie jest pustką — komunikat i „Ponów”", async () => {
    get.mockRejectedValue({ response: { status: 500, data: {} } });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Nie udało się policzyć QC. Spróbuj ponownie.")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Ponów" })).toBeTruthy();
  });
});
