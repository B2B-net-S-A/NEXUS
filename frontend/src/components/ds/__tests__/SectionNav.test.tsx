import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SectionNav, type SectionNavGroup } from "@/components/ds/SectionNav";

const GROUPS: SectionNavGroup[] = [
  { key: "overview", label: "Przegląd", items: [{ key: "profil", label: "Przegląd", tourId: "demo.overview" }] },
  {
    key: "contracts",
    label: "Umowy",
    items: [
      { key: "umowy", label: "Umowy i aneksy" },
      { key: "raporty", label: "Raporty dla klienta", count: 3, countLabel: "3 raporty do przygotowania" },
    ],
  },
  { key: "empty", label: "Pusta", items: [] },
];

describe("SectionNav — grupy i podzakładki", () => {
  it("cicha liczba grupy ma dymek, a treść z `trailing` stoi w pasku grup", () => {
    render(
      <SectionNav
        label="Sekcje"
        groups={[{ ...GROUPS[0], meta: "4", metaTitle: "Otwarte rekrutacje: opublikowane, bez szkiców" }, GROUPS[1]]}
        activeItem="profil"
        onSelect={() => {}}
        trailing={<span>36 624 zł</span>}
      />,
    );
    expect(screen.getByText("4")).toHaveAttribute("title", "Otwarte rekrutacje: opublikowane, bez szkiców");
    expect(within(screen.getByRole("navigation", { name: "Sekcje" })).getByText("36 624 zł")).toBeInTheDocument();
  });

  it("pokazuje grupy bez pustych, a podzakładki tylko aktywnej grupy z ≥ 2 pozycjami", () => {
    const { rerender } = render(<SectionNav label="Sekcje" groups={GROUPS} activeItem="profil" onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: "Przegląd" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /^Umowy/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pusta" })).toBeNull();
    // Grupa z jedną pozycją nie ma drugiego paska; kotwica nowości stoi na grupie.
    expect(screen.queryByRole("button", { name: "Umowy i aneksy" })).toBeNull();
    expect(screen.getByRole("button", { name: "Przegląd" })).toHaveAttribute("data-tour", "demo.overview");

    rerender(<SectionNav label="Sekcje" groups={GROUPS} activeItem="raporty" onSelect={() => {}} />);
    // Grupa stoi w DOM przed swoimi podzakładkami („Umowy i aneksy”).
    expect(screen.getAllByRole("button", { name: /^Umowy/ })[0]).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Umowy i aneksy" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("button", { name: /^Raporty dla klienta/ })).toHaveAttribute("aria-current", "page");
  });

  it("klik w grupę wybiera jej pierwszą pozycję, klik w podzakładkę — ją", () => {
    const onSelect = vi.fn();
    render(<SectionNav label="Sekcje" groups={GROUPS} activeItem="raporty" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "Przegląd" }));
    expect(onSelect).toHaveBeenLastCalledWith("profil");
    fireEvent.click(screen.getByRole("button", { name: "Umowy i aneksy" }));
    expect(onSelect).toHaveBeenLastCalledWith("umowy");
  });

  it("licznik grupy to suma pozycji, z nazwą jedynej liczącej pozycji", () => {
    render(<SectionNav label="Sekcje" groups={GROUPS} activeItem="profil" onSelect={() => {}} />);
    // Grupa nieaktywna: licznik na grupie, nazwa dostępna z pozycji.
    expect(screen.getByLabelText("3 raporty do przygotowania")).toHaveTextContent("3");
  });

  it("pozycja z adresem jest linkiem", () => {
    render(
      <SectionNav
        label="Sekcje"
        groups={[{ key: "fin", label: "Raporty", items: [{ key: "a", label: "Wyniki", href: "/finance?view=results" }, { key: "b", label: "Archiwum", href: "/finance?view=archive" }] }]}
        activeItem="b"
      />,
    );
    expect(screen.getByRole("link", { name: "Archiwum" })).toHaveAttribute("href", "/finance?view=archive");
    expect(screen.getByRole("link", { name: "Raporty" })).toHaveAttribute("href", "/finance?view=results");
  });
});
