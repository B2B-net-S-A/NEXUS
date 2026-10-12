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
import type { QcCheck, QcItem, QcResult } from "@/lib/api/cvQc";
import type { Permission } from "@/lib/permissions";
import { formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

/** Konto testowe. Bez `granted` uprawnienia liczą się z domyślnych dla roli;
 *  z `granted` profil niesie pełną migawkę (dokładnie te uprawnienia). */
function signIn(
  role: string,
  options: { granted?: Permission[]; realUser?: unknown } = {},
) {
  useAuthStore.setState({
    user: {
      id: 1,
      role,
      roles: [role],
      ...(options.granted
        ? { effective_action_access: permissionSnapshot(...options.granted) }
        : {}),
    },
    realUser: options.realUser ?? null,
  } as never);
}

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

/** Wynik z podmienionym jednym sprawdzeniem. */
const withCheck = (key: string, over: Partial<QcCheck>, base: QcResult = result()): QcResult => ({
  ...base,
  checks: base.checks.map((c) => (c.key === key ? { ...c, ...over } : c)),
});

const ROLE_ALFA = "Firma Alfa — Java Developer";
const ROLE_BETA = "Firma Beta — Programista";
const OVERRIDE = { reason: "Klient prosił o krótsze CV", by_name: "Piotr Zając", at: "2026-10-02T10:00:00Z" };

/** Karta rzeczy do poprawy po jej tytule. */
async function taskCard(title: string | RegExp, region = "Do poprawy przed wysłaniem") {
  const dialog = await screen.findByRole("dialog");
  const tasks = await within(dialog).findByRole("region", { name: region });
  const card = within(tasks).getByText(title).closest("li");
  if (!card) throw new Error(`brak karty: ${title}`);
  return { dialog, card };
}

describe("CvQcDialog — QC CV", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signIn("recruiter");
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
    expect(explainer).toHaveTextContent(
      "Opis jest wymagany tylko w tych rolach, w których oryginalne CV pokazuje tę umiejętność.",
    );
    // Poza trybem doradczym QC nie mówi, że doradza.
    expect(explainer).not.toHaveTextContent("QC doradza");

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
    const explainer = await within(dialog).findByRole("region", { name: "Co sprawdza QC" });
    expect(explainer).toHaveTextContent("Ta rekrutacja nie ma umiejętności krytycznych");
    expect(explainer).not.toHaveTextContent("Opis jest wymagany tylko w tych rolach");
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

  // „Przepuść mimo QC…” idzie za uprawnieniem „Rekrutacje: zakładanie, zamykanie,
  // wysyłka CV do klienta” (domyślnie Delivery Lead i administrator), nie za rolą.
  async function overrideButton() {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Do poprawy: 2 rzeczy");
    return within(dialog).queryByRole("button", { name: "Przepuść mimo QC…" });
  }

  it("rekruter bez uprawnienia do prowadzenia rekrutacji nie widzi „Przepuść mimo QC…”", async () => {
    expect(await overrideButton()).toBeNull();
  });

  it.each(["delivery_lead", "admin"])(
    "%s ma uprawnienie domyślnie i widzi „Przepuść mimo QC…”",
    async (role) => {
      signIn(role);
      expect(await overrideButton()).not.toBeNull();
    },
  );

  it("rekruter z nadanym uprawnieniem widzi „Przepuść mimo QC…”", async () => {
    signIn("recruiter", { granted: ["recruitment_manage"] });
    expect(await overrideButton()).not.toBeNull();
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie widzi „Przepuść mimo QC…”", async () => {
    signIn("delivery_lead", { granted: ["delivery_view", "clients_edit"] });
    expect(await overrideButton()).toBeNull();
  });

  it("w podglądzie jako inny użytkownik nie ma „Przepuść mimo QC…”", async () => {
    signIn("delivery_lead", { realUser: { id: 9, role: "admin", roles: ["admin"] } });
    expect(await overrideButton()).toBeNull();
  });

  it("Delivery Lead przepuszcza gotowym powodem — bez wpisywania czegokolwiek", async () => {
    signIn("delivery_lead");
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

  it("poza trybem doradczym obejście nie przesuwa karty samo — „Przesuń dalej” klika człowiek", async () => {
    signIn("delivery_lead");
    post.mockResolvedValue({ data: result({ override: OVERRIDE }) });
    const onMoveNext = vi.fn();
    renderDialog({ onMoveNext });
    const dialog = await screen.findByRole("dialog", { name: /Anna Kowalczyk/ });
    const next = await within(dialog).findByRole("button", { name: /Przesuń dalej/ });
    expect(next).toHaveAttribute("title", "Najpierw popraw rzeczy z listy „Do poprawy przed wysłaniem”.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Przepuść mimo QC…" }));
    const form = await screen.findByRole("dialog", { name: "Przepuść mimo QC" });
    await userEvent.click(within(form).getByRole("radio", { name: "Klient prosił o krótsze CV" }));
    await userEvent.click(within(form).getByRole("button", { name: "Przepuść CV" }));
    expect(await screen.findByText("Przepuszczone mimo QC")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Przepuść mimo QC" })).toBeNull());
    expect(onMoveNext).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("button", { name: /Przesuń dalej/ })).toBeEnabled();
  });

  describe("tryb doradczy — QC doradza, nie blokuje", () => {
    const advisory = (over: Partial<QcResult> = {}): QcResult =>
      result({ advisory: true, can_override: true, ...over });

    it("rekruter z `can_override` widzi „Przesuń mimo uwag…”, a lista to „Zalecane poprawki”", async () => {
      serve(advisory());
      renderDialog({ onMoveNext: vi.fn() });
      const dialog = await screen.findByRole("dialog");
      const tasks = await within(dialog).findByRole("region", { name: "Zalecane poprawki przed wysłaniem" });
      expect(within(tasks).getByText("Zalecane poprawki przed wysłaniem (2)")).toBeTruthy();
      expect(within(tasks).getByText("Java — brak opisu w 1 roli")).toBeTruthy();
      expect(within(dialog).queryByRole("region", { name: "Do poprawy przed wysłaniem" })).toBeNull();
      expect(within(dialog).getByRole("region", { name: "Co sprawdza QC" })).toHaveTextContent(
        "QC doradza: możesz przesunąć kartę mimo uwag — Delivery Lead zobaczy, co zostało niepoprawione, i może cofnąć ją do poprawy.",
      );
      expect(within(dialog).getByRole("button", { name: "Przesuń mimo uwag…" })).toBeTruthy();
      expect(within(dialog).queryByRole("button", { name: "Przepuść mimo QC…" })).toBeNull();
      const next = within(dialog).getByRole("button", { name: /Przesuń dalej/ });
      expect(next).toBeDisabled();
      expect(next).toHaveAttribute("title", "Popraw rzeczy z listy albo użyj „Przesuń mimo uwag…”.");
    });

    it("o przycisku decyduje serwer: `can_override: false` chowa go także Delivery Leadowi", async () => {
      signIn("delivery_lead");
      serve(advisory({ can_override: false }));
      renderDialog();
      const dialog = await screen.findByRole("dialog");
      await within(dialog).findByText("Do poprawy: 2 rzeczy");
      expect(within(dialog).queryByRole("button", { name: "Przesuń mimo uwag…" })).toBeNull();
      expect(within(dialog).queryByRole("button", { name: "Przepuść mimo QC…" })).toBeNull();
    });

    it("w podglądzie jako inny użytkownik przycisku nie ma mimo `can_override`", async () => {
      signIn("recruiter", { realUser: { id: 9, role: "admin", roles: ["admin"] } });
      serve(advisory());
      renderDialog();
      const dialog = await screen.findByRole("dialog");
      await within(dialog).findByText("Do poprawy: 2 rzeczy");
      expect(within(dialog).queryByRole("button", { name: "Przesuń mimo uwag…" })).toBeNull();
    });

    it("po zapisaniu powodu karta idzie dalej od razu — jedno przejście zamiast dwóch", async () => {
      serve(advisory());
      post.mockResolvedValue({ data: advisory({ override: OVERRIDE }) });
      const onMoveNext = vi.fn();
      const { keys } = renderDialog({ onMoveNext });
      const dialog = await screen.findByRole("dialog", { name: /Anna Kowalczyk/ });
      await userEvent.click(await within(dialog).findByRole("button", { name: "Przesuń mimo uwag…" }));
      const form = await screen.findByRole("dialog", { name: "Przesuń mimo uwag QC" });
      expect(form).toHaveTextContent("Delivery Lead dostanie powiadomienie");
      expect(form).toHaveTextContent("CV pójdzie dalej z 2 niepoprawionymi rzeczami:");
      await userEvent.click(within(form).getByRole("radio", { name: "Klient prosił o krótsze CV" }));
      await userEvent.click(within(form).getByRole("button", { name: "Przesuń mimo uwag" }));
      await waitFor(() => expect(post).toHaveBeenCalledWith(`${QC_URL}/override`, { reason_code: "client_short_cv" }));
      await waitFor(() => expect(onMoveNext).toHaveBeenCalledTimes(1));
      expect(onMoveNext).toHaveBeenCalledWith(
        expect.objectContaining({ candidate_id: 21, job_id: 31, override: OVERRIDE }),
      );
      expect(keys()).toEqual(expect.arrayContaining(['["kanban","31"]', '["kanban",31]', '["board-tasks"]']));
    });

    it("bez „Przesuń dalej” u wołającego obejście tylko zapisuje powód", async () => {
      serve(advisory());
      post.mockResolvedValue({ data: advisory({ override: OVERRIDE }) });
      renderDialog();
      const dialog = await screen.findByRole("dialog", { name: /Anna Kowalczyk/ });
      await userEvent.click(await within(dialog).findByRole("button", { name: "Przesuń mimo uwag…" }));
      const form = await screen.findByRole("dialog", { name: "Przesuń mimo uwag QC" });
      await userEvent.click(within(form).getByRole("radio", { name: "Klient prosił o krótsze CV" }));
      await userEvent.click(within(form).getByRole("button", { name: "Przesuń mimo uwag" }));
      expect(await screen.findByText("Przepuszczone mimo QC")).toBeTruthy();
      await waitFor(() => expect(screen.queryByRole("dialog", { name: "Przesuń mimo uwag QC" })).toBeNull());
      expect(screen.queryByRole("button", { name: "Przesuń mimo uwag…" })).toBeNull();
    });
  });

  describe("karta umiejętności krytycznej — dowód z oryginału", () => {
    const critical = (items: QcItem[]) => withCheck("critical_skills", { items });
    const roleItem = (over: Partial<QcItem>): QcItem => ({
      requirement: "Java",
      role: ROLE_ALFA,
      detail: "Brak w tej roli, a w oryginale jest.",
      fix: "ai",
      role_index: 0,
      ...over,
    });

    it("zdanie z opisu roli: cytat z oryginału i przycisk AI", async () => {
      serve(critical([roleItem({ evidence: "Built the SEPA transfers module in Java 11.", evidence_kind: "description" })]));
      renderDialog();
      const { card } = await taskCard("Java — brak opisu w 1 roli");
      expect(card).toHaveTextContent(
        "Oryginalne CV pokazuje tę umiejętność w tej roli. W CV firmowym brakuje tam zdania o tym, co kandydat z nią robił.",
      );
      const role = within(within(card).getByRole("list", { name: "Role bez opisu: Java" })).getByRole("listitem");
      expect(role).toHaveTextContent(ROLE_ALFA);
      const quote = within(role).getByText("„Built the SEPA transfers module in Java 11.”");
      expect(quote).toHaveClass("italic");
      expect(within(role).getByText("W oryginale").nextElementSibling).toContainElement(quote);
      expect(within(role).getByText("W CV firmowym").nextElementSibling).toHaveTextContent("brak w tej roli");
      expect(within(card).getByRole("button", { name: /Dopisz zdania z oryginału \(AI\)/ })).toBeEnabled();
      expect(within(card).getByRole("button", { name: "Poprawię w edytorze" })).toBeTruthy();
      expect(within(card).queryByRole("button", { name: /Skopiuj pytanie do kandydata/ })).toBeNull();
    });

    it("jedna rola z opisem wystarcza, żeby AI miało z czego pisać — druga pokazuje listę technologii", async () => {
      serve(
        critical([
          roleItem({
            detail: "Jest tylko na liście technologii — dopisz zdanie, co kandydat w tej roli z tym robił.",
            evidence: "Built the SEPA transfers module in Java 11.",
            evidence_kind: "description",
          }),
          roleItem({ role: ROLE_BETA, role_index: 1, evidence: "Java 8, Spring, Oracle", evidence_kind: "technologies" }),
        ]),
      );
      renderDialog();
      const { card } = await taskCard("Java — brak opisu w 2 rolach");
      expect(card).toHaveTextContent("Oryginalne CV pokazuje tę umiejętność w tych rolach.");
      const [alfa, beta] = within(within(card).getByRole("list", { name: "Role bez opisu: Java" })).getAllByRole(
        "listitem",
      );
      expect(within(alfa).getByText("W CV firmowym").nextElementSibling).toHaveTextContent(
        "tylko na liście technologii",
      );
      expect(within(beta).getByText("W oryginale").nextElementSibling).toHaveTextContent(
        "lista technologii tej roli: Java 8, Spring, Oracle",
      );
      expect(within(beta).getByText("W CV firmowym").nextElementSibling).toHaveTextContent("brak w tej roli");
      expect(within(card).getByRole("button", { name: /Dopisz zdania z oryginału \(AI\)/ })).toBeTruthy();
    });

    it("tylko lista technologii albo nazwa stanowiska: pytanie do kandydata zamiast AI", async () => {
      copyTextToClipboard.mockResolvedValue(true);
      serve(
        critical([
          roleItem({
            detail: "Jest tylko na liście technologii — dopisz zdanie, co kandydat w tej roli z tym robił.",
            evidence: "Java 11, Spring Boot",
            evidence_kind: "technologies",
          }),
          roleItem({ role: ROLE_BETA, role_index: 1, evidence: "Java Developer", evidence_kind: "title" }),
        ]),
      );
      renderDialog();
      const { card } = await taskCard("Java — brak opisu w 2 rolach");
      expect(card).toHaveTextContent(
        "Oryginalne CV wymienia tę umiejętność w tych rolach, ale nie opisuje, co kandydat z nią robił. Zapytaj kandydata — AI ułoży zdanie dopiero wtedy, gdy powiedzą o tym notatki.",
      );
      const [alfa, beta] = within(within(card).getByRole("list", { name: "Role bez opisu: Java" })).getAllByRole(
        "listitem",
      );
      expect(within(alfa).getByText("W oryginale").nextElementSibling).toHaveTextContent(
        "lista technologii tej roli: Java 11, Spring Boot",
      );
      expect(within(alfa).getByText("W CV firmowym").nextElementSibling).toHaveTextContent(
        "tylko na liście technologii",
      );
      expect(within(beta).getByText("W oryginale").nextElementSibling).toHaveTextContent(
        "nazwa stanowiska: Java Developer",
      );
      expect(within(card).queryByRole("button", { name: /Dopisz zdania z oryginału/ })).toBeNull();
      expect(within(card).getByRole("button", { name: "Poprawię w edytorze" })).toBeTruthy();
      await userEvent.click(within(card).getByRole("button", { name: /Skopiuj pytanie do kandydata/ }));
      // Pytanie o pierwszą rolę z listy — do schowka, nic nie jest wysyłane.
      await waitFor(() => expect(copyTextToClipboard).toHaveBeenCalledWith(`Czy używał(a) Java w ${ROLE_ALFA}?`));
      await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Pytanie skopiowane — wyślij je kandydatowi."));
      expect(post).not.toHaveBeenCalled();
    });

    it("przebieg sprzed zmiany (bez dowodu): nie ma wiersza „W oryginale”, AI zostaje", async () => {
      renderDialog();
      const { card } = await taskCard("Java — brak opisu w 1 roli");
      expect(card).toHaveTextContent("Oryginalne CV pokazuje tę umiejętność w tej roli.");
      expect(within(card).queryByText("W oryginale")).toBeNull();
      expect(within(card).getByText("W CV firmowym").nextElementSibling).toHaveTextContent("brak w tej roli");
      expect(within(card).getByRole("button", { name: /Dopisz zdania z oryginału \(AI\)/ })).toBeTruthy();
    });
  });

  describe("„Potwierdzone z kandydatem” — treść spoza oryginału", () => {
    const DOCKER = "Docker — jest w CV, a nie ma tego w oryginale";
    const FIELD = "Co powiedział kandydat? (opcjonalnie)";

    it("zapisuje to, co powiedział kandydat, i podmienia wynik QC", async () => {
      post.mockResolvedValue({ data: passed() });
      const { onChanged, keys } = renderDialog();
      const { dialog, card } = await taskCard(DOCKER);
      expect(card).toHaveTextContent(
        "Oryginalne CV i notatki z rozmów o tym nie wspominają. Usuń to z CV albo potwierdź u kandydata i zapisz potwierdzenie.",
      );
      // Formularz otwiera się dopiero po kliknięciu.
      expect(within(card).queryByLabelText(FIELD)).toBeNull();
      await userEvent.click(within(card).getByRole("button", { name: "Potwierdzone z kandydatem" }));
      const field = within(card).getByLabelText(FIELD);
      expect(field.tagName).toBe("TEXTAREA");
      expect(field).toHaveAttribute("maxlength", "1000");
      await userEvent.type(field, "  Używał w projekcie migracji, ok. roku ");
      await userEvent.click(within(card).getByRole("button", { name: "Zapisz potwierdzenie" }));
      await waitFor(() =>
        expect(post).toHaveBeenCalledWith(`${QC_URL}/confirm`, {
          term: "Docker",
          text: "Używał w projekcie migracji, ok. roku",
        }),
      );
      await waitFor(() =>
        expect(showSuccess).toHaveBeenCalledWith("Potwierdzenie zapisane w notatkach kandydata — QC przeliczone."),
      );
      // Świeży wynik z odpowiedzi zastępuje cache — bez drugiego odczytu.
      expect(await within(dialog).findByText("QC przechodzi")).toBeTruthy();
      expect(get).toHaveBeenCalledTimes(1);
      expect(onChanged).toHaveBeenCalled();
      expect(keys()).toEqual(expect.arrayContaining(['["kanban","31"]', '["kanban",31]', '["board-tasks"]']));
    });

    it("opis jest opcjonalny, a przycisk działa też przy CV, którego nie da się edytować", async () => {
      serve(result({ cv: { ...result().cv!, source: "document", editable: false, stage_id: null } }));
      post.mockResolvedValue({ data: passed() });
      renderDialog();
      const { card } = await taskCard(DOCKER);
      expect(within(card).getByRole("button", { name: "Usuń „Docker” z CV" })).toBeDisabled();
      const open = within(card).getByRole("button", { name: "Potwierdzone z kandydatem" });
      expect(open).toBeEnabled();
      await userEvent.click(open);
      await userEvent.click(within(card).getByRole("button", { name: "Zapisz potwierdzenie" }));
      await waitFor(() => expect(post).toHaveBeenCalledWith(`${QC_URL}/confirm`, { term: "Docker" }));
    });

    it("odmowa serwera (422) pokazuje jego komunikat i zostawia formularz z treścią", async () => {
      post.mockRejectedValue({
        response: {
          status: 422,
          data: { detail: { code: "CV_QC_CONFIRM_FAILED", message: "QC nie zgłasza już tej pozycji — odśwież okno." } },
        },
      });
      renderDialog();
      const { card } = await taskCard(DOCKER);
      await userEvent.click(within(card).getByRole("button", { name: "Potwierdzone z kandydatem" }));
      await userEvent.type(within(card).getByLabelText(FIELD), "Zna z kursu");
      await userEvent.click(within(card).getByRole("button", { name: "Zapisz potwierdzenie" }));
      await waitFor(() => expect(showError).toHaveBeenCalledWith("QC nie zgłasza już tej pozycji — odśwież okno."));
      expect(showSuccess).not.toHaveBeenCalled();
      expect(within(card).getByLabelText(FIELD)).toHaveValue("Zna z kursu");
    });

    it("awaria bez komunikatu serwera → zdanie zastępcze", async () => {
      post.mockRejectedValue({ response: { status: 500, data: {} } });
      renderDialog();
      const { card } = await taskCard(DOCKER);
      await userEvent.click(within(card).getByRole("button", { name: "Potwierdzone z kandydatem" }));
      await userEvent.click(within(card).getByRole("button", { name: "Zapisz potwierdzenie" }));
      await waitFor(() =>
        expect(showError).toHaveBeenCalledWith("Nie udało się zapisać potwierdzenia. Spróbuj ponownie."),
      );
    });

    it("„Anuluj” zamyka formularz bez zapisu", async () => {
      renderDialog();
      const { card } = await taskCard(DOCKER);
      await userEvent.click(within(card).getByRole("button", { name: "Potwierdzone z kandydatem" }));
      await userEvent.click(within(card).getByRole("button", { name: "Anuluj" }));
      expect(within(card).queryByLabelText(FIELD)).toBeNull();
      expect(within(card).getByRole("button", { name: "Potwierdzone z kandydatem" })).toBeTruthy();
      expect(post).not.toHaveBeenCalled();
    });

    it("lista potwierdzeń stoi pod ramką „Co sprawdza QC” — co, kto i kiedy", async () => {
      const at = "2026-10-12T10:00:00Z";
      serve(
        result({
          confirmations: [
            { text: "Potwierdzone z kandydatem: Kafka — dwa lata w Firmie Alfa", by_name: "Marta Rekruterka", at },
            { text: "Potwierdzone z kandydatem: Scala", by_name: null, at },
          ],
        }),
      );
      renderDialog();
      const dialog = await screen.findByRole("dialog");
      const list = await within(dialog).findByRole("region", { name: "Potwierdzone z kandydatem" });
      expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        `Potwierdzone z kandydatem: Kafka — dwa lata w Firmie Alfa — Marta Rekruterka, ${formatDate(at)}`,
        `Potwierdzone z kandydatem: Scala — ${formatDate(at)}`,
      ]);
      const explainer = within(dialog).getByRole("region", { name: "Co sprawdza QC" });
      expect(explainer.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(explainer.nextElementSibling).toBe(list);
    });

    it("bez potwierdzeń sekcji nie ma", async () => {
      renderDialog();
      const dialog = await screen.findByRole("dialog");
      await within(dialog).findByText("Do poprawy: 2 rzeczy");
      expect(within(dialog).queryByRole("region", { name: "Potwierdzone z kandydatem" })).toBeNull();
    });
  });

  describe("„Rola po roli” i krytyczne do sprawdzenia ręcznie", () => {
    it("rozwinięte sprawdzenie pokazuje stan każdej roli, pogrupowany po wymaganiu", async () => {
      const base = withCheck(
        "critical_skills",
        {
          roles: [
            { requirement: "Java", role: ROLE_ALFA, state: "described" },
            { requirement: "Java", role: ROLE_BETA, state: "not_in_original" },
          ],
        },
        passed(),
      );
      serve({
        ...base,
        checks: [
          ...base.checks,
          {
            key: "must_in_roles",
            label: "Pozostałe wymagania opisane w rolach z oryginału",
            severity: "warning",
            status: "fail",
            summary: "1 do uzupełnienia",
            items: [{ requirement: "Kafka", role: ROLE_ALFA, fix: "ai", role_index: 0 }],
            roles: [
              { requirement: "Kafka", role: ROLE_ALFA, state: "missing" },
              { requirement: "Spring", role: ROLE_ALFA, state: "described" },
              { requirement: "Kafka", role: ROLE_BETA, state: "not_in_original" },
            ],
          },
        ],
      });
      renderDialog();
      const dialog = await screen.findByRole("dialog");
      const notes = await within(dialog).findByRole("region", { name: "Warto poprawić — nie blokuje" });
      await userEvent.click(within(notes).getByRole("button", { name: /Pozostałe wymagania opisane w rolach/ }));
      const group = within(notes).getByRole("group", { name: "Rola po roli" });
      // Kafka ma dwie role pod jednym nagłówkiem, mimo że serwer przeplótł je ze Springiem.
      expect(within(group).getAllByRole("list")).toHaveLength(2);
      expect(within(group).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        `${ROLE_ALFA} — brakuje zdania w CV firmowym`,
        `${ROLE_BETA} — oryginał nie pokazuje tej umiejętności w tej roli — opis nie jest wymagany`,
        `${ROLE_ALFA} — opisane w CV firmowym`,
      ]);
      expect(within(group).getByText("Kafka")).toBeTruthy();
      expect(within(group).getByText("Spring")).toBeTruthy();

      // Zaliczone sprawdzenie bez pozycji też się rozwija, gdy niesie same role.
      const fine = within(dialog).getByRole("region", { name: "W porządku" });
      await userEvent.click(within(fine).getByRole("button", { name: /W porządku \(/ }));
      const rows = within(fine).getByRole("list");
      const criticalRow = within(rows).getByRole("button", { name: /Umiejętności krytyczne są w CV/ });
      expect(criticalRow).toHaveAttribute("aria-expanded", "false");
      await userEvent.click(criticalRow);
      expect(within(within(fine).getByRole("group", { name: "Rola po roli" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        `${ROLE_ALFA} — opisane w CV firmowym`,
        `${ROLE_BETA} — oryginał nie pokazuje tej umiejętności w tej roli — opis nie jest wymagany`,
      ]);
      // Sprawdzenie bez pozycji i bez ról dalej się nie rozwija.
      expect(within(rows).getByRole("button", { name: /CV firmowe jest przygotowane/ })).not.toHaveAttribute(
        "aria-expanded",
      );
    });

    it("krytyczne „sprawdź ręcznie” (odczyt CV bez opisów ról) to uwaga, nie blokada", async () => {
      serve(
        withCheck(
          "critical_skills",
          {
            status: "manual",
            summary: "Odczyt CV nie ma opisów ról — sprawdź role ręcznie",
            items: [],
            roles: [{ requirement: "Java", role: ROLE_ALFA, state: "unverified" }],
          },
          result({ blocking_failed: 1 }),
        ),
      );
      renderDialog();
      const dialog = await screen.findByRole("dialog");
      expect(await within(dialog).findByText("Do poprawy: 1 rzecz")).toBeTruthy();
      const tasks = within(dialog).getByRole("region", { name: "Do poprawy przed wysłaniem" });
      expect(within(tasks).getByText("Do poprawy przed wysłaniem (1)")).toBeTruthy();
      expect(within(tasks).queryByText(/Java — brak/)).toBeNull();
      expect(within(tasks).queryByText("umiejętność krytyczna")).toBeNull();

      const notes = within(dialog).getByRole("region", { name: "Warto poprawić — nie blokuje" });
      expect(within(notes).getByText("Warto poprawić — nie blokuje (3)")).toBeTruthy();
      const row = within(notes).getByRole("button", { name: /Umiejętności krytyczne są w CV i opisane w rolach/ });
      expect(row).toHaveTextContent("Odczyt CV nie ma opisów ról — sprawdź role ręcznie");
      expect(row).toHaveTextContent("sprawdź ręcznie");
      await userEvent.click(row);
      expect(within(notes).getByRole("group", { name: "Rola po roli" })).toHaveTextContent(
        `${ROLE_ALFA} — odczyt CV nie ma opisu tej roli — sprawdź ręcznie`,
      );
      // Nie wiemy, czy w roli czegoś brakuje — CV nie dostaje czerwonej krawędzi.
      const cv = within(dialog).getByRole("article", { name: "CV firmowe" });
      expect(cv.querySelector('[data-qc-gap="blocking"]')).toBeNull();
    });
  });
});
