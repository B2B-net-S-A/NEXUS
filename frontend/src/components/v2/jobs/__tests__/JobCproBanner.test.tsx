import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobCproBanner } from "@/components/v2/jobs/JobCproBanner";
import type { CproJobEvents } from "@/lib/cpro-events-api";

const closed: CproJobEvents = {
  closed: {
    at: "2026-10-19T10:15:07Z",
    request: "42280",
    cpro_reason: "consultant contracted",
    nexus_reason: "Klient wybrał kandydata innej firmy",
    notified: 7,
  },
  rejected: [],
  rejected_more: 0,
};

const rejected: CproJobEvents = {
  closed: null,
  rejected: [{ at: "2026-11-02T10:10:00Z", person: "Jan Testowy", reason: "Profile not matching", candidate_id: 5 }],
  rejected_more: 2,
};

describe("JobCproBanner", () => {
  it("nic nie pokazuje bez zdarzeń", () => {
    const { container } = render(
      <JobCproBanner jobId={1} events={{ closed: null, rejected: [], rejected_more: 0 }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("mówi, kto i dlaczego zamknął, i podaje przyciski tylko z prawem", () => {
    const onReopen = vi.fn();
    render(<JobCproBanner jobId={1} events={closed} onReopen={onReopen} />);
    expect(screen.getByRole("status")).toHaveTextContent("Zamknięte z CPro 19.10 o 12:15");
    expect(screen.getByRole("status")).toHaveTextContent("consultant contracted");
    expect(screen.getByRole("status")).toHaveTextContent("7 rekruterom");
    expect(screen.queryByRole("button", { name: "Zmień powód" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Otwórz ponownie" }));
    expect(onReopen).toHaveBeenCalledOnce();
  });

  it("liczy też odrzucenia spoza listy i linkuje kartę", () => {
    render(<JobCproBanner jobId={9} events={rejected} />);
    expect(screen.getByRole("status")).toHaveTextContent("klient odrzucił 3 osoby");
    expect(screen.getByRole("status")).toHaveTextContent("I jeszcze 2");
    expect(screen.getByRole("link", { name: "Napisz do kandydata" })).toHaveAttribute(
      "href",
      "/jobs/9?candidate=5",
    );
  });
});
