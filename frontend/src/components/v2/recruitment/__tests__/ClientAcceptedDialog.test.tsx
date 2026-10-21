/**
 * Okno „Klient zaakceptował” (D1–D6, 16.10.2026): data, debrief, kto dostanie
 * dzwonek. Zapis oddaje wartości wołającemu — ruch i werdykt robi Tablica.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  verdicts: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
}));

vi.mock("@/lib/api", () => {
  const api = {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  };
  return {
    default: api,
    api,
    hiringManagerFeedbackApi: { list: (...a: unknown[]) => mocks.verdicts(...a) },
  };
});
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { ClientAcceptedDialog } from "@/components/v2/recruitment/ClientAcceptedDialog";
import { warsawToday } from "@/lib/warsaw-date";

const RECIPIENTS = [
  { user_id: 7, name: "Marta Nowak", role: "recruiter", role_label: "rekruter kandydata" },
  { user_id: 9, name: "Olaf Przykładowy", role: "head_of_recruitment", role_label: "Head of Recruitment" },
];

function requirements(items: unknown[] = []) {
  return {
    from_column: "client_interview",
    to_column: "contract",
    skipped_columns: [],
    items,
    primary: { kind: "move", label: "Przesuń na „Akceptacja i umowa”" },
  };
}

function serve({
  recipients = RECIPIENTS as unknown,
  items = [] as unknown[],
  recipientsFail = false,
}: { recipients?: unknown; items?: unknown[]; recipientsFail?: boolean } = {}) {
  mocks.get.mockImplementation((url: string) => {
    if (url === "/api/pipeline/client-acceptance/recipients") {
      return recipientsFail
        ? Promise.reject({ response: { status: 500, data: { detail: "Serwer nie odpowiada." } } })
        : Promise.resolve({ data: { recipients } });
    }
    if (url === "/api/pipeline/move-requirements") return Promise.resolve({ data: requirements(items) });
    return Promise.resolve({ data: null });
  });
}

function renderDialog(props: Partial<React.ComponentProps<typeof ClientAcceptedDialog>> = {}) {
  const onConfirm = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ClientAcceptedDialog
        open
        onOpenChange={vi.fn()}
        jobId={22}
        candidateId={11}
        candidateName="Karol Wzorcowy"
        context="Programista Frontend"
        acceptanceStageDefId={307}
        onConfirm={onConfirm}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onConfirm };
}

async function dialog() {
  return screen.findByRole("dialog", { name: /Klient zaakceptował: Karol Wzorcowy/ });
}

describe("ClientAcceptedDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.verdicts.mockResolvedValue({ can_record: true, items: [] });
  });

  it("pole „Co powiedział klient” startuje od zapisanej notatki werdyktu — zapis jej nie kasuje", async () => {
    serve();
    mocks.verdicts.mockResolvedValue({
      can_record: true,
      items: [{ candidate_id: 11, decision: "on_hold", note: "Runda 1: mocny w Kafce." }],
    });
    const { onConfirm } = renderDialog();
    const box = await dialog();
    await waitFor(() =>
      expect(within(box).getByLabelText(/Co powiedział klient/)).toHaveValue("Runda 1: mocny w Kafce."),
    );
    const save = within(box).getByRole("button", { name: "Zapisz akceptację" });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);
    expect(onConfirm.mock.calls[0][0].clientNote).toBe("Runda 1: mocny w Kafce.");
  });

  it("notatka wpisana w werdykcie przed otwarciem okna wygrywa z zapisaną", async () => {
    serve();
    mocks.verdicts.mockResolvedValue({
      can_record: true,
      items: [{ candidate_id: 11, decision: "on_hold", note: "Stara notatka." }],
    });
    renderDialog({ initialNote: "Klient chce startu od listopada." });
    const box = await dialog();
    await waitFor(() => expect(mocks.verdicts).toHaveBeenCalled());
    expect(within(box).getByLabelText(/Co powiedział klient/)).toHaveValue("Klient chce startu od listopada.");
  });

  it("pokazuje, kto dostanie powiadomienie, i oddaje datę, start i słowa klienta", async () => {
    serve();
    const { onConfirm } = renderDialog();
    const box = await dialog();
    expect(await within(box).findByText("Marta Nowak")).toBeInTheDocument();
    expect(within(box).getByText(/Head of Recruitment/)).toBeInTheDocument();
    expect(within(box).getByLabelText("Kiedy klient dał akceptację")).toHaveValue(warsawToday());

    fireEvent.change(within(box).getByLabelText(/Planowany start/), { target: { value: "2099-11-01" } });
    fireEvent.change(within(box).getByLabelText(/Co powiedział klient/), {
      target: { value: "  Start od listopada.  " },
    });
    const save = within(box).getByRole("button", { name: "Zapisz akceptację" });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    expect(onConfirm).toHaveBeenCalledWith(
      {
        acceptedOn: warsawToday(),
        plannedStartOn: "2099-11-01",
        clientNote: "Start od listopada.",
        requestPreContract: false,
      },
      RECIPIENTS,
    );
  });

  it("„Potrzebna umowa przedwstępna” przekazuje prośbę razem z akceptacją (0506)", async () => {
    serve();
    const { onConfirm } = renderDialog();
    const box = await dialog();
    fireEvent.click(within(box).getByRole("checkbox", { name: /Potrzebna umowa przedwstępna/ }));
    const save = within(box).getByRole("button", { name: "Zapisz akceptację" });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);
    expect(onConfirm.mock.calls[0][0].requestPreContract).toBe(true);
  });

  it("brak debriefu po rozmowie blokuje zapis i prowadzi do debriefu", async () => {
    serve({
      items: [
        {
          key: "debrief",
          label: "Debrief po rozmowie u klienta",
          detail: "zapisz pytania klienta po rozmowie",
          status: "missing",
          blocking: true,
          action: { kind: "open_debrief", label: "Uzupełnij debrief", event_id: 44 },
        },
      ],
    });
    renderDialog();
    const box = await dialog();
    const row = await within(box).findByTestId("client-accepted-debrief");
    expect(row).toHaveTextContent("bez niego akceptacja się nie zapisze");
    expect(within(row).getByRole("button", { name: "Uzupełnij debrief" })).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "Zapisz akceptację" })).toBeDisabled();
  });

  it("akceptacja z przyszłości nie przejdzie", async () => {
    serve();
    const { onConfirm } = renderDialog();
    const box = await dialog();
    fireEvent.change(within(box).getByLabelText("Kiedy klient dał akceptację"), {
      target: { value: "2999-01-01" },
    });
    expect(within(box).getByText("Data akceptacji nie może być z przyszłości.")).toBeInTheDocument();
    const save = within(box).getByRole("button", { name: "Zapisz akceptację" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("awaria listy odbiorców nie wygląda jak „nikt” i nie blokuje zapisu", async () => {
    serve({ recipientsFail: true });
    renderDialog();
    const box = await dialog();
    expect(await within(box).findByText(/Nie udało się pobrać listy/)).toBeInTheDocument();
    expect(within(box).queryByText(/Nikt poza Tobą/)).toBeNull();
    await waitFor(() =>
      expect(within(box).getByRole("button", { name: "Zapisz akceptację" })).not.toBeDisabled(),
    );
  });

  it("szablon bez etapu „Akceptacja” mówi, co zrobić, i nie zapisuje", async () => {
    serve();
    renderDialog({ acceptanceStageDefId: null });
    const box = await dialog();
    expect(within(box).getByRole("alert")).toHaveTextContent(/nie ma etapu „Akceptacja”/);
    expect(within(box).getByRole("button", { name: "Zapisz akceptację" })).toBeDisabled();
  });
});
