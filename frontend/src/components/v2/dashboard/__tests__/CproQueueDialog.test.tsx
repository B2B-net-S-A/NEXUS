import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const copyTextToClipboard = vi.fn();
const fetchAuthenticatedDownload = vi.fn();
const downloadBlob = vi.fn();

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
vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (...a: unknown[]) => copyTextToClipboard(...a),
}));
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => fetchAuthenticatedDownload(...a),
  downloadBlob: (...a: unknown[]) => downloadBlob(...a),
}));

import { CproQueueDialog } from "@/components/v2/dashboard/CproQueueDialog";
import type { CproQueueItem, CproQueueResponse } from "@/lib/api/boardTasks";
import { useAuthStore } from "@/store/auth";

const since = new Date(Date.now() - 2 * 86_400_000).toISOString();

const item = (over: Partial<CproQueueItem>): CproQueueItem => ({
  stage_id: 1,
  candidate_id: 1,
  candidate_name: "X",
  since,
  process_state_version: 3,
  target_stage_def_id: 44,
  return_stage_def_id: 41,
  client_rate_value: 158,
  client_rate_unit: "hourly",
  client_rate_currency: "PLN",
  availability: "2026-11-01",
  qc_status: "passed",
  cv: { generated_document_id: 5, document_id: null },
  ...over,
});

let queue: CproQueueResponse;

function freshQueue(): CproQueueResponse {
  return {
    sender: { user_id: 5, user_name: "Kinga Sordyl", until: null, fallback_user_id: null, fallback_user_name: null, set_by_name: null, set_at: null },
    sent_today: 2,
    jobs: [
      {
        job_id: 1,
        job_title: "Java Backend Developer",
        client_name: "Nordea",
        oldest_since: since,
        items: [
          item({ stage_id: 11, candidate_id: 21, candidate_name: "Robert Zieliński" }),
          item({ stage_id: 12, candidate_id: 22, candidate_name: "Magdalena Pawlak", availability: null, process_state_version: 7 }),
        ],
      },
      {
        job_id: 2,
        job_title: "Data Engineer",
        client_name: "Nordea",
        oldest_since: since,
        items: [item({ stage_id: 15, candidate_id: 25, candidate_name: "Piotr Nowak" })],
      },
    ],
  };
}

function renderDialog(initialJobId: number | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CproQueueDialog open onClose={vi.fn()} initialJobId={initialJobId} />
    </QueryClientProvider>,
  );
}

describe("CproQueueDialog — kolejka Cpro, jedna osoba na firmę", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queue = freshQueue();
    useAuthStore.setState({ user: { id: 1, role: "recruiter" } } as never);
    get.mockImplementation((url: string) => {
      if (url === "/api/board-tasks/cpro/queue") return Promise.resolve({ data: queue });
      if (url === "/api/board-tasks/cpro/sender") return Promise.resolve({ data: queue.sender });
      if (url === "/api/users") return Promise.resolve({ data: [{ id: 5, name: "Kinga Sordyl" }, { id: 7, name: "Ola Nowicka" }] });
      return Promise.reject(new Error(url));
    });
    post.mockResolvedValue({ data: {} });
  });

  it("rekrutacje z licznikami, osoby po kolei, pierwsza podświetlona, dane do przepisania", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Do Cpro wrzuca/)).toBeTruthy();
    expect(within(dialog).getByText("Kinga Sordyl")).toBeTruthy();
    const nav = within(dialog).getByRole("navigation", { name: "Rekrutacje" });
    const jobs = within(nav).getAllByRole("button");
    expect(jobs.map((b) => b.textContent)).toEqual([
      expect.stringMatching(/^Java Backend Developer.*najstarsza czeka od 2 dni2$/),
      expect.stringMatching(/^Data Engineer.*1$/),
    ]);
    expect(jobs[0]).toHaveAttribute("aria-current", "true");

    const rows = within(dialog).getAllByRole("listitem").filter((li) => li.closest("ol"));
    expect(rows.map((r) => r.querySelector("p")?.textContent)).toEqual(["Robert Zieliński", "Magdalena Pawlak"]);
    expect(rows[0]).toHaveAttribute("aria-current", "step");
    expect(rows[0]).toHaveTextContent("stawka do Cpro: 158 zł/h");
    expect(rows[0]).toHaveTextContent("dostępność: 01.11.2026");
    expect(rows[0]).toHaveTextContent("QC ✓");
    expect(rows[1]).toHaveTextContent("dostępność: od zaraz");
  });

  it("„✓ Wrzucone” to zwykły ruch na etap Cpro z wersją procesu; postęp i następna osoba", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Wrzucone do Cpro: Robert Zieliński" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 1,
        stage_def_id: 44,
        expected_state_version: 3,
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Robert Zieliński — wrzucone do Cpro.");
    expect(await within(dialog).findByText("1 z 2 wrzucone")).toBeTruthy();
    expect(within(dialog).getByText("✓ w Cpro")).toBeTruthy();
    const current = within(dialog).getAllByRole("listitem").find((li) => li.getAttribute("aria-current") === "step");
    expect(current).toHaveTextContent("Magdalena Pawlak");

    // Serwer zdejmuje wrzuconą osobę — postęp zostaje w tym oknie.
    queue.jobs[0].items = queue.jobs[0].items.slice(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Wrzucone do Cpro: Magdalena Pawlak" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(await within(dialog).findByText("2 z 2 wrzucone")).toBeTruthy();
    await userEvent.click(within(dialog).getByRole("button", { name: "Następna rekrutacja: Data Engineer →" }));
    expect(within(dialog).getByRole("region", { name: "Kolejka: Data Engineer" })).toBeTruthy();
  });

  it("„Zwróć do rekrutera” wymaga powodu i przesuwa na etap QC CV z notatką", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Nie da się wrzucić/ }));
    const group = within(dialog).getByRole("group", { name: "Zwrot do rekrutera" });
    const submit = within(group).getByRole("button", { name: "Zwróć do rekrutera" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(group).getByRole("textbox"), "Brak zgody RODO w CV");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 1,
        stage_def_id: 41,
        expected_state_version: 3,
        notes: "Brak zgody RODO w CV",
      }),
    );
  });

  it("„Kopiuj dane” i pobranie CV z generatora", async () => {
    copyTextToClipboard.mockResolvedValue(true);
    fetchAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["x"]), filename: "CV Robert.docx" });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Kopiuj dane: Robert Zieliński" }));
    await waitFor(() =>
      expect(copyTextToClipboard).toHaveBeenCalledWith(
        "Robert Zieliński\nRekrutacja: Java Backend Developer\nStawka do Cpro: 158 zł/h\nDostępność: 01.11.2026",
      ),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Pobierz CV: Robert Zieliński" }));
    await waitFor(() => expect(fetchAuthenticatedDownload).toHaveBeenCalledWith("/api/cv-generator/generated/5/docx"));
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "CV Robert.docx");
  });

  it("odmowa schowka — komunikat zamiast fałszywego „skopiowano”", async () => {
    copyTextToClipboard.mockResolvedValue(false);
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Kopiuj dane: Robert Zieliński" }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith(expect.stringMatching(/nie pozwoliła skopiować/)));
    expect(showSuccess).not.toHaveBeenCalled();
  });

  it("zmiana osoby od Cpro — dla całej firmy, z datą zastępstwa", async () => {
    put.mockResolvedValue({ data: { ...queue.sender, user_id: 7, user_name: "Ola Nowicka", until: "2026-10-03" } });
    renderDialog(2);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("region", { name: "Kolejka: Data Engineer" })).toBeTruthy();
    await userEvent.click(within(dialog).getByRole("button", { name: "Zmień" }));
    const popover = await screen.findByLabelText("Kto wrzuca do Cpro");
    const select = within(popover).getByRole("combobox");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Ola Nowicka" })).toBeTruthy());
    await userEvent.selectOptions(select, "7");
    const date = popover.querySelector('input[type="date"]') as HTMLInputElement;
    await userEvent.type(date, "2026-10-03");
    await userEvent.click(within(popover).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/board-tasks/cpro/sender", { user_id: 7, until: "2026-10-03" }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Do Cpro wrzuca: Ola Nowicka (do 03.10.2026).");
  });

  it("awaria kolejki to komunikat z „Ponów”, nie pustka", async () => {
    get.mockImplementation((url: string) =>
      url === "/api/board-tasks/cpro/queue"
        ? Promise.reject({ response: { status: 500, data: {} } })
        : Promise.resolve({ data: queue.sender }),
    );
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Nie udało się wczytać kolejki Cpro. Spróbuj ponownie.")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Ponów" })).toBeTruthy();
  });
});
