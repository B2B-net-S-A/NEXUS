import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ default: {}, api: {} }));

import { RecruiterChips } from "@/components/v2/jobs/RecruiterChips";
import {
  assignedByCaption,
  canRemoveRecruiter,
  type JobRecruiter,
} from "@/lib/job-team";

const owner: JobRecruiter = {
  user_id: 1,
  name: "Marta Kowalska",
  via: "owner",
  proposed: false,
  assigned_by_name: null,
};
const assigned: JobRecruiter = {
  user_id: 2,
  name: "Jan Nowak",
  via: "assignment",
  proposed: false,
  assigned_by_name: "Anna Lis",
};
const collaborator: JobRecruiter = {
  user_id: 3,
  name: "Ewa Zielińska",
  via: "collaborator",
  proposed: false,
  assigned_by_name: null,
};
const proposal: JobRecruiter = {
  user_id: 4,
  name: "Piotr Wiśniewski",
  via: "assignment",
  proposed: true,
  assigned_by_name: null,
};

function chipOf(name: string): HTMLElement {
  const item = screen.getByText(name).closest("li");
  if (!item) throw new Error(`brak pozycji listy dla: ${name}`);
  return item;
}

describe("RecruiterChips — pełna lista", () => {
  it("pokazuje inicjały oraz imię i nazwisko każdej osoby — bez dopisku roli", () => {
    render(<RecruiterChips people={[owner, assigned]} label="Rekruterzy" />);

    const list = screen.getByRole("list", { name: "Rekruterzy" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(chipOf("Marta Kowalska")).getByText("MK")).toHaveAttribute("aria-hidden", "true");
    // Podział rekruter / sourcer zniknął (02.10.2026) — chip nie niesie roli.
    expect(within(chipOf("Marta Kowalska")).queryByText("rekruter")).not.toBeInTheDocument();
    expect(within(chipOf("Jan Nowak")).queryByText(/sourcer|rekruter/)).not.toBeInTheDocument();
  });

  it("propozycja automatu ma przerywaną ramkę w kolorze akcentu i dopisek „propozycja”", () => {
    render(<RecruiterChips people={[owner, proposal]} />);

    const proposed = within(chipOf("Piotr Wiśniewski"));
    expect(proposed.getByText("propozycja")).toBeInTheDocument();
    const frame = screen.getByText("Piotr Wiśniewski").parentElement as HTMLElement;
    expect(frame).toHaveAttribute("data-proposed", "true");
    expect(frame.className).toContain("border-dashed");
    expect(frame.className).toContain("border-primary/60");

    const working = screen.getByText("Marta Kowalska").parentElement as HTMLElement;
    expect(working).not.toHaveAttribute("data-proposed");
    expect(working.className).not.toContain("border-dashed");
    expect(within(chipOf("Marta Kowalska")).queryByText(/propozycja/)).not.toBeInTheDocument();
  });

  it("w wąskim miejscu najpierw kurczy się etykieta, nazwisko na końcu", () => {
    render(<RecruiterChips people={[proposal]} />);

    const tags = screen.getByText("propozycja");
    expect(tags.className).toContain("shrink-[1000000]");
    expect(tags.className).toContain("truncate");
    const name = screen.getByText("Piotr Wiśniewski");
    expect(name.className).toContain("truncate");
    // Obcięte nazwisko da się przeczytać w podpowiedzi.
    expect(name).toHaveAttribute("title", "Piotr Wiśniewski");
  });

  it("podpis pod osobą pochodzi od wołającego — np. kto przydzielił", () => {
    render(<RecruiterChips people={[owner, assigned]} caption={assignedByCaption} />);

    expect(within(chipOf("Jan Nowak")).getByText("przydzielił(a) Anna L.")).toBeInTheDocument();
    // Nie wiadomo, kto przydzielił — bez pustej linii.
    expect(within(chipOf("Marta Kowalska")).queryByText(/przydzielił/)).not.toBeInTheDocument();
  });

  it("bez `onRemove` nie ma przycisków zdejmowania", () => {
    render(<RecruiterChips people={[owner, assigned]} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("„Zdejmij” woła `onRemove` z tą osobą", () => {
    const onRemove = vi.fn();
    render(<RecruiterChips people={[owner, assigned]} onRemove={onRemove} />);

    fireEvent.click(screen.getByRole("button", { name: "Zdejmij Jan Nowak" }));

    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith(assigned);
  });

  it("`canRemove` zawęża, przy kim przycisk się pojawia", () => {
    // Osoba, która redaguje rekrutację, ale nie przydziela ludzi: zdejmie
    // tylko współpracownika.
    const access = { canStaff: false, canDecide: false, canEdit: true };
    render(
      <RecruiterChips
        people={[owner, collaborator, proposal]}
        onRemove={vi.fn()}
        canRemove={(person) => canRemoveRecruiter(person, access)}
      />,
    );

    expect(screen.getByRole("button", { name: "Zdejmij Ewa Zielińska" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zdejmij Marta Kowalska" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zdejmij Piotr Wiśniewski" })).not.toBeInTheDocument();
  });

  it("akcje decyzji renderują się tylko przy propozycji", () => {
    const actions = vi.fn((person: JobRecruiter) => (
      <button type="button">Akceptuj {person.name}</button>
    ));
    render(<RecruiterChips people={[owner, proposal]} proposalActions={actions} />);

    expect(
      within(chipOf("Piotr Wiśniewski")).getByRole("button", { name: "Akceptuj Piotr Wiśniewski" }),
    ).toBeInTheDocument();
    expect(within(chipOf("Marta Kowalska")).queryByRole("button")).not.toBeInTheDocument();
    expect(actions).toHaveBeenCalledTimes(1);
    expect(actions).toHaveBeenCalledWith(proposal);
  });

  it("pusta lista: nic albo tekst od wołającego", () => {
    const { container, rerender } = render(<RecruiterChips people={[]} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<RecruiterChips people={[]} emptyLabel="Bez rekrutera" />);
    expect(screen.getByText("Bez rekrutera")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("mniejszy rozmiar zmniejsza awatar i tekst", () => {
    render(<RecruiterChips people={[owner]} size="sm" />);
    expect(screen.getByText("MK").className).toContain("h-5");
    expect((screen.getByText("Marta Kowalska").parentElement as HTMLElement).className).toContain("text-xs");
  });

  it("przyjmuje osoby z pulpitu, które nie niosą jeszcze `via`", () => {
    const board = [
      { user_id: 7, name: "Anna Przykładowa", proposed: true, source: "auto" as const },
    ];
    const onRemove = vi.fn();
    render(<RecruiterChips people={board} onRemove={onRemove} />);

    expect(screen.getByText("propozycja")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zdejmij Anna Przykładowa" }));
    expect(onRemove).toHaveBeenCalledWith(board[0]);
  });
});

describe("RecruiterChips — compact (komórka tabeli)", () => {
  it("pierwsza osoba skrócona, reszta jako „+N”, wszyscy w podpowiedzi", () => {
    render(<RecruiterChips people={[owner, assigned, collaborator, proposal]} compact />);

    const tooltip =
      "Rekruterzy: Marta Kowalska, Jan Nowak, Ewa Zielińska · Propozycja automatu: Piotr Wiśniewski";
    const cell = screen.getByTitle(tooltip);
    expect(within(cell).getByText("Marta K.")).toBeInTheDocument();
    expect(within(cell).getByText("+2")).toHaveAttribute("aria-hidden", "true");
    // Czytnik ekranu dostaje pełne nazwiska zamiast skrótu i „+2”.
    expect(within(cell).getByText(tooltip)).toHaveClass("sr-only");
    expect(cell).not.toHaveAttribute("data-proposed");
    // Element z `sr-only` musi mieć pozycjonowanego przodka (przewijane tabele).
    expect(cell.className).toContain("relative");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("jedna osoba: bez „+N”", () => {
    render(<RecruiterChips people={[owner]} compact />);
    expect(screen.getByText("Marta K.")).toBeInTheDocument();
    expect(screen.queryByText(/^\+\d/)).not.toBeInTheDocument();
  });

  it("nikt nie pracuje, jest propozycja: przerywana ramka i dopisek „propozycja”", () => {
    const second: JobRecruiter = { ...proposal, user_id: 5, name: "Olga Lis" };
    render(<RecruiterChips people={[proposal, second]} compact />);

    const cell = screen.getByTitle("Propozycje automatu: Piotr Wiśniewski, Olga Lis");
    expect(cell).toHaveAttribute("data-proposed", "true");
    expect(cell.className).toContain("border-dashed");
    expect(within(cell).getByText("Piotr W.")).toBeInTheDocument();
    expect(within(cell).getByText("propozycja")).toBeInTheDocument();
    expect(within(cell).getByText("+1")).toBeInTheDocument();
  });

  it("pusta lista: tekst od wołającego", () => {
    render(<RecruiterChips people={[]} compact emptyLabel="Bez rekrutera" />);
    expect(screen.getByText("Bez rekrutera")).toBeInTheDocument();
  });
});
