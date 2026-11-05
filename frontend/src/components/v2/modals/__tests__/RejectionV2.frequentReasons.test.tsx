/**
 * Sześć powodów zamiast ręcznego opisu pod „Inne” (0646, 04.11.2026). Lista
 * zależy od „Kto kończy?”, wybór nie wymaga opisu, a powód dla systemu trafia
 * do nowego powodu zamiast do „Inne”.
 */
import type * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  default: { post: vi.fn() },
}));

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";
import { AUTOFILL_TEMPLATE_REASON } from "@/lib/autofill-feedback";
import { groupRejectedReasons, reasonFitsEndedBy } from "@/lib/rejection-reasons";

const LABELS = {
  not_looking_for_work: "Nie szuka pracy lub niezainteresowany",
  client_conflict: "Pracuje u klienta lub nie chce do klienta",
  contract_form: "Forma umowy (UoP, B2B, etat)",
  no_contact: "Brak kontaktu",
  client_no_reason: "Klient nie podał powodu",
  client_chose_other: "Klient wybrał kogoś innego",
} as const;

const reasons = [
  { id: "1", name: "Brak doświadczenia", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  ...Object.entries(LABELS).map(([name, label], index) => ({
    id: String(index + 10),
    name,
    label,
    applies_to: ["rejected" as const],
  })),
  { id: "99", name: "Inne (rejected)", label: "Inne", applies_to: ["rejected" as const] },
];

function renderWindow(props: Partial<React.ComponentProps<typeof RejectionV2>> = {}) {
  const onConfirm = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <RejectionV2
      open
      onOpenChange={() => {}}
      terminalType="rejected"
      reasons={reasons}
      previousStageCategory="internal"
      previousStage="screening"
      onConfirm={onConfirm}
      canEndAsDeliveryLead
      {...props}
    />,
    {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    },
  );
  return onConfirm;
}

const confirm = () => screen.getByRole("button", { name: "Potwierdź" });
const visible = (label: string) => screen.queryByText(label) !== null;

describe("RejectionV2 — lista powodów zależy od „Kto kończy?”", () => {
  it.each(["Odrzucamy my", "Odrzuca Delivery Lead"])("%s: bez powodów klienta", (who) => {
    renderWindow();
    fireEvent.click(screen.getByText(who));
    expect(visible(LABELS.not_looking_for_work)).toBe(true);
    expect(visible(LABELS.no_contact)).toBe(true);
    expect(visible(LABELS.client_conflict)).toBe(true);
    expect(visible(LABELS.contract_form)).toBe(true);
    expect(visible(LABELS.client_no_reason)).toBe(false);
    expect(visible(LABELS.client_chose_other)).toBe(false);
  });

  it("Odrzuca klient: powody klienta, bez spraw osoby", () => {
    renderWindow({ initialEndedBy: "client" });
    expect(visible(LABELS.client_no_reason)).toBe(true);
    expect(visible(LABELS.client_chose_other)).toBe(true);
    expect(visible(LABELS.client_conflict)).toBe(true);
    expect(visible(LABELS.contract_form)).toBe(true);
    expect(visible(LABELS.not_looking_for_work)).toBe(false);
    expect(visible(LABELS.no_contact)).toBe(false);
    expect(visible("Brak doświadczenia")).toBe(true);
    expect(visible("Inne")).toBe(true);
  });

  it("powód, którego nie ma na nowej liście, nie zostaje wybrany po cichu", () => {
    const onConfirm = renderWindow();
    fireEvent.click(screen.getByText(LABELS.no_contact));
    expect(confirm()).toBeEnabled();
    fireEvent.click(screen.getByText("Odrzuca klient"));
    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Odrzucamy my"));
    expect(confirm()).toBeDisabled();
  });

  it("powód obecny na obu listach zostaje wybrany", () => {
    const onConfirm = renderWindow();
    fireEvent.click(screen.getByText(LABELS.contract_form));
    fireEvent.click(screen.getByText("Odrzuca klient"));
    fireEvent.click(confirm());
    expect(onConfirm.mock.calls[0][0]).toBe("12");
    expect(onConfirm.mock.calls[0][5]).toBe("client");
  });

  it("wybór zastępuje pisanie: bez opisu, a „Inne” nadal go wymaga", () => {
    const onConfirm = renderWindow({ initialEndedBy: "client" });
    fireEvent.click(screen.getByText("Inne"));
    expect(confirm()).toBeDisabled();
    fireEvent.click(screen.getByText(LABELS.client_no_reason));
    expect(confirm()).toBeEnabled();
    fireEvent.click(confirm());
    expect(onConfirm.mock.calls[0][0]).toBe("14");
    expect(onConfirm.mock.calls[0][1]).toBe("");
  });

  it("„Inne” przenosi kursor do opisu, a powód z listy nie", () => {
    renderWindow();
    fireEvent.click(screen.getByText(LABELS.no_contact));
    expect(document.activeElement?.tagName).not.toBe("TEXTAREA");
    fireEvent.click(screen.getByText("Inne"));
    expect(document.activeElement?.tagName).toBe("TEXTAREA");
  });

  it("powód dopisany przez admina jest widoczny zawsze", () => {
    const custom = { name: "Klauzula konkurencji" };
    for (const who of ["candidate", "recruiter", "delivery_lead", "client"] as const) {
      expect(reasonFitsEndedBy(custom, who)).toBe(true);
    }
    expect(reasonFitsEndedBy({ name: " client_no_reason " }, "recruiter")).toBe(false);
    expect(reasonFitsEndedBy({ name: "no_contact" }, "client")).toBe(false);
  });
});

describe("groupRejectedReasons", () => {
  it("„Inne” i powód admina nie giną poza grupami", () => {
    const groups = groupRejectedReasons([
      { name: "Brak doświadczenia" },
      { name: "Klauzula konkurencji" },
      { name: "Inne (rejected)" },
    ]);
    expect(groups.map((g) => g.title)).toEqual(["Wymagania", "Pozostałe"]);
    expect(groups[1].reasons.map((r) => r.name)).toEqual(["Klauzula konkurencji", "Inne (rejected)"]);
  });

  it("szablon bez znanych powodów: płaska lista bez nagłówka", () => {
    expect(groupRejectedReasons([{ name: "Własny" }])).toEqual([
      { title: null, reasons: [{ name: "Własny" }] },
    ]);
  });

  it("każdy powód jest na liście dokładnie raz", () => {
    const flat = groupRejectedReasons(reasons).flatMap((g) => g.reasons);
    expect(flat).toHaveLength(reasons.length);
    expect(new Set(flat).size).toBe(reasons.length);
  });
});

describe("RejectionV2 — osoba od systemu trafia do nowych powodów", () => {
  function chooseAndConfirm(label: string) {
    const onConfirm = renderWindow({
      autofill: { rateKnown: false, several: false },
      previousStage: "new",
    });
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    fireEvent.click(screen.getByText(label));
    fireEvent.click(confirm());
    return onConfirm.mock.calls[0];
  }

  it("mapa nie ma już `null` przy sprawach osoby", () => {
    expect(AUTOFILL_TEMPLATE_REASON.not_looking).toBe("not_looking_for_work");
    expect(AUTOFILL_TEMPLATE_REASON.no_answer).toBe("no_contact");
    expect(AUTOFILL_TEMPLATE_REASON.wrong_phone).toBe("no_contact");
    expect(AUTOFILL_TEMPLATE_REASON.client_employed).toBe("client_conflict");
    expect(AUTOFILL_TEMPLATE_REASON.client_refused).toBe("client_conflict");
    expect(AUTOFILL_TEMPLATE_REASON.client_other_vendor).toBe("client_conflict");
  });

  it("„Nie szuka pracy” idzie do własnego powodu, bez powtórzenia w opisie", () => {
    const call = chooseAndConfirm("Nie szuka pracy");
    expect(call[0]).toBe("10");
    expect(call[1]).toBe("");
    expect(call[9].reason).toBe("not_looking");
  });

  it("„Nie odbiera” idzie do „Brak kontaktu”", () => {
    expect(chooseAndConfirm("Nie odbiera (3 próby)")[0]).toBe("13");
  });

  it("szerszy powód zostawia szczegół w opisie", () => {
    const call = chooseAndConfirm("Zgłoszony do klienta przez inną firmę");
    expect(call[0]).toBe("11");
    expect(call[1]).toBe("Zgłoszony do klienta przez inną firmę");
  });

  it("szablon bez nowych powodów: nadal „Inne” z nazwą w opisie", () => {
    const onConfirm = renderWindow({
      reasons: reasons.filter((r) => !(r.name in LABELS)),
      autofill: { rateKnown: false, several: false },
      previousStage: "new",
    });
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    fireEvent.click(screen.getByText("Nie odbiera (3 próby)"));
    fireEvent.click(confirm());
    expect(onConfirm.mock.calls[0][0]).toBe("99");
    expect(onConfirm.mock.calls[0][1]).toBe("Nie odbiera (3 próby)");
  });
});
