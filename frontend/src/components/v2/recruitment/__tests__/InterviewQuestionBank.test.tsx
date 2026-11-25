import type { AnchorHTMLAttributes } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BankQuestion } from "@/lib/question-bank";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  query: { isPending: false, isError: false, data: undefined as { items: unknown[] } | undefined, refetch: vi.fn() },
}));
let urlParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
  usePathname: () => "/jobs/pytania",
  useRouter: () => ({ push: mocks.push, replace: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api/interviewCycle", () => ({ useQuestionBank: () => mocks.query }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));

import { InterviewQuestionBank } from "../InterviewQuestionBank";

function q(over: Partial<BankQuestion>): BankQuestion {
  return {
    id: 1,
    text: "Różnica między PUT a POST?",
    client_id: 1,
    client_name: "Klient A",
    source: "debrief",
    roles: [{ job_id: 10, title: "Programista Integracji · Java", job_number: "ZOB 1", manager: "Manager A" }],
    managers: ["Manager A"],
    asked_count: 1,
    last_asked_at: "2026-11-24T10:00:00Z",
    answer: null,
    answer_source: null,
    ...over,
  };
}

const ITEMS = [
  q({ id: 1, text: "REST i SOAP", answer_source: "none" }),
  q({ id: 2, answer: "PUT podmienia zasób i jest idempotentny.", answer_source: "ai" }),
  q({ id: 3, text: "Co to jest kolejka?" }),
  q({
    id: 4,
    text: "Doświadczenie z chmurą?",
    roles: [{ job_id: 20, title: "Senior .NET Developer", job_number: "ZOB 2", manager: null }],
    managers: [],
    last_asked_at: "2026-11-23T10:00:00Z",
  }),
];

describe("InterviewQuestionBank", () => {
  beforeEach(() => {
    urlParams = new URLSearchParams();
    mocks.push.mockReset();
    mocks.query = { isPending: false, isError: false, data: { items: ITEMS }, refetch: vi.fn() };
  });

  it("lista pokazuje stanowiska, nie pytania", () => {
    render(<InterviewQuestionBank />);
    const rows = screen.getAllByTestId("position-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Programista Integracji")).toBeInTheDocument();
    // Śródtytuł „REST i SOAP” nie liczy się do pytań.
    expect(within(rows[0]).getByText("2")).toBeInTheDocument();
    expect(screen.queryByText("Co to jest kolejka?")).not.toBeInTheDocument();
  });

  it("klik w stanowisko wpisuje je do adresu", () => {
    render(<InterviewQuestionBank />);
    fireEvent.click(screen.getAllByTestId("position-row")[1]);
    expect(mocks.push).toHaveBeenCalledWith("/jobs/pytania?stanowisko=20");
  });

  it("strona stanowiska: pytania, śródtytuł, odpowiedź po kliknięciu i oznaczenie AI", () => {
    urlParams = new URLSearchParams("stanowisko=10");
    render(<InterviewQuestionBank />);
    expect(screen.getByRole("heading", { name: "Programista Integracji" })).toBeInTheDocument();
    expect(screen.getAllByTestId("question-row")).toHaveLength(2);
    expect(screen.getByText("REST i SOAP")).toBeInTheDocument();
    expect(screen.queryByText("PUT podmienia zasób i jest idempotentny.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Odpowiedź" }));
    expect(screen.getByText("PUT podmienia zasób i jest idempotentny.")).toBeInTheDocument();
    expect(screen.getByText(/Propozycja odpowiedzi AI · do sprawdzenia/)).toBeInTheDocument();
    // Pytanie bez odpowiedzi mówi, skąd ona przyjdzie.
    expect(screen.getByText("odpowiedź po nocnym przebiegu")).toBeInTheDocument();
  });

  it("„Pokaż wszystkie odpowiedzi” rozwija odpowiedzi naraz", () => {
    urlParams = new URLSearchParams("stanowisko=10");
    render(<InterviewQuestionBank />);
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie odpowiedzi" }));
    expect(screen.getByText("PUT podmienia zasób i jest idempotentny.")).toBeInTheDocument();
  });

  it("strzałki prowadzą do sąsiedniego stanowiska, powrót czyści adres", () => {
    urlParams = new URLSearchParams("stanowisko=10");
    render(<InterviewQuestionBank />);
    expect(screen.getByRole("button", { name: /Poprzednie/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Następne/ }));
    expect(mocks.push).toHaveBeenLastCalledWith("/jobs/pytania?stanowisko=20");
    fireEvent.click(screen.getByRole("button", { name: /Wszystkie stanowiska/ }));
    expect(mocks.push).toHaveBeenLastCalledWith("/jobs/pytania");
  });

  it("nieznane stanowisko w adresie daje komunikat, nie pustą stronę", () => {
    urlParams = new URLSearchParams("stanowisko=999");
    render(<InterviewQuestionBank />);
    expect(screen.getByText("Tego stanowiska nie ma na liście")).toBeInTheDocument();
  });

  it("awaria zapytania nie wygląda jak pusta lista", () => {
    mocks.query = { isPending: false, isError: true, data: undefined, refetch: vi.fn() };
    render(<InterviewQuestionBank />);
    expect(screen.getByText(/nie wczytały się/)).toBeInTheDocument();
    expect(screen.queryByText("Brak stanowisk dla tych filtrów")).not.toBeInTheDocument();
  });
});
