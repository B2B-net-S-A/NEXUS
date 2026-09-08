/**
 * Krok 08 „Umowa" — karta zamknięcia czyta stan trzech modułów i nic nie zgaduje.
 *
 * Dwie rzeczy pod szczególną ochroną:
 *
 * 1. **Zamknięcie rekrutacji jest PRZYCISKIEM, nie skutkiem ubocznym.** Backend
 *    po zatrudnieniu wysyła wyłącznie podpowiedź; ekran nie może tego zrobić za
 *    człowieka ani ukryć przycisku przed rolą, która ma do niego prawo.
 * 2. **Awaria pobrania umów nie może udawać „nie ma umowy".** Rejestr umów
 *    B2B stoi za osobną bramką i osobnym zapytaniem — 403 albo 500 wygląda
 *    stąd identycznie jak brak dokumentu, jeśli się tego nie rozdzieli.
 */

import type { ComponentProps } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const generated = vi.fn();
const statusHistory = vi.fn();
const closeJob = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
  b2bGeneratorApi: {
    generated: (...a: unknown[]) => generated(...a),
    statusHistory: (...a: unknown[]) => statusHistory(...a),
  },
  jobsApi: { close: (...a: unknown[]) => closeJob(...a) },
  CONTRACT_FIELD_LABELS: {
    start_date: "Data rozpoczęcia",
    rate_candidate: "Stawka kosztowa (kandydata)",
    rate_client: "Stawka przychodowa (klienta)",
    contract_type: "Typ kontraktu",
    end_date: "Data zakończenia",
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { JobContractTab } from "@/components/v2/jobs/JobContractTab";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";

function columns(): KanbanColumn[] {
  return [
    {
      stage: "client_interview",
      name: "Interview Klient",
      category: "external",
      count: 0,
      items: [],
      stage_def_id: 6,
    },
    {
      stage: "new",
      name: "Umowa wysłana",
      category: "external",
      count: 1,
      items: [
        {
          id: 700,
          candidate_id: 42,
          stage: "new",
          name: "Grzegorz",
          lastname: "Żebrowski",
          days_in_stage: 2,
        },
      ],
      stage_def_id: 20,
    },
    {
      stage: "hired",
      name: "Zatrudniony",
      category: "terminal",
      count: 0,
      items: [],
      stage_def_id: 12,
      terminal_type: "hired",
    },
  ];
}

const contractRow = {
  id: 5,
  contract_number: "1436/2026",
  partner_name: "Grzegorz Żebrowski",
  partner_display_name: null,
  partner_secondary_line: null,
  partner_nip: null,
  start_date: "2026-10-01",
  client_name: "PKO BP",
  language: "pl",
  signing_date: null,
  created_at: "2026-09-16T09:00:00Z",
  created_by_name: "Marta K.",
  signature_status: "unsigned" as const,
  signature_source: null,
  contract_status: "in_progress" as const,
  closure_reason: null,
  closure_reason_other: null,
  closure_date: null,
  can_change_status: true,
  candidate_id: 42,
  job_id: 10,
  client_id: 3,
  contract_id: 77,
  candidate_name: "Grzegorz Żebrowski",
  job_title: "Programista Python",
  canonical_client_name: "PKO BP",
  signed_at: null,
  signed_by_name: null,
  can_confirm_signed: true,
  blocked_reason: null,
  can_delete: true,
  can_edit: true,
  can_download: true,
};

type Props = ComponentProps<typeof JobContractTab>;

function renderTab(overrides: Partial<Props> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props: Props = {
    jobId: 10,
    jobTitle: "Programista Python",
    clientId: 3,
    columns: columns(),
    readOnly: false,
    canCloseJob: true,
    ...overrides,
  };
  render(
    <QueryClientProvider client={qc}>
      <JobContractTab {...props} />
    </QueryClientProvider>,
  );
  return props;
}

beforeEach(() => {
  vi.clearAllMocks();
  generated.mockResolvedValue([contractRow]);
  statusHistory.mockResolvedValue([]);
  closeJob.mockResolvedValue({ data: {} });
});

describe("JobContractTab", () => {
  it("pyta backend o umowy TEJ rekrutacji, a nie filtruje pobranego rejestru", async () => {
    renderTab();
    await waitFor(() => expect(generated).toHaveBeenCalled());
    expect(generated).toHaveBeenCalledWith(50, { jobId: 10 });
  });

  it("pokazuje numer i status podpisu wygenerowanej umowy", async () => {
    renderTab();
    expect(await screen.findByText("1436/2026")).toBeTruthy();
    expect(screen.getAllByText("Czeka na podpis").length).toBeGreaterThan(0);
    expect(screen.getByText("Umowa wygenerowana")).toBeTruthy();
  });

  it("bez wygenerowanej umowy mówi to wprost, zamiast pustki", async () => {
    generated.mockResolvedValue([]);
    renderTab();
    expect(
      await screen.findByText(/nie wygenerowano jeszcze umowy B2B/i),
    ).toBeTruthy();
  });

  it("awaria pobrania umów renderuje się jako awaria, nie jako brak umowy", async () => {
    generated.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );
    renderTab();
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeTruthy();
    expect(screen.queryByText(/nie wygenerowano jeszcze umowy B2B/i)).toBeNull();
  });

  it("403 na rejestrze umów to brak uprawnień, a nie brak danych", async () => {
    generated.mockRejectedValue(
      Object.assign(new Error("nope"), { response: { status: 403 } }),
    );
    renderTab();
    expect(await screen.findByText("Brak uprawnień")).toBeTruthy();
  });

  it("wypisuje bramkę aktywacji BEZ daty zakończenia", async () => {
    renderTab();
    expect(
      await screen.findByText("Czego wymaga aktywacja kontraktu"),
    ).toBeTruthy();
    for (const label of [
      "Data rozpoczęcia",
      "Stawka kosztowa (kandydata)",
      "Stawka przychodowa (klienta)",
      "Typ kontraktu",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    // „Data zakończenia" pada tylko w zdaniu wyjaśniającym, nie na liście
    // wymaganych pól — wymaganie jej więziło kompletne kontrakty w szkicu.
    expect(screen.queryByText("Data zakończenia")).toBeNull();
    expect(screen.getByText(/NIE jest wymagana/)).toBeTruthy();
  });

  it("zamyka rekrutację z powodem — przyciskiem, nie automatem", async () => {
    renderTab();
    await userEvent.click(
      await screen.findByRole("button", { name: /Zamknij rekrutację z powodem/ }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Zamknij rekrutację" }),
    );
    await waitFor(() => expect(closeJob).toHaveBeenCalledTimes(1));
    expect(closeJob).toHaveBeenCalledWith(10, "other", "");
  });

  it("rola bez `job.update` nie dostaje przycisku, tylko powód", async () => {
    renderTab({ canCloseJob: false });
    expect(
      await screen.findByText(/wymaga roli TAC, Delivery Leada albo/i),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /Zamknij rekrutację z powodem/ }),
    ).toBeNull();
  });

  it("pusty krok mówi, że nikt nie doszedł do umowy", async () => {
    const empty = columns().map((c) => ({ ...c, items: [], count: 0 }));
    renderTab({ columns: empty });
    expect(
      await screen.findByText("Nikt nie doszedł jeszcze do umowy"),
    ).toBeTruthy();
  });

  it("awaria kanbana NIE udaje pustego kroku", async () => {
    renderTab({
      columns: [],
      columnsSuccess: false,
      columnsError: { response: { status: 500 } },
    });
    expect(screen.getByText("Nie udało się pobrać danych")).toBeTruthy();
    expect(screen.queryByText("Nikt nie doszedł jeszcze do umowy")).toBeNull();
  });
});
