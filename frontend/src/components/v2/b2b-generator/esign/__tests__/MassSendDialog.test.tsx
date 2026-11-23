import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MassSendBatch,
  MassSendPreview,
  MassSendSettings,
} from "@/lib/api/b2bMassSend";

const mocks = vi.hoisted(() => ({
  settings: vi.fn(),
  saveSettings: vi.fn(),
  preview: vi.fn(),
  dryRun: vi.fn(),
  start: vi.fn(),
  current: vi.fn(),
  items: vi.fn(),
  cancel: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

vi.mock("@/lib/api/b2bMassSend", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/b2bMassSend")>();
  return {
    ...actual,
    b2bMassSendApi: {
      settings: (...a: unknown[]) => mocks.settings(...a),
      saveSettings: (...a: unknown[]) => mocks.saveSettings(...a),
      preview: (...a: unknown[]) => mocks.preview(...a),
      dryRun: (...a: unknown[]) => mocks.dryRun(...a),
      start: (...a: unknown[]) => mocks.start(...a),
      current: (...a: unknown[]) => mocks.current(...a),
      items: (...a: unknown[]) => mocks.items(...a),
      cancel: (...a: unknown[]) => mocks.cancel(...a),
    },
  };
});

import { MassSendButton, MassSendDialog, clientRows } from "../MassSendDialog";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function settings(overrides: Partial<MassSendSettings> = {}): MassSendSettings {
  return {
    template_ready: false,
    template_ready_at: null,
    template_ready_by: null,
    template_label: "Umowa B2B, obecny wzór Generatora",
    worker_enabled: true,
    can_start: true,
    mailbox_connected: true,
    company_signers: [{ id: 9, name: "Reprezentant Fikcyjny" }],
    link_days: [1, 3, 5, 7, 14],
    chunk_size: 50,
    ...overrides,
  };
}

const CLIENTS = [
  ["Klient A", 30, 28],
  ["Klient B", 20, 19],
  ["Klient C", 10, 10],
  ["Klient D", 8, 7],
  ["Klient E", 5, 5],
  ["Klient F", 4, 4],
  ["Klient G", 2, 1],
  ["Klient H", 1, 1],
] as const;

function preview(overrides: Partial<MassSendPreview["summary"]> = {}): MassSendPreview {
  return {
    summary: {
      total: 80,
      ready: 75,
      needs_review: 3,
      skipped: 2,
      ending_soon: 4,
      by_reason: {},
      by_client: CLIENTS.map(([name, total, ready], i) => ({
        client_id: i + 1,
        client_name: name,
        total,
        ready,
      })),
      ...overrides,
    },
    rows: [
      {
        contract_id: 1,
        candidate_id: 11,
        name: "Anna Przykładowa",
        client_id: 1,
        client_name: "Klient A",
        status: "needs_review",
        reason: "missing_data",
        reason_label: "Brakuje danych do umowy",
        missing: ["Miasto Klienta", "REGON"],
        issues: [],
        data_source: "generator",
        end_date: null,
      },
    ],
    rows_total: 3,
    no_email: [{ id: 12, name: "Piotr Bezmailowy" }],
  };
}

function batch(overrides: Partial<MassSendBatch> = {}): MassSendBatch {
  return {
    id: 4,
    status: "running",
    started_by: { id: 1, name: "Osoba Wysyłająca" },
    company_signer: { id: 9, name: "Reprezentant Fikcyjny" },
    link_days: 14,
    skip_ending: true,
    template_label: "Umowa B2B, obecny wzór Generatora",
    planned: { total: 80, ready: 75, needs_review: 3, skipped: 2 },
    created_at: "2026-11-23T09:00:00Z",
    finished_at: null,
    cancelled_at: null,
    template_ready: true,
    progress: {
      pending: 25,
      created: 0,
      sent: 50,
      failed: 1,
      needs_review: 3,
      skipped: 2,
      waiting_contractor: 40,
      waiting_company: 6,
      signed: 4,
      closed: 0,
    },
    ...overrides,
  };
}

describe("clientRows", () => {
  it("pokazuje sześciu klientów z nazwy, resztę jako „Pozostali klienci”", () => {
    const rows = clientRows(preview().summary.by_client);
    expect(rows).toHaveLength(7);
    expect(rows[6]).toEqual({ name: "Pozostali klienci", ready: 2, total: 3 });
  });
});

describe("MassSendDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.current.mockResolvedValue(null);
    mocks.preview.mockResolvedValue(preview());
  });

  it("przy niepodpiętym wzorze blokuje wysyłkę, a próba działa i mówi, co blokuje", async () => {
    mocks.dryRun.mockResolvedValue({
      summary: { ...preview().summary, ready: 74, needs_review: 4 },
      problems: [
        {
          ...preview().rows[0],
          name: "Jan Testowy",
          issues: ["Kandydat nie uczestniczy w wybranej rekrutacji."],
        },
      ],
      would_send: 74,
      blocked: true,
      block_reasons: ["Nowy wzór umowy nie jest jeszcze podpięty."],
    });
    const user = userEvent.setup();
    wrap(<MassSendDialog isAdmin={false} settings={settings()} onClose={() => undefined} />);

    expect(
      await screen.findByText(/Wysyłka zablokowana: nowy wzór umowy nie jest jeszcze podpięty/),
    ).toBeInTheDocument();
    const send = await screen.findByRole("button", { name: /Wyślij 75 umów/ });
    expect(send).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Próba bez wysyłki/ }));
    expect(mocks.dryRun).toHaveBeenCalledWith(true);
    expect(await screen.findByText(/Próba: 74 umowy by poszło, 4 do sprawdzenia/)).toBeInTheDocument();
    expect(screen.getByText(/Jan Testowy: Kandydat nie uczestniczy/)).toBeInTheDocument();
    expect(screen.getByText("Nowy wzór umowy nie jest jeszcze podpięty.")).toBeInTheDocument();
    expect(mocks.start).not.toHaveBeenCalled();
  });

  it("pokazuje odbiorców po klientach, osoby bez e-maila i braki do sprawdzenia", async () => {
    const user = userEvent.setup();
    wrap(<MassSendDialog isAdmin={false} settings={settings()} onClose={() => undefined} />);

    const table = await screen.findByRole("table", { name: "Odbiorcy według klienta" });
    expect(within(table).getByText("Klient A")).toBeInTheDocument();
    expect(within(table).getByText("28 z 30")).toBeInTheDocument();
    expect(within(table).getByText("Pozostali klienci")).toBeInTheDocument();
    expect(screen.getByText(/Piotr Bezmailowy/)).toBeInTheDocument();
    expect(screen.getByText(/Brakuje: Miasto Klienta, REGON\./)).toBeInTheDocument();
    expect(screen.getByText(/Umowa: podpis kwalifikowany obu stron/)).toBeInTheDocument();

    await user.click(
      screen.getByRole("checkbox", { name: /Pomiń osoby, którym umowa kończy się w ciągu 30 dni/ }),
    );
    await waitFor(() =>
      expect(mocks.preview).toHaveBeenLastCalledWith(
        expect.objectContaining({ skip_ending: false }),
      ),
    );
  });

  it("awaria podglądu to komunikat, nie pusta lista", async () => {
    mocks.preview.mockRejectedValue(new Error("boom"));
    wrap(<MassSendDialog isAdmin={false} settings={settings()} onClose={() => undefined} />);
    expect(await screen.findByText("Nie udało się policzyć odbiorców")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma aktywnych kontraktów B2B/)).not.toBeInTheDocument();
  });

  it("po podpięciu wzoru wysyła z reprezentantem i terminem, potem pokazuje postęp", async () => {
    mocks.start.mockResolvedValue(batch({ progress: { ...batch().progress, sent: 0 } }));
    const user = userEvent.setup();
    wrap(
      <MassSendDialog
        isAdmin={false}
        settings={settings({ template_ready: true })}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(await screen.findByLabelText("Termin na podpis"), "7");
    const send = await screen.findByRole("button", { name: /Wyślij 75 umów/ });
    await waitFor(() => expect(send).toBeEnabled());
    await user.click(send);
    expect(mocks.start).toHaveBeenCalledWith({
      skip_ending: true,
      company_signer_id: 9,
      days: 7,
    });
    expect(await screen.findByText("Wysłano 0 z 75")).toBeInTheDocument();
  });

  it("bez połączonej skrzynki nie da się zacząć i mówi dlaczego", async () => {
    wrap(
      <MassSendDialog
        isAdmin={false}
        settings={settings({ template_ready: true, mailbox_connected: false })}
        onClose={() => undefined}
      />,
    );
    expect(await screen.findByRole("button", { name: /Wyślij 75 umów/ })).toBeDisabled();
    expect(screen.getByText(/Twoja skrzynka Microsoft 365 nie jest połączona/)).toBeInTheDocument();
  });

  it("trwająca wysyłka pokazuje wysłane, podpisy, firmę i problemy, a zatrzymanie pyta", async () => {
    mocks.current.mockResolvedValue(batch());
    mocks.items.mockResolvedValue({
      items: [
        {
          id: 1,
          candidate_id: 3,
          name: "Ewa Problemowa",
          client_name: "Klient A",
          status: "failed",
          reason: null,
          reason_label: null,
          missing: [],
          error: "Mail z linkiem nie wyszedł, wysyłkę tej osoby wycofano.",
          contract_number: "1700/2026",
          generated_contract_id: 8,
          signing_status: "withdrawn",
        },
      ],
      total: 1,
    });
    mocks.cancel.mockResolvedValue(batch({ status: "cancelled" }));
    const user = userEvent.setup();
    wrap(
      <MassSendDialog
        isAdmin={false}
        settings={settings({ template_ready: true })}
        onClose={() => undefined}
      />,
    );
    expect(await screen.findByText("Wysłano 50 z 75")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "67");
    expect(screen.getByText("Podpisali").nextSibling).toHaveTextContent("4");
    expect(screen.getByText("Czeka na firmę").nextSibling).toHaveTextContent("6");
    expect(await screen.findByText(/Mail z linkiem nie wyszedł/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zatrzymaj wysyłkę" }));
    const confirm = await screen.findByRole("dialog", { name: "Zatrzymać wysyłkę?" });
    await user.click(within(confirm).getByRole("button", { name: "Zatrzymaj wysyłkę" }));
    await waitFor(() => expect(mocks.cancel).toHaveBeenCalled());
  });

  it("admin oznacza nowy wzór jako podpięty dopiero po potwierdzeniu", async () => {
    mocks.saveSettings.mockResolvedValue(settings({ template_ready: true }));
    const user = userEvent.setup();
    wrap(<MassSendDialog isAdmin settings={settings()} onClose={() => undefined} />);
    await user.click(
      await screen.findByRole("button", { name: "Oznacz nowy wzór jako podpięty" }),
    );
    expect(mocks.saveSettings).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("dialog", {
      name: "Oznaczyć nowy wzór umowy jako podpięty?",
    });
    await user.click(within(confirm).getByRole("button", { name: "Nowy wzór podpięty" }));
    await waitFor(() => expect(mocks.saveSettings).toHaveBeenCalledWith(true));
  });
});

describe("MassSendButton", () => {
  beforeEach(() => vi.clearAllMocks());

  it("przy niepodpiętym wzorze widzi go tylko admin", async () => {
    mocks.settings.mockResolvedValue(settings());
    const { unmount } = wrap(<MassSendButton isAdmin={false} />);
    await waitFor(() => expect(mocks.settings).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Nowa umowa dla aktywnych/ })).toBeNull();
    unmount();
    wrap(<MassSendButton isAdmin />);
    expect(
      await screen.findByRole("button", { name: /Nowa umowa dla aktywnych/ }),
    ).toBeInTheDocument();
  });

  it("po podpięciu wzoru widzi go każdy, kto wysyła umowy do podpisu", async () => {
    mocks.settings.mockResolvedValue(settings({ template_ready: true }));
    wrap(<MassSendButton isAdmin={false} />);
    expect(
      await screen.findByRole("button", { name: /Nowa umowa dla aktywnych/ }),
    ).toBeInTheDocument();
  });

  it("bez prawa wysyłki do podpisu przycisku nie ma", async () => {
    mocks.settings.mockResolvedValue(settings({ template_ready: true, can_start: false }));
    wrap(<MassSendButton isAdmin={false} />);
    await waitFor(() => expect(mocks.settings).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Nowa umowa dla aktywnych/ })).toBeNull();
  });
});
