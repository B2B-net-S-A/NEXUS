/**
 * Pole „Zmiany w umowie” aneksu z własną nazwą (16.11.2026): gotowa klauzula
 * wpisuje treść i nazwę aneksu, nie kasuje wpisanych zmian, a skreślenie nie
 * ma pola treści.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type {
  DocumentFieldDef,
  DocumentTypeDef,
  DocumentValues,
} from "@/lib/api/b2bDocuments";
import { DocumentFieldsForm } from "@/components/v2/b2b-generator/documents/DocumentFieldsForm";

function field(key: string, label: string, extra: Partial<DocumentFieldDef> = {}): DocumentFieldDef {
  return {
    key,
    label,
    kind: "text",
    required: true,
    sensitive: false,
    help: null,
    options: [],
    show_if: null,
    group: "change",
    lookup: null,
    lookup_fills: [],
    ...extra,
  };
}

const TYPE: DocumentTypeDef = {
  key: "annex_custom",
  label: "Aneks — inna zmiana",
  family: "annex",
  languages: ["pl"],
  parent: "b2b",
  description: "",
  effect_label: "",
  signatories: "both",
  uses_refs: false,
  allows_external: true,
  legacy_languages: [],
  fields: [
    field("annex_title", "Czego dotyczy aneks"),
    field("changes", "Zmiany w umowie", { kind: "annex_changes" }),
  ],
  clauses: [
    {
      key: "non_compete_release",
      label: "Zwolnienie z zakazu konkurencji",
      title: "zwolnienie z zakazu konkurencji",
      rows: [
        {
          op: "free",
          text: "Zwolnienie z {non_compete_paragraph} na rzecz: {client_legal_name}.",
        },
      ],
    },
  ],
};

let latest: DocumentValues = {};

function Harness({ initial = {} }: { initial?: DocumentValues }) {
  const [values, setValues] = React.useState<DocumentValues>(initial);
  latest = values;
  return (
    <DocumentFieldsForm
      type={TYPE}
      values={values}
      onChange={(key, value) => setValues((prev) => ({ ...prev, [key]: value }))}
      clauseVars={{ non_compete_paragraph: "§ 10 ust. 1", client_legal_name: "Bank Fikcyjny S.A." }}
    />
  );
}

describe("AnnexChangesField", () => {
  it("klauzula wpisuje treść z paragrafem i klientem oraz nazwę aneksu", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Zwolnienie z zakazu konkurencji" }));
    expect(screen.getByLabelText("Treść zmiany 1")).toHaveValue(
      "Zwolnienie z § 10 ust. 1 na rzecz: Bank Fikcyjny S.A.",
    );
    expect(screen.getByLabelText(/Czego dotyczy aneks/)).toHaveValue(
      "zwolnienie z zakazu konkurencji",
    );
    expect(screen.getByText("punkt aneksu z Twoją treścią")).toBeInTheDocument();
  });

  it("klauzula nie nadpisuje wpisanej nazwy ani wpisanych zmian", async () => {
    const user = userEvent.setup();
    render(
      <Harness
        initial={{
          annex_title: "zmiana warunków",
          changes: [{ op: "delete", paragraph: "7", section: "", text: "" }],
        }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Zwolnienie z zakazu konkurencji" }));
    expect(screen.getByLabelText(/Czego dotyczy aneks/)).toHaveValue("zmiana warunków");
    expect(latest.changes).toHaveLength(2);
    // Skreślenie nie ma treści — tylko formułka.
    expect(screen.queryByLabelText("Treść zmiany 1")).toBeNull();
    expect(screen.getByText("§ 7 Umowy skreśla się.")).toBeInTheDocument();
  });

  it("dodaje i usuwa wiersze", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByRole("button", { name: "Usuń zmianę 1" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Dodaj zmianę/ }));
    expect(screen.getByLabelText("Treść zmiany 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Usuń zmianę 2" }));
    expect(screen.queryByLabelText("Treść zmiany 2")).toBeNull();
  });
});
