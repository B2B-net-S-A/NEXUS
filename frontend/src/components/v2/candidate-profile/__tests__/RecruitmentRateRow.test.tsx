import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({
  candidatesApi: {
    setRecruitmentExpectedRate: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
  },
}));

import { useAuthStore } from "@/store/auth";
import { RecruitmentRateRow, type ClientRateAccess } from "../RecruitmentsTab";

const clientRate = { value: 190, unit: "hourly", currency: "PLN" };
const expectedRate = { value: 150, unit: "hourly", currency: "PLN" };

function renderAs(roles: string[], clientRateAccess?: ClientRateAccess) {
  useAuthStore.setState({
    user: {
      id: 1,
      email: "osoba@example.com",
      name: "Osoba",
      role: roles[0],
      roles,
    } as never,
    hydrated: true,
  });
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RecruitmentRateRow
        candidateId={1}
        jobId={2}
        clientRate={clientRate}
        expectedRate={expectedRate}
        clientRateAccess={clientRateAccess}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => useAuthStore.setState({ user: null, hydrated: true }));

// Decyzja 23.09.2026: rekruter nie widzi stawki do klienta,
// HoR, TCM i Finanse widzą, zapisuje wyłącznie DL albo admin.
describe("RecruitmentRateRow — stawka do klienta wg roli", () => {
  it.each(["recruiter"])(
    "%s widzi tylko stawkę kandydata, bez marży",
    (role) => {
      renderAs([role]);
      expect(screen.getByText("Stawka kandydata")).toBeInTheDocument();
      expect(screen.queryByText("Stawka do klienta")).not.toBeInTheDocument();
      expect(screen.queryByText(/Marża/)).not.toBeInTheDocument();
    },
  );

  it.each(["head_of_recruitment", "talent_community_manager", "finance"])(
    "%s widzi stawkę do klienta bez przycisku edycji",
    (role) => {
      renderAs([role]);
      expect(screen.getByText("Stawka do klienta")).toBeInTheDocument();
      expect(screen.getByText(/Marża/)).toBeInTheDocument();
      expect(screen.queryByTestId("client-rate-edit")).not.toBeInTheDocument();
    },
  );

  it("Delivery Lead widzi i edytuje stawkę do klienta", () => {
    renderAs(["delivery_lead"]);
    expect(screen.getByTestId("client-rate-edit")).toBeInTheDocument();
  });

  it("rekruter z dodatkową rolą DL widzi stawkę do klienta", () => {
    renderAs(["recruiter", "delivery_lead"]);
    expect(screen.getByText("Stawka do klienta")).toBeInTheDocument();
  });
});

// Runda 10 (R10-X2-3): flagi z odpowiedzi `/history` wygrywają z rolą — serwer
// liczy też zapis w sekcji, którego przeglądarka nie zna.
describe("RecruitmentRateRow — flagi serwera", () => {
  it("DL bez zapisu w sekcji (can_write_client_rate=false) nie edytuje stawki", () => {
    renderAs(["delivery_lead"], { canView: true, canWrite: false });
    expect(screen.getByText("Stawka do klienta")).toBeInTheDocument();
    expect(screen.queryByTestId("client-rate-edit")).not.toBeInTheDocument();
  });

  it("serwer chowa stawkę do klienta mimo roli (can_view_client_rate=false)", () => {
    renderAs(["delivery_lead"], { canView: false, canWrite: false });
    expect(screen.queryByText("Stawka do klienta")).not.toBeInTheDocument();
    expect(screen.queryByText(/Marża/)).not.toBeInTheDocument();
  });

  it("brak flag w odpowiedzi — zapas z roli", () => {
    renderAs(["delivery_lead"], { canView: null, canWrite: undefined });
    expect(screen.getByTestId("client-rate-edit")).toBeInTheDocument();
  });
});

// 12.10.2026: para z czasów Traffita nie ma stawek na etapie — oczekiwanie
// kandydata leży w karcie rekomendacji, cena wysłania w notatce Delivery Leada
// z dnia wysyłki. Serwer dokłada je do `/history` jako podpowiedzi.
describe("RecruitmentRateRow — stawki z notatek, gdy etap ich nie ma", () => {
  const expectedRateHint = {
    amount_hourly: 90,
    raw: "90 zł/h",
    at: "2026-09-21T10:00:00+00:00",
    source: "card",
    author_name: "Anna Nowak",
  };
  const clientRateNote = {
    note_id: 7,
    text: "Wysłany 150/100-110",
    at: "2026-09-22T09:53:00+00:00",
    author_name: "Ewa Lis",
  };

  function renderHints(
    roles: string[],
    props: Partial<Parameters<typeof RecruitmentRateRow>[0]> = {},
  ) {
    useAuthStore.setState({
      user: { id: 1, email: "osoba@example.com", name: "Osoba", role: roles[0], roles } as never,
      hydrated: true,
    });
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <RecruitmentRateRow
          candidateId={1}
          jobId={2}
          clientRate={null}
          expectedRate={null}
          expectedRateHint={expectedRateHint}
          clientRateNote={clientRateNote}
          {...props}
        />
      </QueryClientProvider>,
    );
  }

  it("stawka kandydata z karty stoi zamiast „—”, z informacją skąd jest", () => {
    renderHints(["delivery_lead"]);
    expect(screen.getByText("90 PLN/h")).toBeInTheDocument();
    expect(screen.getByTestId("expected-rate-footnote")).toHaveTextContent(
      "Screening (z notatki) · Anna Nowak · 21.09.2026",
    );
    // Nadal podpowiedź, nie zapisana stawka.
    expect(screen.getByTestId("expected-rate-edit")).toHaveTextContent("Uzupełnij");
  });

  it("„Uzupełnij” otwiera pole z kwotą z karty i jednostką godzinową", () => {
    renderHints(["delivery_lead"]);
    fireEvent.click(screen.getByTestId("expected-rate-edit"));
    expect(screen.getByTestId("expected-rate-input")).toHaveValue(90);
    expect(screen.getByLabelText("Stawka kandydata — jednostka")).toHaveValue("hourly");
  });

  it("podpowiedź, która doszła po zamontowaniu wiersza, też trafia do pola", () => {
    const { rerender } = renderHints(["delivery_lead"], { expectedRateHint: null });
    expect(screen.queryByText("90 PLN/h")).not.toBeInTheDocument();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <RecruitmentRateRow
          candidateId={1}
          jobId={2}
          clientRate={null}
          expectedRate={null}
          expectedRateHint={expectedRateHint}
        />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByTestId("expected-rate-edit"));
    expect(screen.getByTestId("expected-rate-input")).toHaveValue(90);
    expect(screen.getByLabelText("Stawka kandydata — jednostka")).toHaveValue("hourly");
  });

  it("Delivery Lead widzi pod pustą stawką do klienta notatkę z wysyłki — bez wpisanej kwoty", () => {
    renderHints(["delivery_lead"]);
    expect(screen.getByTestId("client-rate-footnote")).toHaveTextContent(
      "Notatka z wysyłki · Ewa Lis · 22.09.2026: „Wysłany 150/100-110”",
    );
    fireEvent.click(screen.getByTestId("client-rate-edit"));
    expect(screen.getByTestId("client-rate-input")).toHaveValue(null);
  });

  it("rekruter nie dostaje notatki z wysyłki, nawet gdyby odpowiedź ją niosła", () => {
    renderHints(["recruiter"]);
    expect(screen.getByText("90 PLN/h")).toBeInTheDocument();
    expect(screen.queryByTestId("client-rate-footnote")).not.toBeInTheDocument();
    expect(screen.queryByText(/150\/100-110/)).not.toBeInTheDocument();
  });

  it("zapisana stawka wygrywa — podpowiedzi i dopisków nie ma", () => {
    renderHints(["delivery_lead"], { clientRate, expectedRate });
    expect(screen.getByText("150 PLN/h")).toBeInTheDocument();
    expect(screen.queryByText("90 PLN/h")).not.toBeInTheDocument();
    expect(screen.queryByTestId("expected-rate-footnote")).not.toBeInTheDocument();
    expect(screen.queryByTestId("client-rate-footnote")).not.toBeInTheDocument();
  });
});
