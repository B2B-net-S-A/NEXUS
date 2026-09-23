import * as React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type {
  DocumentFieldDef,
  DocumentTypeDef,
  DocumentValue,
  DocumentValues,
} from "@/lib/api/b2bDocuments";
import { DocumentFieldsForm } from "@/components/v2/b2b-generator/documents/DocumentFieldsForm";

function field(key: string, label: string, extra: Partial<DocumentFieldDef> = {}): DocumentFieldDef {
  return {
    key,
    label,
    kind: "text",
    required: false,
    sensitive: false,
    help: null,
    options: [],
    show_if: null,
    group: "document",
    ...extra,
  };
}

const TYPE: DocumentTypeDef = {
  key: "termination_agreement",
  label: "Porozumienie",
  family: "termination",
  languages: ["pl"],
  parent: "b2b",
  description: "",
  effect_label: "",
  signatories: "both",
  uses_refs: true,
  fields: [
    field("document_date", "Data dokumentu", { kind: "date", required: true, help: "Domyślnie dziś." }),
    field("gender", "Płeć Partnera", { kind: "gender", required: true, group: "partner" }),
    field("pesel", "PESEL", { required: true, sensitive: true, group: "partner" }),
    field("new_rate", "Nowa stawka", { kind: "money" }),
    field("currency", "Waluta", { kind: "select", options: [["PLN", "PLN"], ["EUR", "EUR"]] }),
    field("release_non_compete", "Zwolnienie z zakazu konkurencji", { kind: "bool" }),
    field("non_compete_client_name", "Klient, którego dotyczy zwolnienie", {
      required: true,
      show_if: ["release_non_compete", true],
    }),
  ],
};

function Harness({ initial = {} }: { initial?: DocumentValues }) {
  const [values, setValues] = React.useState<DocumentValues>(initial);
  return (
    <DocumentFieldsForm
      type={TYPE}
      values={values}
      errorKeys={new Set(["document_date"])}
      onChange={(key: string, value: DocumentValue) =>
        setValues((prev) => ({ ...prev, [key]: value }))
      }
    />
  );
}

describe("DocumentFieldsForm", () => {
  it("pokazuje pole zależne dopiero po zaznaczeniu zwolnienia", async () => {
    render(<Harness />);
    expect(screen.queryByLabelText(/Klient, którego dotyczy zwolnienie/)).toBeNull();
    await userEvent.click(screen.getByRole("checkbox", { name: /Zwolnienie z zakazu/ }));
    expect(screen.getByLabelText(/Klient, którego dotyczy zwolnienie/)).toBeInTheDocument();
  });

  it("oznacza pola wymagane i pola z błędem", () => {
    render(<Harness />);
    const date = screen.getByLabelText(/Data dokumentu/);
    expect(date).toHaveAttribute("aria-required", "true");
    expect(date).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Domyślnie dziś.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Nowa stawka/)).not.toHaveAttribute("aria-required");
  });

  it("pole wrażliwe mówi, że nie zapisujemy danych", () => {
    render(<Harness />);
    const pesel = screen.getByLabelText(/PESEL/);
    expect(pesel).toHaveAttribute("autocomplete", "off");
    const help = document.getElementById(pesel.getAttribute("aria-describedby") ?? "");
    expect(help?.textContent).toContain("Nie zapisujemy — trafi tylko do dokumentu");
  });

  it("płeć to przełącznik z aria-pressed", async () => {
    render(<Harness initial={{ gender: "m" }} />);
    const male = screen.getByRole("button", { name: "Mężczyzna" });
    const female = screen.getByRole("button", { name: "Kobieta" });
    expect(male).toHaveAttribute("aria-pressed", "true");
    expect(female).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(female);
    expect(female).toHaveAttribute("aria-pressed", "true");
    expect(male).toHaveAttribute("aria-pressed", "false");
  });

  it("kwota nie-liczba dostaje komunikat, select ma opcje z definicji", async () => {
    render(<Harness />);
    await userEvent.type(screen.getByLabelText(/Nowa stawka/), "sto");
    expect(screen.getByText(/Podaj kwotę liczbą/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "EUR" })).toBeInTheDocument();
  });
});
