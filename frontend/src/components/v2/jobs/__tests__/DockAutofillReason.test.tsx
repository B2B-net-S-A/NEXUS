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

  it("po decyzji nie prosi o nią, a osoby od ludzi nie dotyczy", () => {
    const { rerender, container } = render(
      <DockAutofillReason
        item={{
          entry_source: "system",
          entry_autofill: { ...meta, decided: true, decision_due: false, waiting_days: null, rate_known: true, availability_known: true },
        }}
      />,
    );
    expect(container).toHaveTextContent("System znał stawkę i dostępność");
    expect(container).not.toHaveTextContent("Zdecyduj");
    rerender(<DockAutofillReason item={{ entry_source: "added_manual", entry_autofill: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
