/**
 * Historia zmian formularza screeningu (0424): wersje z autorem i zmianami
 * „przed → po”, przywrócenie z potwierdzeniem w wierszu (bez `confirm()`),
 * komunikaty o stawce i pominiętych odpowiedziach, awaria ≠ pustka.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScreeningFormVersion } from "@/lib/api/screeningForm";
import { FORM_CANDIDATE_ID, FORM_JOB_ID, formSaveResult, formState } from "@/test/fixtures/screening-form";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
  };
  return { __esModule: true, default: client, api: client };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError, showInfo: mocks.showInfo }),
}));

import { ScreeningFormHistory, ScreeningFormHistoryView } from "../ScreeningFormHistory";

const VERSIONS: ScreeningFormVersion[] = [
  {
    version_no: 2,
    action: "save",
    source: "note_import",
    created_at: "2026-10-07T10:00:00Z",
    created_by: 5,
    created_by_name: "Marta Testowa",
    restored_from_version: null,
    note_id: 77,
    changes: [
      { section: "terms", key: "availability", label: "Dostępność", before: null, after: "od zaraz" },
      { section: "rate", key: "rate", label: "Stawka", before: "140 zł/h", after: "150 zł/h" },
    ],
  },
  {
    version_no: 1,
    action: "baseline",
    source: "form",
    created_at: "2026-10-06T09:00:00Z",
    created_by: null,
    created_by_name: null,
    restored_from_version: null,
    note_id: null,
    changes: [],
  },
];

function mount(props: Partial<Parameters<typeof ScreeningFormHistory>[0]> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ScreeningFormHistory
        candidateId={FORM_CANDIDATE_ID}
        jobId={FORM_JOB_ID}
        currentVersion={2}
        stateToken="token-2"
        canRestore
        {...props}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
  mocks.get.mockResolvedValue({ data: { items: VERSIONS, total: 2 } });
});

describe("ScreeningFormHistory", () => {
  it("pokazuje wersje z autorem, źródłem i zmianami „przed → po”", async () => {
    mount();
    const row = (await screen.findByText("Wersja 2")).closest("li") as HTMLElement;
    expect(within(row).getByText(/Zapis · z notatki/)).toBeInTheDocument();
    expect(within(row).getByText(/Marta Testowa/)).toBeInTheDocument();
    expect(within(row).getByText("bieżąca")).toBeInTheDocument();
    expect(within(row).getByText("od zaraz")).toBeInTheDocument();
    expect(within(row).getByText("140 zł/h")).toBeInTheDocument();
    // Bieżąca wersja nie ma „Przywróć”.
    expect(within(row).queryByRole("button", { name: /Przywróć/ })).toBeNull();

    const baseline = screen.getByText("Wersja 1").closest("li") as HTMLElement;
    expect(within(baseline).getByText(/Stan przed formularzem/)).toBeInTheDocument();
    expect(within(baseline).getByText(/system/)).toBeInTheDocument();
    expect(within(baseline).getByText("Bez zmian treści.")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/screening-form/versions",
      expect.objectContaining({ params: { candidate_id: FORM_CANDIDATE_ID, job_id: FORM_JOB_ID } }),
    );
  });

  it("„Przywróć” wymaga potwierdzenia w wierszu i wysyła wersję z bieżącą wersją formularza", async () => {
    const result = {
      ...formSaveResult(formState({ version: 2 })),
      rate_not_restored: true,
      rate_not_restored_reason: "managed_by_dl" as const,
      skipped_answers: ["q2"],
    };
    mocks.post.mockResolvedValue({ data: result });
    const onRestored = vi.fn();
    const user = userEvent.setup();
    mount({ dirty: true, onRestored });

    await user.click(await screen.findByRole("button", { name: "Przywróć wersję 1" }));
    const confirm = screen.getByRole("group", { name: "Przywrócić wersję 1?" });
    expect(confirm).toHaveTextContent("Niezapisane zmiany w formularzu przepadną.");
    expect(mocks.post).not.toHaveBeenCalled();

    await user.click(within(confirm).getByRole("button", { name: "Przywróć" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/screening-form/restore", {
        candidate_id: FORM_CANDIDATE_ID,
        job_id: FORM_JOB_ID,
        version_no: 1,
        expected_version: 2,
        state_token: "token-2",
        mode: "restore",
      }),
    );
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalledWith("Przywrócono wersję 1."));
    expect(onRestored).toHaveBeenCalledWith(result);
    expect(mocks.showInfo).toHaveBeenCalledWith(
      "Stawka nie wróciła — od „Zweryfikowany” zmianą stawki zarządza Delivery Lead.",
    );
    expect(mocks.showInfo).toHaveBeenCalledWith(
      "Pominięto 1 odpowiedź — treść pytania w Profilu Championa się zmieniła.",
    );
  });

  it("wersja bez stawki: stawka kandydata zostaje i komunikat to mówi", async () => {
    mocks.post.mockResolvedValue({
      data: {
        ...formSaveResult(formState({ version: 2 })),
        rate_not_restored: true,
        rate_not_restored_reason: "not_in_version",
        skipped_answers: [],
      },
    });
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("button", { name: "Przywróć wersję 1" }));
    const confirm = screen.getByRole("group", { name: "Przywrócić wersję 1?" });
    await user.click(within(confirm).getByRole("button", { name: "Przywróć" }));

    await waitFor(() =>
      expect(mocks.showInfo).toHaveBeenCalledWith(
        "Stawka kandydata została — ta wersja jej nie miała. Zmień ją w formularzu.",
      ),
    );
  });

  it("„Anuluj” w potwierdzeniu nic nie wysyła", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Przywróć wersję 1" }));
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByRole("group", { name: "Przywrócić wersję 1?" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("bez prawa przywracania (proces zakończony) nie ma przycisków", async () => {
    mount({ canRestore: false });
    await screen.findByText("Wersja 1");
    expect(screen.queryByRole("button", { name: /Przywróć/ })).toBeNull();
  });

  it("awaria wczytania to komunikat z „Ponów”, nie pusta historia", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać historii zmian.");
    expect(screen.queryByText("Formularz nie ma jeszcze zapisanych wersji.")).toBeNull();
  });

  it("widok: pusta historia mówi to wprost", () => {
    render(<ScreeningFormHistoryView versions={[]} total={0} currentVersion={0} canRestore />);
    expect(screen.getByText("Formularz nie ma jeszcze zapisanych wersji.")).toBeInTheDocument();
  });
});
