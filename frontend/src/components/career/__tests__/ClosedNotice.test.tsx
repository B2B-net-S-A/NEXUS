import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClosedNotice } from "@/components/career/ClosedNotice";

const base = {
  jobTitle: "Senior Java Developer",
  recruiterFirstName: "Marta",
  jobHref: (slug: string) => `/kariera/r/${slug}`,
  homeHref: "/kariera",
  rodoHref: "/kariera/rodo",
  hostLabel: "nexus.b2bnetwork.pl/kariera/r/senior-java-developer-ab12",
};

describe("ClosedNotice", () => {
  it("bez listy i bez stałego linku prosi o kontakt z osobą od linku i odsyła na tablicę", () => {
    render(<ClosedNotice {...base} recruiterPageHref={null} otherJobs={[]} />);
    expect(
      screen.getByText("Odezwij się do Marty tam, skąd masz ten link — podpowie, co jest teraz otwarte."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ten proces jest zakończony.");
    expect(screen.getByText(/Rekrutacja zamknięta · Senior Java Developer/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Zostaw CV/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Wszystkie otwarte rekrutacje" })).toHaveAttribute("href", "/kariera");
  });

  it("ze stałym linkiem i listą pokazuje oba odesłania", () => {
    render(
      <ClosedNotice
        {...base}
        recruiterPageHref="/kariera/p/marta-n"
        otherJobs={[{ slug: "qa-x1y2", title: "QA Engineer", city: null, remote_policy: "remote" }]}
      />,
    );
    expect(screen.getByText(/zobacz, czy coś pasuje, albo zostaw CV do bazy\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /QA Engineer/ })).toHaveAttribute("href", "/kariera/r/qa-x1y2");
    expect(screen.getByRole("link", { name: "Zostaw CV u Marty" })).toHaveAttribute("href", "/kariera/p/marta-n");
  });

  it("bez imienia nie wstawia pustego miejsca", () => {
    render(<ClosedNotice {...base} recruiterFirstName=" " recruiterPageHref={null} otherJobs={[]} />);
    expect(screen.getByText(/Odezwij się do osoby, od której masz ten link/)).toBeInTheDocument();
  });

  it("nie wraca do okna terminala", () => {
    const { container } = render(<ClosedNotice {...base} recruiterPageHref={null} otherJobs={[]} />);
    expect(container.textContent).not.toMatch(/\$ |\[err\]|zsh|\.\/aplikuj/);
  });
});
