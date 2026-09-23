import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));
vi.mock("@/components/v2/recruitment/DlReviewPanel", () => ({
  DlReviewPanel: ({
    task,
    open,
    canSendToClient,
  }: {
    task: { candidate_name: string } | null;
    open: boolean;
    canSendToClient?: boolean;
  }) =>
    open && task ? (
      <div role="dialog" aria-label="Przegląd DL">
        {task.candidate_name} · wysyłka {canSendToClient ? "tak" : "nie"}
      </div>
    ) : null,
}));

import { BoardTasksPanel } from "@/components/v2/dashboard/BoardTasksPanel";
import { useAuthStore } from "@/store/auth";

const since = new Date(Date.now() - 3 * 86_400_000).toISOString();

function row(kind: string, over: Record<string, unknown> = {}) {
  return {
    kind,
    stage_id: 11,
    candidate_id: 21,
    candidate_name: "Anna Nowak",
    job_id: 31,
    job_title: "Java Developer",
    client_id: 5,
    client_name: "Nordea",
    since,
    process_state_version: 4,
    target_stage_def_id: 303,
    assignee_id: null,
    assignee_name: null,
    ...over,
  };
}

function mockQueue(queue: Record<string, unknown>) {
  get.mockImplementation((url: string) =>
    url === "/api/board-tasks"
      ? Promise.resolve({ data: { window_days: 14, can_approve_dz: true, dz: [], cpro_to_send: [], cpro_sent: [], ...queue } })
      : Promise.resolve({ data: [{ id: 1, name: "Artur" }, { id: 44, name: "Marta" }] }),
  );
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BoardTasksPanel />
    </QueryClientProvider>,
  );
}

describe("BoardTasksPanel — „Czeka na Ciebie” na pulpicie", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "head_of_recruitment" } } as never);
    post.mockResolvedValue({ data: {} });
    put.mockResolvedValue({ data: { job_id: 31, assignee_id: 44, assignee_name: "Marta", added_to_team: true } });
  });

  it("nic nie czeka → panelu nie ma (pusta ramka uczyłaby go ignorować)", async () => {
    mockQueue({});
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("„Czeka na Twój przegląd (DL)” otwiera panel przeglądu kandydata", async () => {
    mockQueue({
      can_send_to_client: true,
      dl_review_window_days: 30,
      dl_review: [row("dl_review", { candidate_name: "Ola Przegląd", client_name: "PKO BP" })],
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na Twój przegląd (DL)" });
    expect(within(section).getByText("Java Developer · PKO BP")).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "Przegląd DL" })).toBeNull();
    await userEvent.click(within(section).getByRole("button", { name: "Przejrzyj: Ola Przegląd" }));
    expect(screen.getByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Ola Przegląd · wysyłka tak");
  });

  it("„DZ” to zwykły ruch na etap DZ z wersją procesu", async () => {
    mockQueue({ dz: [row("dz")] });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na DZ" });
    expect(within(section).getByText("Anna Nowak")).toHaveAttribute("href", "/jobs/31?candidate=21");
    expect(within(section).getByText("od 3 dni")).toBeTruthy();
    await userEvent.click(within(section).getByRole("button", { name: "Zatwierdź przez DZ: Anna Nowak" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        stage_def_id: 303,
        expected_state_version: 4,
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Anna Nowak — zatwierdzony przez DZ.");
  });

  it("Cpro: jedna osoba na rekrutację — grupy po rekrutacji, wybór osoby i przejście do rekrutacji", async () => {
    mockQueue({
      cpro_to_send: [
        row("cpro_to_send", { stage_id: 12, candidate_name: "Bez Osoby", assignee_id: 44, assignee_name: "Marta" }),
        row("cpro_to_send", { stage_id: 15, candidate_id: 25, candidate_name: "Druga Osoba" }),
        row("cpro_to_send", {
          stage_id: 13,
          candidate_id: 22,
          candidate_name: "Moja Osoba",
          job_id: 32,
          job_title: "QA Engineer",
          assignee_id: 1,
          assignee_name: "Artur",
          job_sender_id: 1,
          job_sender_name: "Artur",
        }),
      ],
      cpro_sent: [row("cpro_sent", { stage_id: 14, candidate_name: "Już Wysłana" })],
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Do wysłania do Cpro" });
    // Licznik = osoby, wiersz = rekrutacja.
    expect(within(section).getByText("3")).toBeTruthy();
    expect(within(section).getAllByRole("listitem")).toHaveLength(2);
    expect(within(section).getByText(/czeka 2: Bez Osoby, Druga Osoba/)).toBeTruthy();
    // Typowanie jednego kandydata z 0348 nie jest osobą dla rekrutacji.
    expect(within(section).getByText(/Dotąd typowani per kandydat: Marta/)).toBeTruthy();

    const select = within(section).getByLabelText("Kto wysyła do Cpro w rekrutacji Java Developer");
    expect((select as HTMLSelectElement).value).toBe("");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Wysyła: Marta" })).toBeTruthy());
    await userEvent.selectOptions(select, "44");
    await waitFor(() => expect(put).toHaveBeenCalledWith("/api/board-tasks/cpro/jobs/31/sender", { assignee_id: 44 }));
    expect(showSuccess).toHaveBeenCalledWith("Do Cpro wysyła: Marta (dodana do zespołu rekrutacji).");

    const links = within(section).getAllByRole("link", { name: /Wysyłaj z rekrutacji/ });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/jobs/31", "/jobs/32"]);
    expect(within(screen.getByRole("region", { name: "Wysłane do Cpro" })).getByText("Już Wysłana")).toBeTruthy();
  });

  it("„Sprawdź” otwiera przegląd DZ: must-have, oba CV, zapytanie, podpowiedzi i „Zatwierdź DZ”", async () => {
    const review = {
      stage_id: 11,
      candidate_id: 21,
      candidate_name: "Anna Nowak",
      job_id: 31,
      job_title: "Java Developer",
      client_name: "Nordea",
      client_request: { must: ["Java", "Kubernetes"], nice: ["Spring"], description: "Projekt bankowy w Java", project_about: null },
      generated_cv: {
        source: "branded_draft",
        stage_id: 11,
        generated_document_id: null,
        updated_at: null,
        blocks: [
          { kind: "h", section: "summary", runs: [{ t: "Podsumowanie", b: false }] },
          { kind: "p", section: null, runs: [{ t: "Programista ", b: false }, { t: "Java", b: true }] },
        ],
      },
      original_cv: { source: "profile_text", stage_id: null, filename: null, text: "Java Kubernetes Kafka" },
      checks: [
        { label: "Java", in_cv: true, bolded: true, in_original: true, original_roles: ["Dev · Acme"], missing_in_roles: [], roles_absent: [] },
        { label: "Kubernetes", in_cv: false, bolded: false, in_original: true, original_roles: ["Dev · Acme"], missing_in_roles: ["Dev · Acme"], roles_absent: [] },
      ],
      extra_bold: ["React"],
      summary: { must_total: 2, must_in_cv: 1, must_bolded: 1, roles_missing: 1, generated_roles: 1 },
    };
    get.mockImplementation((url: string) => {
      if (url === "/api/board-tasks")
        return Promise.resolve({ data: { window_days: 14, can_approve_dz: true, dz: [row("dz")], cpro_to_send: [], cpro_sent: [] } });
      if (url === "/api/board-tasks/dz/11/review") return Promise.resolve({ data: review });
      return Promise.resolve({ data: [] });
    });
    post.mockImplementation((url: string) =>
      url === "/api/board-tasks/dz/11/hints"
        ? Promise.resolve({
            data: {
              status: "ok",
              verdict: "fix",
              model: "gpt-6-luna",
              cached: false,
              hints: [{ kind: "missing_must", severity: "high", must_have: "Kubernetes", message: "Dopisz Kubernetes w roli Acme.", quote: null }],
            },
          })
        : Promise.resolve({ data: {} }),
    );
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na DZ" });
    await userEvent.click(within(section).getByRole("button", { name: "Sprawdź CV przed DZ: Anna Nowak" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Brak (jest w oryginale)");
    expect(within(dialog).getByText("Brak w: Dev · Acme")).toBeTruthy();
    expect(within(dialog).getByText("Pogrubione spoza wymagań: React")).toBeTruthy();
    expect(await within(dialog).findByText("Dopisz Kubernetes w roli Acme.")).toBeTruthy();
    expect(within(dialog).getByRole("region", { name: "CV dla klienta" })).toHaveTextContent("Programista Java");
    expect(within(dialog).getByRole("region", { name: "CV oryginalne" })).toHaveTextContent("Java Kubernetes Kafka");
    expect(within(dialog).getByRole("region", { name: "Zapytanie klienta" })).toHaveTextContent("Projekt bankowy w Java");

    await userEvent.click(within(dialog).getByRole("button", { name: "Zatwierdź DZ" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        stage_def_id: 303,
        expected_state_version: 4,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("przegląd DZ po powrocie z Tablicy: świeże CV i nowe podpowiedzi", async () => {
    const base = {
      stage_id: 11, candidate_id: 21, candidate_name: "Anna Nowak", job_id: 31, job_title: "Java Developer", client_name: null,
      client_request: { must: ["Kafka"], nice: [], description: null, project_about: null },
      original_cv: { source: "profile_text", stage_id: null, filename: null, text: "Kafka" },
      checks: [], extra_bold: [],
      summary: { must_total: 1, must_in_cv: 0, must_bolded: 0, roles_missing: 0, generated_roles: 0 },
    };
    const cv = (text: string, updated: string) => ({
      source: "branded_draft", stage_id: 11, generated_document_id: null, updated_at: updated,
      blocks: [{ kind: "p", section: null, runs: [{ t: text, b: false }] }],
    });
    let version = 1;
    get.mockImplementation((url: string) => {
      if (url === "/api/board-tasks")
        return Promise.resolve({ data: { window_days: 14, can_approve_dz: true, dz: [row("dz")], cpro_to_send: [], cpro_sent: [] } });
      if (url === "/api/board-tasks/dz/11/review")
        return Promise.resolve({
          data: { ...base, generated_cv: version === 1 ? cv("Wersja pierwsza", "2026-09-23T08:00:00Z") : cv("Wersja poprawiona z Kafka", "2026-09-23T09:00:00Z") },
        });
      return Promise.resolve({ data: [] });
    });
    post.mockImplementation((url: string) =>
      url === "/api/board-tasks/dz/11/hints"
        ? Promise.resolve({ data: { status: "ok", verdict: "ok", model: "gpt-6-luna", cached: false, hints: [] } })
        : Promise.resolve({ data: {} }),
    );
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na DZ" });
    await userEvent.click(within(section).getByRole("button", { name: "Sprawdź CV przed DZ: Anna Nowak" }));
    let dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Wersja pierwsza");
    await waitFor(() => expect(post.mock.calls.filter((c) => c[0] === "/api/board-tasks/dz/11/hints")).toHaveLength(1));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    version = 2;
    await userEvent.click(within(section).getByRole("button", { name: "Sprawdź CV przed DZ: Anna Nowak" }));
    dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Wersja poprawiona z/)).toBeTruthy();
    await waitFor(() => expect(post.mock.calls.filter((c) => c[0] === "/api/board-tasks/dz/11/hints")).toHaveLength(2));
  });

  it("przegląd DZ: awaria podpowiedzi nie blokuje — komunikat i „Ponów”", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/api/board-tasks")
        return Promise.resolve({ data: { window_days: 14, can_approve_dz: true, dz: [row("dz")], cpro_to_send: [], cpro_sent: [] } });
      if (url === "/api/board-tasks/dz/11/review")
        return Promise.resolve({
          data: {
            stage_id: 11, candidate_id: 21, candidate_name: "Anna Nowak", job_id: 31, job_title: "Java Developer", client_name: null,
            client_request: { must: [], nice: [], description: null, project_about: null },
            generated_cv: null,
            original_cv: { source: null, stage_id: null, filename: null, text: null },
            checks: [], extra_bold: [],
            summary: { must_total: 0, must_in_cv: 0, must_bolded: 0, roles_missing: 0, generated_roles: 0 },
          },
        });
      return Promise.resolve({ data: [] });
    });
    post.mockRejectedValue(new Error("boom"));
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na DZ" });
    await userEvent.click(within(section).getByRole("button", { name: "Sprawdź CV przed DZ: Anna Nowak" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Podpowiedzi AI są chwilowo niedostępne/)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Ponów" })).toBeTruthy();
    expect(within(dialog).getByText(/Rekruter nie przygotował jeszcze CV dla klienta/)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Zatwierdź DZ" })).toBeEnabled();
  });

  it("długa lista pokazuje najpierw kilka osób i „Pokaż wszystkie (N)”", async () => {
    mockQueue({
      cpro_sent: Array.from({ length: 9 }, (_, i) =>
        row("cpro_sent", { stage_id: 100 + i, candidate_id: 200 + i, candidate_name: `Osoba ${i + 1}` }),
      ),
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Wysłane do Cpro" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(6);
    await userEvent.click(within(section).getByRole("button", { name: "Pokaż wszystkie (9)" }));
    expect(within(section).getAllByRole("listitem")).toHaveLength(9);
    expect(within(section).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
  });

  it("recruiter bez prawa DZ nie dostaje przycisku zatwierdzenia", async () => {
    mockQueue({ can_approve_dz: false, dz: [row("dz")] });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na DZ" });
    expect(within(section).queryByRole("button")).toBeNull();
  });
});
