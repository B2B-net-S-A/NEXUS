import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WantedTopics } from "@/components/consultant-portal/TrainingScreens";
import { portalApi } from "@/lib/api/consultant-portal";
import type { LiveTraining, OrderInput, TrainingTopic } from "@/lib/api/trainings";

import { OrderFields } from "../OrderFields";
import { TeamsPanel } from "../TeamsPanel";
import { TopicRequests } from "../TopicRequests";
import { TrainingCalendar } from "../TrainingCalendar";
import { chapterClock, chapterSecond, emptyOrder } from "../training-model";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

describe("rozdziały z transkryptu", () => {
  it("sekunda z transkryptu wygrywa z minutą agendy", () => {
    expect(chapterSecond({ start_minute: 12, start_second: 760 })).toBe(760);
    expect(chapterSecond({ start_minute: 30 })).toBe(1800);
    expect(chapterClock(760)).toBe("12:40");
    expect(chapterClock(3730)).toBe("1:02:10");
    expect(chapterClock(5)).toBe("0:05");
  });
});

describe("zamówienie: próba techniczna i obowiązkowe dla roli", () => {
  it("zaznaczenie próby i roli przekazuje zmianę", async () => {
    const onChange = vi.fn();
    const value: OrderInput = { ...emptyOrder(), title: "Szkolenie" };
    render(
      <OrderFields
        value={value}
        onChange={onChange}
        deliverables={[]}
        onDeliverablesChange={vi.fn()}
        employee
        roles={["recruiter", "finance"]}
      />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: /Próba techniczna/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ rehearsal: true }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Finanse" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ mandatory_roles: ["finance"] }));
  });

  it("bez listy ról nie ma pola „Obowiązkowe dla roli”", () => {
    render(
      <OrderFields
        value={emptyOrder()}
        onChange={vi.fn()}
        deliverables={[]}
        onDeliverablesChange={vi.fn()}
        employee
      />,
    );
    expect(screen.queryByText("Obowiązkowe dla roli")).toBeNull();
    expect(screen.getByRole("checkbox", { name: /Próba techniczna/ })).toBeInTheDocument();
  });
});

const LIVE: LiveTraining = {
  id: 7,
  title: "RODO w rekrutacji",
  topic: "RODO",
  session_date: "2026-12-01",
  time_from: "10:00",
  time_to: "11:00",
  platform: "Microsoft Teams",
  registered: true,
  join_url: "https://teams.microsoft.com/l/meetup-join/x",
  invited: true,
  mandatory: true,
};

describe("kalendarz: obowiązkowe", () => {
  it("obowiązkowy zapis nie ma „Wypisz się”", () => {
    render(<TrainingCalendar today="2026-11-20" onRegister={vi.fn()} live={[LIVE]} />);
    expect(screen.getByText("Obowiązkowe dla Twojej roli")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wypisz się" })).toBeNull();
  });

  it("zwykły zapis nadal ma „Wypisz się”", () => {
    render(<TrainingCalendar today="2026-11-20" onRegister={vi.fn()} live={[{ ...LIVE, mandatory: false }]} />);
    expect(screen.getByRole("button", { name: "Wypisz się" })).toBeInTheDocument();
  });

  it("prowadzący widzi link do próby technicznej", () => {
    render(
      <TrainingCalendar
        today="2026-11-20"
        onRegister={vi.fn()}
        live={[
          { ...LIVE, id: 1, registered: true, mandatory: false, title: "Zapisane" },
          {
            ...LIVE,
            id: 2,
            registered: false,
            mandatory: false,
            leading: true,
            rehearsal: {
              status: "created",
              start: "2026-11-27T09:00:00Z",
              minutes: 15,
              join_url: "https://teams.microsoft.com/l/meetup-join/proba",
            },
          },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: /Próba:/ })).toHaveAttribute(
      "href",
      "https://teams.microsoft.com/l/meetup-join/proba",
    );
  });
});

describe("panel Teams: próba techniczna", () => {
  const base = {
    status: "signed" as const,
    trainer_kind: "employee" as const,
    join_url: "",
    teams: { status: "created" as const, error: null, synced_at: null, recording: null },
    files: [],
    published_at: null,
    shared_registered_at: null,
    feedback: { count: 0, average: null },
    registrations: 0,
    payment: { invoice_ready_at: null, paid_at: null },
  };

  it("założona próba pokazuje termin, nieudana ma „Spróbuj ponownie”", async () => {
    const onRetry = vi.fn().mockResolvedValue(true);
    const { rerender } = render(
      <TeamsPanel
        view={{ ...base, rehearsal: { status: "created", start: "2026-11-27T09:00:00Z", minutes: 15, join_url: "x" } }}
        me={{ can_manage: true, teams_ready: true }}
        onRetry={onRetry}
        onShare={vi.fn()}
      />,
    );
    expect(screen.getByTestId("teams-rehearsal")).toHaveTextContent("15 min, bez nagrywania");
    rerender(
      <TeamsPanel
        view={{ ...base, rehearsal: { status: "failed", start: null, minutes: 15, join_url: null } }}
        me={{ can_manage: true, teams_ready: true }}
        onRetry={onRetry}
        onShare={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(onRetry).toHaveBeenCalled();
  });
});

const TOPICS: TrainingTopic[] = [
  {
    id: 1,
    title: "Terraform i IaC",
    description: "2 h",
    audience: "rekruterzy IT",
    status: "open",
    created_at: null,
    closed_at: null,
    applicants: 2,
  },
  {
    id: 2,
    title: "Pact",
    description: "",
    audience: "",
    status: "closed",
    created_at: null,
    closed_at: null,
    applicants: 0,
  },
];

describe("Szukamy trenerów (NEXUS)", () => {
  it("lista otwartych, zamknięcie i nowy temat", async () => {
    const onSave = vi.fn().mockResolvedValue(true);
    render(<TopicRequests topics={TOPICS} onSave={onSave} />);
    expect(screen.getByText("2 zgłoszenia", { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(onSave).toHaveBeenCalledWith(1, expect.objectContaining({ open: false, title: "Terraform i IaC" }));

    const publish = screen.getByRole("button", { name: "Opublikuj temat" });
    expect(publish).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Nowy temat/), "Kubernetes dla rekruterów");
    await userEvent.click(publish);
    expect(onSave).toHaveBeenLastCalledWith(null, expect.objectContaining({ title: "Kubernetes dla rekruterów" }));
    await waitFor(() => expect(screen.getByLabelText(/Nowy temat/)).toHaveValue(""));
  });
});

describe("Szukamy trenerów (panel)", () => {
  const topics = [
    { id: 51, title: "Terraform", description: "", audience: "", applied: true },
    { id: 52, title: "Pact", description: "", audience: "", applied: false },
  ];

  it("bez zgłoszenia trenera link prowadzi do formularza z tematem", () => {
    wrap(<WantedTopics topics={topics} applied={false} />);
    const links = screen.getAllByRole("link", { name: "Zgłoś się na temat" });
    expect(links[0]).toHaveAttribute("href", "/konsultant/trener?temat=51");
  });

  it("ze zgłoszeniem: zgłoszenie i wycofanie jednym kliknięciem", async () => {
    const spy = vi.spyOn(portalApi, "trainerTopic").mockResolvedValue({ application: {} as never });
    wrap(<WantedTopics topics={topics} applied />);
    expect(screen.getByText("Zgłoszono")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zgłoś się na temat" }));
    expect(spy).toHaveBeenCalledWith(52, true);
    await userEvent.click(screen.getByRole("button", { name: "Wycofaj" }));
    expect(spy).toHaveBeenCalledWith(51, false);
  });
});
