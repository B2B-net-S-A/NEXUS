import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ClientFormField, ClientFormView } from "@/lib/api/clientForms";

import { ClientFormDialog } from "../ClientFormDialog";

const field = (over: Partial<ClientFormField>): ClientFormField => ({
  id: "t2.r5.c3",
  kind: "cell",
  label: "Stopień zaawansowania w skali 1-10",
  section: null,
  row_label: "Selenium",
  table: "Kompetencje",
  value: null,
  source: null,
  quote: null,
  ...over,
});

const view = (fields: ClientFormField[]): ClientFormView => ({
  client_document: "client_form",
  status: "filled",
  message: null,
  template: { file_id: 1, filename: "Formularz.docx", summary: "" },
  template_changed: false,
  fields,
  extra_rows: [],
  missing: [],
  filled_at: null,
  updated_at: null,
  model: null,
});

describe("ClientFormDialog — szkic rekrutera", () => {
  it("zapis siatki lat (nowa odpowiedź serwera) nie kasuje niezapisanych wpisów w polach", () => {
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      candidateName: "Anna Fikcyjna",
      onSave: vi.fn(),
      onDownload: vi.fn(),
    };
    const first = view([
      field({}),
      field({
        id: "t2.r2.c3",
        label: "Liczba lat doświadczenia",
        row_label: "SQL",
      }),
    ]);
    const { rerender } = render(<ClientFormDialog {...props} view={first} />);
    fireEvent.change(screen.getByLabelText(/Stopień zaawansowania/), {
      target: { value: "7" },
    });
    // Serwer przeliczył lata SQL po „Zapisz lata” — pole oceny dalej niezapisane.
    const second = view([
      field({}),
      field({
        id: "t2.r2.c3",
        label: "Liczba lat doświadczenia",
        row_label: "SQL",
        value: "2 lata",
        source: "cv",
      }),
    ]);
    rerender(<ClientFormDialog {...props} view={second} />);
    // Wypełnione pola są w zwiniętej sekcji.
    fireEvent.click(screen.getByRole("button", { name: /Pokaż wypełnione/ }));
    expect(screen.getByLabelText(/Stopień zaawansowania/)).toHaveValue("7");
    expect(screen.getByLabelText(/Liczba lat doświadczenia/)).toHaveValue(
      "2 lata",
    );
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(props.onSave).toHaveBeenCalledWith({ "t2.r5.c3": "7" });
  });
});
