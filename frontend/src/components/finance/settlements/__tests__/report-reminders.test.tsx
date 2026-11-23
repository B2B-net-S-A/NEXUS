import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { recipientText, type ReminderOverview, type ReminderRow } from "@/lib/api/settlement-reminders";

import { ReportReminderButton, ReportReminderNotice, sendSummary } from "../ReportReminders";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
  extra: { current: null as ReactNode },
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({
    askConfirm: (request: { extra?: ReactNode }) => {
      mocks.extra.current = request.extra ?? null;
      return mocks.confirm(request);
    },
    confirmDialog: null,
  }),
}));

const row = (contract_id: number, person: string, extra: Partial<ReminderRow>): ReminderRow => ({
  contract_id,
  person,
  action: "none",
  consultant: { reachable: false, reason: "portal_closed", email: null },
  owner: null,
  last_reminder: null,
  ...extra,
});

const overview = (enabled = true): ReminderOverview => ({
  enabled,
  portal_state: "pilot",
  month: "2026-10",
  schedule: { day3: "2026-11-05", day5: "2026-11-07", day7: "2026-11-12" },
  settlements_address: "rozliczenia@example.com",
  clients: [
    {
      client_id: 7,
      client_name: "Bank Przykładowy",
      missing: 3,
      automatic: false,
      to_consultant: 1,
      to_owner: 1,
      without_recipient: 1,
      last_reminder_on: "2026-11-05",
      mail: { subject: "Raport godzin za październik 2026: prosimy o przesłanie", text: "Prześlij go, proszę, jako plik." },
      rows: [
        row(1, "Jan Próbny", {
          action: "mail",
          consultant: { reachable: true, reason: "ok", email: "k@example.com" },
          owner: { user_id: 5, name: "Opiekun Testowy", source: "contract_care" },
        }),
        row(2, "Ewa Nowa", {
          action: "bell",
          consultant: { reachable: false, reason: "no_panel", email: null },
          owner: { user_id: 6, name: "Lider Testowy", source: "client_dl" },
        }),
        row(3, "Adam Brak", {}),
      ],
    },
  ],
});

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("Przypomnienia o raporcie godzin", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.confirm.mockResolvedValue(true);
    mocks.extra.current = null;
  });

  it("przycisk liczy tylko osoby z adresatem i po potwierdzeniu wysyła", async () => {
    mocks.get.mockResolvedValue({ data: overview() });
    mocks.post.mockResolvedValue({
      data: { missing: 3, mails: 1, bells: 1, already_today: 0, without_recipient: 1, failed: 0 },
    });
    renderWith(<ReportReminderButton clientId={7} month="2026-10" />);
    fireEvent.click(await screen.findByRole("button", { name: "Przypomnij (2)" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/reminders/send", {
        client_id: 7,
        month: "2026-10",
      }),
    );
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements/reminders", {
      params: { month: "2026-10", client_id: 7 },
    });
    expect(mocks.success).toHaveBeenCalledWith(
      "Przypomnienia: maile: 1, dzwonki opiekunów: 1, bez adresata: 1.",
    );
  });

  it("podgląd w potwierdzeniu pokazuje treść maila, adresatów i brak adresata", async () => {
    mocks.get.mockResolvedValue({ data: overview() });
    mocks.confirm.mockResolvedValue(false);
    renderWith(<ReportReminderButton clientId={7} month="2026-10" />);
    fireEvent.click(await screen.findByRole("button", { name: "Przypomnij (2)" }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    renderWith(<>{mocks.extra.current}</>);
    expect(screen.getByText("Raport godzin za październik 2026: prosimy o przesłanie")).toBeInTheDocument();
    expect(screen.getByText("mail do konsultanta, w kopii Opiekun Testowy")).toBeInTheDocument();
    expect(screen.getByText(/dzwonek: Lider Testowy \(Delivery Lead klienta\)/)).toBeInTheDocument();
    expect(screen.queryByText("Adam Brak")).not.toBeInTheDocument();
    expect(screen.getByText(/Bez adresata: 1/)).toBeInTheDocument();
    expect(screen.getByText(/automat 3\., 5\. i 7\. dnia roboczego go pomija/)).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("wyłączone przypomnienia = przycisk nieaktywny z powodem", async () => {
    mocks.get.mockResolvedValue({ data: overview(false) });
    renderWith(<ReportReminderButton clientId={7} month="2026-10" />);
    const button = await screen.findByRole("button", { name: "Przypomnij (2)" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", expect.stringContaining("Start rozliczeń"));
  });

  it("lista bez adresata i data ostatniego przypomnienia pod filtrem", async () => {
    mocks.get.mockResolvedValue({ data: overview() });
    renderWith(<ReportReminderNotice clientId={7} month="2026-10" />);
    expect(await screen.findByText(/Bez adresata \(1\): Adam Brak/)).toBeInTheDocument();
    expect(screen.getByText("Ostatnie przypomnienie: 05.11")).toBeInTheDocument();
  });

  it("opis adresata dla każdego powodu", () => {
    const nobody = row(9, "X", { consultant: { reachable: false, reason: "client_report", email: null } });
    expect(recipientText(nobody)).toBe("bez adresata: brak opiekuna i DL-a klienta; raport przysyła klient");
    expect(sendSummary({ missing: 0, mails: 0, bells: 0, already_today: 0, without_recipient: 0, failed: 0 })).toBe(
      "Nie było do kogo wysłać przypomnienia.",
    );
  });
});
