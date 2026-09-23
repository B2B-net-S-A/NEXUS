/**
 * Mail odrzucenia jest OPT-IN od 17.09.2026: checkbox domyślnie odznaczony,
 * a okno zawsze wysyła jawny boolean — serwer planuje wysyłkę wyłącznie
 * przy `true`.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";
import type { RejectionReasonDef } from "@/lib/api";
import { mapRejectionReasons, rejectionReasonLabel } from "@/lib/rejection-reasons";

const reasons = [
  { id: "7", label: "Za wysoka stawka", applies_to: ["rejected" as const] },
];

function renderRejection(onConfirm = vi.fn()) {
  render(
    <RejectionV2
      open
      onOpenChange={() => {}}
      terminalType="rejected"
      reasons={reasons}
      previousStageCategory="external"
      previousStage="cv_sent"
      onConfirm={onConfirm}
    />,
  );
  return onConfirm;
}

describe("RejectionV2 — mail odrzucenia opt-in", () => {
  it("checkbox maila jest domyślnie odznaczony i wysyłamy jawne false", () => {
    const onConfirm = renderRejection();
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();

    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][2]).toBe(false);
  });

  it("zaznaczony checkbox wysyła true", () => {
    const onConfirm = renderRejection();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));

    expect(onConfirm.mock.calls[0][2]).toBe(true);
  });
});

describe("RejectionV2 — kto zakończył proces (Pipeline v4)", () => {
  it("domyślnie „Odrzucamy my”, wybór klienta idzie w ostatnim argumencie", () => {
    const onConfirm = renderRejection();
    // Bez uprawnień DL opcji „Odrzuca Delivery Lead" nie ma.
    expect(screen.queryByText("Odrzuca Delivery Lead")).toBeNull();
    fireEvent.click(screen.getByText("Odrzuca klient"));
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][5]).toBe("client");
  });

  it("upuszczenie na „Odrzucony przez DL” wstępnie wybiera DL; rezygnacja to zawsze kandydat", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        onConfirm={onConfirm}
        initialEndedBy="delivery_lead"
        canEndAsDeliveryLead
      />,
    );
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][5]).toBe("delivery_lead");

    rerender(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="withdrawn"
        reasons={[{ id: "9", label: "Lepsza oferta", applies_to: ["withdrawn"] }]}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.queryByText("Kto kończy?")).toBeNull();
    fireEvent.click(screen.getByText("Lepsza oferta"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[1][5]).toBe("candidate");
  });
});

describe("RejectionV2 — powody po polsku (test na produkcji 23.09.2026)", () => {
  // Kształt odpowiedzi `GET /api/pipeline-templates/{id}`: `name` jest kluczem
  // danych (kody z migracji 0068, „Inne (…)" z 0006), `label` liczy backend.
  const SEEDED: [string, string, "rejected" | "withdrawn"][] = [
    ["counter_offer", "Kontroferta od obecnego pracodawcy", "withdrawn"],
    ["personal_reasons", "Powody osobiste", "withdrawn"],
    ["lost_interest", "Stracił zainteresowanie", "withdrawn"],
    ["accepted_other_offer", "Przyjął inną ofertę", "withdrawn"],
    ["salary_mismatch", "Rozbieżność oczekiwań finansowych", "withdrawn"],
    ["process_too_long", "Za długi proces", "withdrawn"],
    ["Inne (withdrawn)", "Inne", "withdrawn"],
    ["Inne (rejected)", "Inne", "rejected"],
  ];
  const rows: RejectionReasonDef[] = SEEDED.map(([name, label, category], i) => ({
    id: i + 1,
    template_id: 1,
    stage_def_id: null,
    name,
    label,
    order: 0,
    category,
    active: true,
    disqualifies_person: false,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: "2026-09-23T00:00:00Z",
  }));

  it("okno „Kandydat zrezygnował” pokazuje etykiety, nigdy surowe kody", () => {
    render(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="withdrawn"
        reasons={mapRejectionReasons(rows)}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText("Kandydat zrezygnował")).toBeInTheDocument();
    for (const [name, label, category] of SEEDED) {
      if (category !== "withdrawn") continue;
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.queryByText(name)).toBeNull();
    }
  });

  it("odpowiedź bez `label` (stary mock) spada na `name`", () => {
    expect(rejectionReasonLabel({ name: "Brak doświadczenia" })).toBe("Brak doświadczenia");
    expect(rejectionReasonLabel({ name: "counter_offer", label: "  " })).toBe("counter_offer");
  });
});
