import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { EndingConsultant } from "@/lib/api/endingConsultants";
import { EndingAtClientsView, formatEndDay } from "../EndingAtClientsView";

// „Kończą u klientów” (25.10.2026): kogo przepiąć, zanim zostanie bez projektu.

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const ROWS: EndingConsultant[] = [
  {
    contract_id: 1,
    candidate_id: 11,
    candidate_name: "Jan Testowy",
    client_id: 5,
    client_name: "Bank Przykładowy",
    job_title: "DevOps",
    end_date: "2026-10-31",
    prolongation_status: "unknown",
  },
  {
    contract_id: 2,
    candidate_id: 12,
    candidate_name: null,
    client_id: 5,
    client_name: "Bank Przykładowy",
    job_title: null,
    end_date: "2026-11-30",
    prolongation_status: "negotiate",
  },
];

describe("EndingAtClientsView", () => {
  it("says who ends, where, when and what about the renewal", () => {
    render(<EndingAtClientsView rows={ROWS} onAdd={vi.fn()} />);
    expect(screen.getByText(/2 osobom u Twoich klientów/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Jan Testowy" })).toHaveAttribute(
      "href",
      "/candidates/11",
    );
    expect(
      screen.getByText("Bank Przykładowy · koniec umowy 31.10 · przedłużenie: nie wiadomo"),
    ).toBeInTheDocument();
    // Bez nazwiska w odpowiedzi — nie pusty wiersz.
    expect(screen.getByRole("link", { name: "Kandydat 12" })).toBeInTheDocument();
    expect(screen.getByText(/przedłużenie w negocjacjach/)).toBeInTheDocument();
  });

  it("hands the person to „add to recruitment”", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    render(<EndingAtClientsView rows={ROWS} onAdd={onAdd} />);
    await user.click(screen.getByRole("button", { name: "Dodaj do rekrutacji: Jan Testowy" }));
    expect(onAdd).toHaveBeenCalledWith({ candidate_id: 11, full_name: "Jan Testowy" });
  });

  it("says nobody is ending instead of showing a blank tab", () => {
    render(<EndingAtClientsView rows={[]} onAdd={vi.fn()} />);
    expect(screen.getByText(/nikomu nie kończy się umowa w ciągu 60 dni/)).toBeInTheDocument();
  });

  it("formats the day without time-zone shifts", () => {
    expect(formatEndDay("2026-11-01")).toBe("01.11");
  });
});
