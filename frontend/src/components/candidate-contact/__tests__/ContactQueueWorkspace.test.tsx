import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AxiosError } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContactQueueWorkspace } from "@/components/candidate-contact/ContactQueueWorkspace";
import {
  candidateContactApi,
  type CandidateContactCase,
  type CandidateContactQueueResponse,
} from "@/lib/candidate-contact";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showError: vi.fn(),
    showSuccess: vi.fn(),
  }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const queueCase: CandidateContactCase = {
  id: 41,
  status: "queued",
  due_at: "2099-07-28T16:00:00Z",
  callback_at: null,
  attempts_in_cycle: 0,
  version: 4,
  owner: { id: 2, name: "Marta Nowak" },
  candidate: {
    id: 8,
    name: "Anna",
    lastname: "Nowak",
    phone: "+48 500 100 200",
    current_role: "Senior Developer",
  },
  opportunities: [
    { job_id: 11, job_title: "Java Developer" },
    { job_id: 12, job_title: "Tech Lead" },
  ],
};

const initialData: CandidateContactQueueResponse = {
  utilization: { used: 20, capacity: 20 },
  next_cursor: null,
  items: [
    queueCase,
    {
      ...queueCase,
      id: 99,
      version: 3,
      opportunities: [{ job_id: 13, job_title: "Architect" }],
    },
  ],
};

describe("ContactQueueWorkspace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows each candidate once and displays capacity N/20", () => {
    render(
      <ContactQueueWorkspace
        initialData={initialData}
        featureEnabledOverride
      />,
      { wrapper },
    );

    expect(screen.getByText("20/20")).toBeInTheDocument();
    expect(screen.getAllByText("Anna Nowak")).toHaveLength(1);
    expect(screen.getByText("Java Developer")).toBeInTheDocument();
    expect(screen.getByText("Tech Lead")).toBeInTheDocument();
    expect(screen.getByText("Architect")).toBeInTheDocument();
  });

  it("does not save on phone click and sends exactly one POST-equivalent on submit", async () => {
    const submitAttempt = vi.fn().mockResolvedValue({
      ...queueCase,
      status: "handoff_pending",
      version: 5,
    });
    render(
      <ContactQueueWorkspace
        initialData={initialData}
        featureEnabledOverride
        submitAttempt={submitAttempt}
      />,
      { wrapper },
    );

    const phoneLink = screen.getByRole("link", { name: "+48 500 100 200" });
    phoneLink.addEventListener("click", (event) => event.preventDefault(), {
      once: true,
    });
    fireEvent.click(phoneLink);
    expect(submitAttempt).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /zaloguj wynik/i }));
    expect(screen.getByText("Rozmowa odbyta")).toBeInTheDocument();
    expect(screen.getByText("Brak odpowiedzi")).toBeInTheDocument();
    expect(screen.getByText("Prośba o oddzwonienie")).toBeInTheDocument();
    expect(screen.getByText("Błędny numer")).toBeInTheDocument();
    expect(screen.getByText("Nie kontaktować")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Brak odpowiedzi" }));
    const saveButton = screen.getByRole("button", { name: "Zapisz wynik" });
    fireEvent.click(saveButton);
    fireEvent.click(saveButton);

    await waitFor(() => expect(submitAttempt).toHaveBeenCalledTimes(1));
    expect(submitAttempt).toHaveBeenCalledWith(
      41,
      {
        expected_version: 4,
        outcome: "no_answer",
        callback_at: null,
        notes: null,
        opportunity_outcomes: [],
      },
      expect.any(String),
    );
  });

  it("refreshes the open case after 409 and retries with the current version", async () => {
    const conflict = new AxiosError("Conflict", "ERR_BAD_REQUEST");
    conflict.response = {
      status: 409,
      statusText: "Conflict",
      data: { detail: "Stara wersja procesu" },
      headers: {},
      config: { headers: {} },
    } as AxiosError["response"];
    const refreshedCase = { ...queueCase, version: 5 };
    vi.spyOn(candidateContactApi, "queue").mockResolvedValue({
      utilization: { used: 20, capacity: 20 },
      next_cursor: null,
      items: [refreshedCase],
    });
    const submitAttempt = vi
      .fn()
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ ...refreshedCase, version: 6 });

    render(
      <ContactQueueWorkspace
        initialData={initialData}
        featureEnabledOverride
        submitAttempt={submitAttempt}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: /zaloguj wynik/i }));
    fireEvent.click(screen.getByRole("radio", { name: "Brak odpowiedzi" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz wynik" }));

    expect(
      await screen.findByText(
        "Ktoś zmienił ten kontakt. Odśwież dane i spróbuj ponownie.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => expect(candidateContactApi.queue).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: "Zapisz wynik" }));

    await waitFor(() => expect(submitAttempt).toHaveBeenCalledTimes(2));
    expect(submitAttempt.mock.calls[1]?.[1]).toMatchObject({
      expected_version: 5,
      outcome: "no_answer",
    });
  });

  it("shows a neutral disabled state and does not fetch the queue when rollout is off", async () => {
    vi.spyOn(candidateContactApi, "status").mockResolvedValue({
      enabled: false,
      assignment_enabled: false,
      traffit_intake_enabled: false,
    });
    const queueSpy = vi.spyOn(candidateContactApi, "queue");

    render(<ContactQueueWorkspace />, { wrapper });

    expect(
      await screen.findByText("Kolejka kontaktu jest obecnie wyłączona"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0/20")).not.toBeInTheDocument();
    expect(queueSpy).not.toHaveBeenCalled();
  });
});
