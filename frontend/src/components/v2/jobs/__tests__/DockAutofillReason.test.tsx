import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DockAutofillReason } from "@/components/v2/jobs/DockAutofillReason";

const meta = {
  score: 81,
  matched_must: ["Java"],
  missing_must: ["AWS"],
  rate_known: false,
  availability_known: false,
  decided: false,
  awaiting_decision: true,
  waiting_days: 2,
  decision_due: true,
};

describe("DockAutofillReason", () => {
  it("pokazuje wynik, wymagania, czego system nie wiedział i termin", () => {
    render(<DockAutofillReason item={{ entry_source: "system", entry_autofill: meta }} />);
    const block = screen.getByRole("region", { name: "Dlaczego system dodał tę osobę" });
    expect(block).toHaveTextContent("Od systemu · 81%");
    expect(block).toHaveTextContent("2 dni bez decyzji");
    expect(block).toHaveTextContent("✓ Java");
    expect(block).toHaveTextContent("✕ AWS");
    expect(block).toHaveTextContent("System nie znał stawki ani dostępności");
    expect(block).toHaveTextContent("Zdecyduj");
  });

  it("„Znamy tę osobę” rozpisuje punkty, a bez nich bloku nie ma", () => {
    const { rerender } = render(
      <DockAutofillReason
        item={{
          entry_source: "system",
          entry_autofill: {
            ...meta,
            known: { points: 14, client_points: 6, note_points: 8, verified_at_client: 7, last_note_days: 2 },
          },
        }}
      />,
    );
    const block = screen.getByTestId("dock-autofill-known");
    expect(block).toHaveTextContent("Wyżej w kolejce o 14 pkt");
    expect(block).toHaveTextContent("+6 zweryfikowana u tego klienta (7×)");
    expect(block).toHaveTextContent("+8 notatka 2 dni temu");
    rerender(<DockAutofillReason item={{ entry_source: "system", entry_autofill: meta }} />);
    expect(screen.queryByTestId("dock-autofill-known")).toBeNull();
  });

  it("„Na co uważać” wymienia ostrzeżenia, a bez nich sekcji nie ma", () => {
    const { rerender } = render(
      <DockAutofillReason
        item={{
          entry_source: "system",
          entry_autofill: {
            ...meta,
            cautions: [
              {
                key: "office_days",
                label: "Biuro: 1 z 3 dni",
                title: "Według profilu przyjmie 1 dzień w biurze w tygodniu, klient chce 3 dni.",
              },
            ],
          },
        }}
      />,
    );
    const cautions = screen.getByTestId("dock-autofill-cautions");
    expect(cautions).toHaveTextContent("Na co uważać");
    expect(cautions).toHaveTextContent("przyjmie 1 dzień w biurze w tygodniu, klient chce 3 dni");
    rerender(<DockAutofillReason item={{ entry_source: "system", entry_autofill: meta }} />);
    expect(screen.queryByTestId("dock-autofill-cautions")).toBeNull();
  });

  it("poza „Nowymi” nie prosi o decyzję, a „Od systemu” i powód zostają", () => {
    const { container } = render(
      <DockAutofillReason
        item={{
          entry_source: "system",
          entry_autofill: { ...meta, awaiting_decision: false, decision_due: false, waiting_days: null },
        }}
      />,
    );
    expect(container).toHaveTextContent("Od systemu · 81%");
    expect(container).toHaveTextContent("✓ Java");
    expect(container).toHaveTextContent("System nie znał stawki");
    expect(container).not.toHaveTextContent("bez decyzji");
    expect(container).not.toHaveTextContent("Zdecyduj");
  });

  it("po decyzji nie prosi o nią, a osoby od ludzi nie dotyczy", () => {
    const { rerender, container } = render(
      <DockAutofillReason
        item={{
          entry_source: "system",
          entry_autofill: { ...meta, decided: true, awaiting_decision: false, decision_due: false, waiting_days: null, rate_known: true, availability_known: true },
        }}
      />,
    );
    expect(container).toHaveTextContent("System znał stawkę i dostępność");
    expect(container).not.toHaveTextContent("Zdecyduj");
    rerender(<DockAutofillReason item={{ entry_source: "added_manual", entry_autofill: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
