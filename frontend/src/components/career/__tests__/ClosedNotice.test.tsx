import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClosedNotice } from "@/components/career/ClosedNotice";

const base = {
  jobHandle: "senior-java-developer",
  recruiterFirstName: "Marta",
  jobHref: (slug: string) => `/kariera/r/${slug}`,
};

describe("ClosedNotice", () => {
  it("bez listy i bez stałego linku prosi o kontakt z osobą od linku", () => {
    render(<ClosedNotice {...base} recruiterPageHref={null} recruiterSlug={null} otherJobs={[]} />);
    expect(
      screen.getByText("Odezwij się do Marty tam, skąd masz ten link — podpowie, co jest teraz otwarte."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("ze stałym linkiem i listą pokazuje oba odesłania", () => {
    render(
      <ClosedNotice
        {...base}
        recruiterPageHref="/kariera/p/marta-n"
        recruiterSlug="marta-n"
        otherJobs={[{ slug: "qa-x1y2", title: "QA Engineer", city: null, remote_policy: "remote" }]}
      />,
    );
    expect(screen.getByText(/zobacz, czy coś pasuje, albo zostaw CV do bazy\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /qa-engineer/ })).toHaveAttribute("href", "/kariera/r/qa-x1y2");
    expect(screen.getByRole("link", { name: /cd ~\/marta-n/ })).toHaveAttribute("href", "/kariera/p/marta-n");
  });

  it("bez imienia nie wstawia pustego miejsca", () => {
    render(
      <ClosedNotice {...base} recruiterFirstName=" " recruiterPageHref={null} recruiterSlug={null} otherJobs={[]} />,
    );
    expect(screen.getByText(/Odezwij się do osoby, od której masz ten link/)).toBeInTheDocument();
  });
});
