import { beforeEach, describe, expect, it, vi } from "vitest";
import { configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import type { GeneratedCvItem } from "@/lib/api";

import { MyCvList, groupPackageRows } from "../MyCvList";
import { remarksLabel } from "../GeneratedCvRow";

// Wyszukiwanie z debounce i kaskada zapytań — pod obciążeniem (pełny
// przebieg na współdzielonej maszynie) domyślna sekunda to za mało.
configure({ asyncUtilTimeout: 10000 });

vi.mock("@/components/v2/modals/CVBrandedEditModal", () => ({ CVBrandedEditModal: () => null }));

function item(partial: Partial<GeneratedCvItem> & Pick<GeneratedCvItem, "id">): GeneratedCvItem {
  return {
    candidate_name: "Jan Kowalski", candidate_id: 1, job_id: 5, client_name: "PKO BP", position: "Senior Java Developer",
    language: "pl", blind: false, mode: "new", content_mode: "tailored", filename: `CV_${partial.id}.docx`,
    status: "ready", warnings: [], can_download: true, can_delete: true, created_at: new Date().toISOString(),
    ...partial,
  };
}

const ROWS = [
  item({ id: 10, language: "en", warnings: ["MUST-HAVE: Kafka", "MUST-HAVE: Kubernetes", "NICE-TO-HAVE: AWS"], consent_required: true, consent_missing: true }),
  item({ id: 11, package_id: 10, language: "pl" }),
  item({ id: 12, candidate_name: "Paweł Wójcik", status: "failed", job_status: "failed" }),
  item({ id: 13, candidate_name: "Tomasz Dąbrowski", job_id: null }),
];

const listMock = vi.fn(async (_params: unknown) => ({ data: ROWS }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    cvGeneratorApi: {
      listGenerated: (params: unknown) => listMock(params),
      identifyUpload: vi.fn(),
      uploadConsentForGenerated: vi.fn(),
      attachConsent: vi.fn(),
      deleteGenerated: vi.fn(),
    },
  };
});

function renderList(props: Partial<Parameters<typeof MyCvList>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MyCvList canWrite {...props} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => listMock.mockClear());

describe("Moje CV", () => {
  it("domyślnie pyta o moje CV z 30 dni, filtry idą do serwera", async () => {
    renderList();
    await screen.findByText("Jan Kowalski");
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ mine: true, days: 30 }));

    fireEvent.click(screen.getByRole("button", { name: "Wszyscy" }));
    await waitFor(() => expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ mine: false, days: 30 })));
    fireEvent.change(screen.getByLabelText("Okres"), { target: { value: "90" } });
    await waitFor(() => expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ days: 90 })));
    fireEvent.change(screen.getByLabelText("Szukaj osoby"), { target: { value: "Wójcik" } });
    await waitFor(() => expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: "Wójcik" })));
  });

  it("pakiet „Obie” to jeden wiersz z dwoma językami; uwagi to tylko „Do sprawdzenia”", async () => {
    renderList();
    const row = (await screen.findByText("Jan Kowalski")).closest("tr")!;
    expect(within(row).getByText("EN")).toBeInTheDocument();
    expect(within(row).getByText("PL")).toBeInTheDocument();
    expect(within(row).getByText("2 uwagi")).toBeInTheDocument();
    expect(within(row).getByText("brak zgody RODO")).toBeInTheDocument();
    expect(screen.getAllByText("Jan Kowalski")).toHaveLength(1);
  });

  it("nieudane CV ma „Ponów”, CV bez procesu jest oznaczone", async () => {
    const onRetry = vi.fn();
    renderList({ onRetry });
    const failed = (await screen.findByText("Paweł Wójcik")).closest("tr")!;
    fireEvent.click(within(failed).getByRole("button", { name: "Ponów" }));
    expect(onRetry).toHaveBeenCalledWith(expect.objectContaining({ id: 12 }));
    const noProcess = screen.getByText("Tomasz Dąbrowski").closest("tr")!;
    expect(within(noProcess).getByText("bez procesu")).toBeInTheDocument();
  });

  it("„Otwórz” pokazuje widok wyniku z blokadą pobrania bez zgody", async () => {
    renderList();
    const row = (await screen.findByText("Jan Kowalski")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Otwórz" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Pobranie zablokowane/)).toBeInTheDocument();
    for (const button of within(dialog).getAllByRole("button", { name: /Pobierz DOCX/ })) {
      expect(button).toBeDisabled();
    }
    expect(within(dialog).getByRole("button", { name: "Wgraj zrzut maila" })).toBeInTheDocument();
  });

  it("zawężona do osoby — bez filtrów, pyta po candidate_id i job_id", async () => {
    renderList({ candidateId: 1, jobId: 5 });
    await screen.findByText("Jan Kowalski");
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ candidate_id: 1, job_id: 5 }));
    expect(screen.queryByRole("button", { name: "Wszyscy" })).not.toBeInTheDocument();
  });
});

describe("pomocnicze", () => {
  it("odmiana „uwaga”", () => {
    expect([1, 2, 4, 5, 12, 22, 25].map(remarksLabel)).toEqual([
      "1 uwaga", "2 uwagi", "4 uwagi", "5 uwag", "12 uwag", "22 uwagi", "25 uwag",
    ]);
  });
  it("wersja językowa bez głównego dokumentu na liście zostaje osobnym wierszem", () => {
    expect(groupPackageRows([item({ id: 2, package_id: 1 })]).map((r) => r.item.id)).toEqual([2]);
  });
});
