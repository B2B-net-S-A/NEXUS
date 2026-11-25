import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { RedlineReview } from "@/components/legal-assistant/redline/RedlineReview";
import type { ChangeEdit, Decision, RedlineChange, RedlineParagraph } from "@/lib/legal-redline";

const PARAGRAPHS: RedlineParagraph[] = [
  { index: 0, text: "§ 1 Przedmiot", style: "Nagwek1", in_table: false, heading: true },
  { index: 1, text: "Termin wynosi 30 dni.", style: null, in_table: false, heading: false },
];

const base = { find: "", start: null, end: null, before: false, sources: [], blocked: false };

const CHANGES: RedlineChange[] = [
  { ...base, id: "a", kind: "replace", paragraph: 1, find: "30", start: 14, end: 16, new_text: "14", reason: "Krócej." },
  {
    ...base,
    id: "b",
    kind: "replace",
    paragraph: 1,
    find: "dni",
    start: 17,
    end: 20,
    new_text: "dni roboczych",
    reason: "Doprecyzowanie.",
    blocked: true,
    sources: [{ ref: "kc", label: "art. 111 KC", quote: "nie ma", kind: "law", state: "mismatch" }],
  },
];

function Harness() {
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [edits, setEdits] = useState<Record<string, ChangeEdit>>({});
  return (
    <RedlineReview
      paragraphs={PARAGRAPHS}
      changes={CHANGES}
      decisions={decisions}
      edits={edits}
      notes={["§ 2 bez zmian."]}
      dropped={[]}
      onDecide={(id, d) => setDecisions((p) => ({ ...p, [id]: d }))}
      onEdit={(id, e) => setEdits((p) => ({ ...p, [id]: e }))}
    />
  );
}

describe("RedlineReview", () => {
  it("pokazuje wstawki, skreślenia i karty zmian z numerami", () => {
    render(<Harness />);
    const text = screen.getByRole("article", { name: "Tekst dokumentu ze zmianami" });
    expect(within(text).getByText("30").tagName).toBe("DEL");
    expect(within(text).getByText("14").tagName).toBe("INS");
    expect(screen.getByText("§ 2 bez zmian.")).toBeInTheDocument();
    expect(screen.getByText(/bez pokrycia/)).toBeInTheDocument();
  });

  it("zablokowany cytat: „Przyjmij” nieaktywne do „Zmień”", () => {
    render(<Harness />);
    const list = screen.getByRole("complementary", { name: "Lista zmian" });
    const accept = within(list).getAllByRole("button", { name: /Przyjmij/ });
    expect(accept[0]).toBeEnabled();
    expect(accept[1]).toBeDisabled();

    fireEvent.click(within(list).getAllByRole("button", { name: /Zmień/ })[1]);
    fireEvent.change(screen.getByLabelText(/Powód zmiany/), { target: { value: "Decyzja zespołu." } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz zmianę" }));
    expect(within(list).getAllByRole("button", { name: /Przyjmij/ })[1]).toBeEnabled();
    expect(screen.getByText("Decyzja zespołu.")).toBeInTheDocument();
  });

  it("odrzucenie przywraca oryginał w tekście, „Cofnij” wraca do decyzji", () => {
    render(<Harness />);
    const list = screen.getByRole("complementary", { name: "Lista zmian" });
    fireEvent.click(within(list).getAllByRole("button", { name: /Odrzuć/ })[0]);
    const text = screen.getByRole("article", { name: "Tekst dokumentu ze zmianami" });
    expect(within(text).queryByText("14")).toBeNull();
    expect(within(list).getByText("Odrzucona")).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: /Cofnij/ }));
    expect(within(text).getByText("14").tagName).toBe("INS");
  });
});
