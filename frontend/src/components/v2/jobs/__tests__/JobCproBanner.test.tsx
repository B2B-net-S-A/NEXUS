import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const NOW = new Date("2026-11-05T12:00:00Z");

describe("JobCproBanner", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"], now: NOW });
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("nic nie pokazuje bez zdarzeń", () => {
    const { container } = render(
      <JobCproBanner jobId={1} events={{ closed: null, rejected: [], rejected_more: 0 }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("mówi, kto i dlaczego zamknął, i podaje przyciski tylko z prawem", () => {
    const onReopen = vi.fn();
    const recent = { ...closed, closed: { ...closed.closed!, at: "2026-11-04T10:15:07Z" } };
    render(<JobCproBanner jobId={1} events={recent} onReopen={onReopen} />);
    fireEvent.click(screen.getByTestId("job-cpro-banner-show"));
    expect(screen.getByRole("status")).toHaveTextContent("Zamknięte z CPro 04.11 o 11:15");
    expect(screen.getByRole("status")).toHaveTextContent("consultant contracted");
    expect(screen.getByRole("status")).toHaveTextContent("7 rekruterom");
    expect(screen.queryByRole("button", { name: "Zmień powód" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Otwórz ponownie" }));
    expect(onReopen).toHaveBeenCalledOnce();
  });

  it("liczy też odrzucenia spoza listy i linkuje kartę", () => {
    render(<JobCproBanner jobId={9} events={rejected} />);
    fireEvent.click(screen.getByTestId("job-cpro-banner-show"));
    expect(screen.getByRole("status")).toHaveTextContent("klient odrzucił 3 osoby");
    expect(screen.getByRole("status")).toHaveTextContent("I jeszcze 2");
    expect(screen.getByRole("link", { name: "Napisz do kandydata" })).toHaveAttribute(
      "href",
      "/jobs/9?candidate=5",
    );
  });

  it("U3: zwinięty do jednej linii z liczbą osób i „Pokaż”", () => {
    render(<JobCproBanner jobId={9} events={rejected} />);
    expect(screen.getByTestId("job-cpro-banner")).toHaveTextContent("Z CPro: klient odrzucił 3 osobyPokaż");
    expect(screen.queryByRole("link", { name: "Napisz do kandydata" })).toBeNull();
    fireEvent.click(screen.getByTestId("job-cpro-banner-show"));
    expect(screen.getByRole("link", { name: "Napisz do kandydata" })).toBeInTheDocument();
  });

  it("U3: po otwarciu i po 7 dniach od zdarzenia nie wraca", () => {
    const { unmount } = render(<JobCproBanner jobId={9} events={rejected} />);
    fireEvent.click(screen.getByTestId("job-cpro-banner-show"));
    unmount();
    const { container } = render(<JobCproBanner jobId={9} events={rejected} />);
    expect(container).toBeEmptyDOMElement();

    window.localStorage.clear();
    vi.setSystemTime(new Date("2026-11-10T12:00:00Z"));
    const { container: late } = render(<JobCproBanner jobId={9} events={rejected} />);
    expect(late).toBeEmptyDOMElement();
  });

  it("U3: nowe odrzucenie po obejrzeniu pokazuje się znowu", () => {
    const { unmount } = render(<JobCproBanner jobId={9} events={rejected} />);
    fireEvent.click(screen.getByTestId("job-cpro-banner-show"));
    unmount();
    const newer: CproJobEvents = {
      ...rejected,
      rejected: [...rejected.rejected, { at: "2026-11-05T09:00:00Z", person: "Ola Testowa", reason: null, candidate_id: 6 }],
    };
    render(<JobCproBanner jobId={9} events={newer} />);
    expect(screen.getByTestId("job-cpro-banner-show")).toBeInTheDocument();
  });
});
