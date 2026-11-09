import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
const showError = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...args: unknown[]) => apiGet(...args) } }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError }) }));

import {
  CandidateCvBrowser,
  type CvBrowserAddToJob,
  type CvBrowserPerson,
} from "@/components/v2/candidates/CandidateCvBrowser";

// Plik tekstowy nie ma podglądu inline, więc okno nie pobiera bajtów.
function cv(candidateId: number) {
  return {
    id: candidateId * 10,
    filename: `CV-${candidateId}.txt`,
    content_type: "text/plain",
    size_bytes: 100,
    document_kind: "cv",
    is_primary: true,
    uploaded_at: "2026-10-01T08:00:00Z",
    external_source: null,
    created_at: "2026-10-01T08:00:00Z",
  };
}

const people: CvBrowserPerson[] = [
  { id: 1, name: "Marta Kowalczyk" },
  { id: 2, name: "Tomasz Nowicki" },
  { id: 3, name: "Ewa Zielińska" },
];

function Harness({
  start,
  onAssign,
  addToJob,
  list = people,
  onOpened = vi.fn(),
}: {
  start: CvBrowserPerson;
  onAssign?: (person: CvBrowserPerson) => void;
  addToJob?: CvBrowserAddToJob;
  list?: readonly CvBrowserPerson[];
  onOpened?: (person: CvBrowserPerson) => void;
}) {
  const [current, setCurrent] = useState<CvBrowserPerson | null>(start);
  return (
    <>
      <span data-testid="current">{current?.id ?? "zamknięte"}</span>
      <CandidateCvBrowser
        people={list}
        current={current}
        onChange={setCurrent}
        onOpened={onOpened}
        onAssign={onAssign}
        addToJob={addToJob}
      />
    </>
  );
}

beforeEach(() => {
  apiGet.mockReset();
  showError.mockReset();
  apiGet.mockImplementation((url: string) => {
    const id = Number(url.match(/candidates\/(\d+)\//)?.[1]);
    return Promise.resolve({ data: [cv(id)] });
  });
});

function addToJob(overrides: Partial<CvBrowserAddToJob> = {}): CvBrowserAddToJob {
  return {
    jobTitle: "Programista Java",
    readOnly: false,
    addedIds: new Set(),
    addingIds: new Set(),
    add: vi.fn(),
    ...overrides,
  };
}

describe("CandidateCvBrowser — dodawanie w „Szukaj ręcznie”", () => {
  it("„Dodaj do Nowych” dodaje oglądaną osobę i zostawia okno otwarte", async () => {
    const job = addToJob();
    render(<Harness start={people[1]} addToJob={job} />);

    const button = await screen.findByRole("button", { name: "Dodaj Tomasz Nowicki do Nowych" });
    expect(button).toHaveAttribute("title", "Dodaj do „Nowych” w „Programista Java”");
    fireEvent.click(button);

    expect(job.add).toHaveBeenCalledExactlyOnceWith(2);
    expect(screen.getByTestId("current").textContent).toBe("2");
  });

  it("osoba już dodana ma „Dodano” i nie da się jej dodać drugi raz", async () => {
    const job = addToJob({ addedIds: new Set([1]) });
    render(<Harness start={people[0]} addToJob={job} />);

    const button = await screen.findByRole("button", { name: "Marta Kowalczyk — dodano do Nowych" });
    expect(button).toBeDisabled();
    expect(button.textContent).toBe("Dodano");
  });

  it("w trakcie dodawania i w trybie tylko do odczytu przycisk jest nieaktywny", async () => {
    const { unmount } = render(
      <Harness start={people[0]} addToJob={addToJob({ addingIds: new Set([1]) })} />,
    );
    const adding = await screen.findByRole("button", { name: "Dodaj Marta Kowalczyk do Nowych" });
    expect(adding).toBeDisabled();
    expect(adding.textContent).toBe("Dodaję…");
    unmount();

    render(<Harness start={people[0]} addToJob={addToJob({ readOnly: true })} />);
    expect(await screen.findByRole("button", { name: "Dodaj Marta Kowalczyk do Nowych" })).toBeDisabled();
  });

  it("po zniknięciu dodanej osoby z wyników licznik i strzałki zostają", async () => {
    const job = addToJob();
    const { rerender } = render(<Harness start={people[1]} addToJob={job} list={people} />);
    expect(await screen.findByText("Osoba 2 z 3")).toBeTruthy();

    // Odświeżona lista nie ma już dodanej osoby (`recruitment_match=not_assigned`).
    rerender(
      <Harness
        start={people[1]}
        addToJob={job}
        list={people.filter((person) => person.id !== 2)}
      />,
    );

    expect(screen.getByText("Osoba 2 z 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Następna osoba: Ewa Zielińska" }));
    expect(await screen.findByText("CV-3.txt")).toBeTruthy();
  });

  it("bez kontekstu rekrutacji przycisku dodawania nie ma", async () => {
    render(<Harness start={people[0]} />);
    expect(await screen.findByText("CV-1.txt")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /do Nowych/ })).toBeNull();
  });
});

describe("CandidateCvBrowser — CV kolejnych osób z listy", () => {
  it("pokazuje imię i pozycję, przechodzi przyciskami i Shift + strzałką", async () => {
    const onOpened = vi.fn();
    render(<Harness start={people[0]} onOpened={onOpened} />);

    expect(await screen.findByText("CV-1.txt")).toBeTruthy();
    expect(screen.getByText("· Marta Kowalczyk")).toBeTruthy();
    expect(screen.getByText("Osoba 1 z 3")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Poprzednia osoba" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Następna osoba: Tomasz Nowicki" }));
    expect(await screen.findByText("CV-2.txt")).toBeTruthy();
    expect(screen.getByText("Osoba 2 z 3")).toBeTruthy();

    fireEvent.keyDown(window, { key: "ArrowRight", shiftKey: true });
    expect(await screen.findByText("CV-3.txt")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Następna osoba" })).toBeDisabled();

    fireEvent.keyDown(window, { key: "ArrowLeft", shiftKey: true });
    expect(await screen.findByText("CV-2.txt")).toBeTruthy();

    expect(onOpened.mock.calls.map(([person]) => person.id)).toEqual([1, 2, 3, 2]);
  });

  it("Shift + strzałka w polu „Szukaj w CV” nie zmienia osoby", async () => {
    render(<Harness start={people[0]} />);
    expect(await screen.findByText("CV-1.txt")).toBeTruthy();

    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "ArrowRight", shiftKey: true });

    expect(screen.getByTestId("current").textContent).toBe("1");
    input.remove();
  });

  it("„Przypisz do rekrutacji” zamyka CV i oddaje osobę, którą się ogląda", async () => {
    const onAssign = vi.fn();
    render(<Harness start={people[1]} onAssign={onAssign} />);

    fireEvent.click(await screen.findByRole("button", { name: "Przypisz do rekrutacji" }));

    expect(onAssign).toHaveBeenCalledWith(people[1]);
    expect(screen.getByTestId("current").textContent).toBe("zamknięte");
  });

  it("bez onAssign (okno rekrutacji) nie ma przycisku przypisania", async () => {
    render(<Harness start={people[0]} />);
    expect(await screen.findByText("CV-1.txt")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Przypisz do rekrutacji" })).toBeNull();
  });

  it("następna osoba bez pliku CV: komunikat i zostaje poprzednia", async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({ data: url.includes("/2/") ? [] : [cv(1)] }),
    );
    const onOpened = vi.fn();
    render(<Harness start={people[0]} onOpened={onOpened} />);
    expect(await screen.findByText("CV-1.txt")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Następna osoba: Tomasz Nowicki" }));

    await waitFor(() => expect(showError).toHaveBeenCalledWith("Tomasz Nowicki nie ma zapisanego pliku CV."));
    await waitFor(() => expect(screen.getByTestId("current").textContent).toBe("1"));
    expect(screen.getByText("CV-1.txt")).toBeTruthy();
    expect(onOpened.mock.calls.map(([person]) => person.id)).not.toContain(2);
  });

  it("nieudane otwarcie pierwszej osoby zamyka okno i nie liczy się jako obejrzane", async () => {
    apiGet.mockRejectedValueOnce(new Error("500"));
    const onOpened = vi.fn();
    render(<Harness start={people[0]} onOpened={onOpened} />);

    await waitFor(() => expect(screen.getByTestId("current").textContent).toBe("zamknięte"));
    expect(showError).toHaveBeenCalled();
    expect(onOpened).not.toHaveBeenCalled();
  });
});
