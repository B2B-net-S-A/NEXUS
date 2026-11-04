import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { post: (...a: unknown[]) => post(...a) },
}));

import type { LeaveRequestRow } from "@/lib/api/hr-leave";

import { CancelLeaveDialog } from "../CancelLeaveDialog";
import { cancelNeedsReason, pastCancelText } from "../leave-format";

const ROW: LeaveRequestRow = {
  id: "r1",
  user_id: 11,
  user_name: "Anna Przykładowa",
  leave_type: "vacation",
  leave_type_label: "Urlop wypoczynkowy",
  status: "approved",
  start_date: "2026-10-01",
  end_date: "2026-10-07",
  half_day: null,
  days_total: "5.0",
  paid_days: "5.0",
  unpaid_days: "0.0",
  note: null,
  substitute_user_id: null,
  substitute_name: null,
  forward_mail_consent: false,
  oof_internal_message: null,
  oof_external_message: null,
  decided_by_name: null,
  decided_at: null,
  decision_note: null,
  source: "self",
  created_at: null,
  proof_count: 0,
  can_cancel: false,
  employment_type: "b2b",
};

const TODAY = "2026-10-28";

function renderDialog(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CancelLeaveDialog request={ROW} today={TODAY} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

describe("cofnięcie minionych dni (28.10.2026)", () => {
  beforeEach(() => {
    post.mockReset();
  });

  it("powód jest wymagany od pierwszego dnia, przed nim — nie", () => {
    expect(cancelNeedsReason({ start_date: "2026-10-29" }, TODAY)).toBe(false);
    expect(cancelNeedsReason({ start_date: TODAY }, TODAY)).toBe(true);
    expect(cancelNeedsReason({ start_date: "2026-10-01" }, TODAY)).toBe(true);
  });

  it("tekst mówi słowami formy i odróżnia trwający termin i niezatwierdzony wniosek", () => {
    expect(pastCancelText(ROW, TODAY)).toEqual({
      title: "Cofnąć nieobecność 01–07.10.2026?",
      text:
        "Te dni już minęły. Po cofnięciu wrócą do raportu godzin jako dni robocze " +
        "do uzupełnienia i do statów. Osoba dostanie powiadomienie z powodem.",
    });
    expect(pastCancelText({ ...ROW, employment_type: "uop" }, TODAY).text).toContain(
      "wrócą do ewidencji czasu pracy",
    );
    expect(pastCancelText({ ...ROW, end_date: "2026-10-30" }, TODAY).text).toMatch(
      /^Ten termin już trwa\. Po cofnięciu minione dni wrócą/,
    );
    const pending = pastCancelText({ ...ROW, status: "pending" }, TODAY);
    expect(pending.title).toBe("Anulować wniosek 01–07.10.2026?");
    expect(pending.text).not.toContain("raportu godzin");
  });

  it("bez powodu nic nie wysyła, z powodem wysyła go przycięty", async () => {
    post.mockResolvedValue({ data: { ...ROW, status: "cancelled" } });
    const onClose = renderDialog();
    expect(screen.getByText("Cofnąć nieobecność 01–07.10.2026?")).toBeInTheDocument();
    expect(screen.getByLabelText(/Powód \(wymagany, widzi go osoba\)/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cofnij nieobecność" }));
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByText(/Podaj powód/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Powód/), "  Był w pracy u klienta ");
    await userEvent.click(screen.getByRole("button", { name: "Cofnij nieobecność" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/leave/approvals/r1/cancel", {
        reason: "Był w pracy u klienta",
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledWith(expect.objectContaining({ status: "cancelled" })));
  });

  it("błąd serwera pokazuje komunikat z API i zostawia okno", async () => {
    post.mockRejectedValue({
      response: { status: 422, data: { detail: "Powód musi mieć co najmniej 3 znaki." } },
    });
    const onClose = renderDialog();
    await userEvent.type(screen.getByLabelText(/Powód/), "abc");
    await userEvent.click(screen.getByRole("button", { name: "Cofnij nieobecność" }));
    expect(await screen.findByText("Powód musi mieć co najmniej 3 znaki.")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("„Zostaw” zamyka bez wysyłki", async () => {
    const onClose = renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "Zostaw" }));
    expect(onClose).toHaveBeenCalledWith(null);
    expect(post).not.toHaveBeenCalled();
  });
});
