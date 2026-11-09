/** Spotkania przy zamknięciu karty: domyślnie do odwołania, awaria nie udaje braku. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RejectionMeetingsField, choiceFrom } from "@/components/v2/modals/RejectionMeetingsField";
import { closePairMeetings, meetingWhen, type PairMeeting } from "@/lib/api/pairMeetings";

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: http }));

const prep: PairMeeting = {
  event_id: 1,
  kind: "prep",
  title: "Prep 1",
  start: "2031-06-10T13:00:00Z",
  host: "Anna",
  cancellable: true,
};
const invite: PairMeeting = { ...prep, event_id: 2, kind: "outlook", title: "Z Outlooka", cancellable: false };

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  http.get.mockReset();
  http.post.mockReset();
});

describe("choiceFrom", () => {
  it("dzieli zaznaczone na odwołania i prośby", () => {
    expect(choiceFrom([prep, invite], [])).toEqual({ cancel: [1], ask: [2] });
  });
  it("odznaczone zostaje w kalendarzu", () => {
    expect(choiceFrom([prep, invite], [1])).toEqual({ cancel: [], ask: [2] });
  });
});

describe("RejectionMeetingsField", () => {
  it("startuje z wszystkim zaznaczonym, odznaczenie zmienia wybór", async () => {
    http.get.mockResolvedValue({ data: [prep, invite] });
    const onChange = vi.fn();
    wrap(<RejectionMeetingsField jobId={5} candidateId={6} onChange={onChange} />);
    await screen.findByTestId("rejection-meetings");
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ cancel: [1], ask: [2] }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Prep 1/ }));
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ cancel: [], ask: [2] }));
  });

  it("bez spotkań nic nie pokazuje", async () => {
    http.get.mockResolvedValue({ data: [] });
    const onChange = vi.fn();
    const { container } = wrap(<RejectionMeetingsField jobId={5} candidateId={6} onChange={onChange} />);
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ cancel: [], ask: [] }));
    expect(container.textContent).toBe("");
  });

  it("awaria odczytu mówi, że trzeba sprawdzić Kalendarz", async () => {
    http.get.mockRejectedValue(new Error("x"));
    wrap(<RejectionMeetingsField jobId={5} candidateId={6} onChange={vi.fn()} />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Kalendarz/);
  });
});

describe("closePairMeetings", () => {
  const toast = () => ({ showSuccess: vi.fn(), showError: vi.fn() });

  it("bez wyboru nie woła serwera", async () => {
    await closePairMeetings(5, 6, { cancel: [], ask: [] }, toast());
    expect(http.post).not.toHaveBeenCalled();
  });

  it("zgłasza spotkanie, którego Outlook nie odwołał", async () => {
    http.post.mockResolvedValue({
      data: { cancelled: [2], asked: [], failed: [{ event_id: 1, title: "Prep 1", detail: "x" }] },
    });
    const t = toast();
    await closePairMeetings(5, 6, { cancel: [1, 2], ask: [] }, t);
    expect(t.showSuccess).toHaveBeenCalledWith("Odwołano 1 spotkanie.");
    expect(t.showError.mock.calls[0][0]).toMatch(/Prep 1/);
  });

  it("awaria żądania nie udaje sukcesu", async () => {
    http.post.mockRejectedValue(new Error("x"));
    const t = toast();
    await closePairMeetings(5, 6, { cancel: [1], ask: [] }, t);
    expect(t.showSuccess).not.toHaveBeenCalled();
    expect(t.showError).toHaveBeenCalledTimes(1);
  });
});

it("meetingWhen podaje godzinę firmy", () => {
  expect(meetingWhen("2031-06-10T13:00:00Z")).toBe("wt 10.06, 15:00");
});
