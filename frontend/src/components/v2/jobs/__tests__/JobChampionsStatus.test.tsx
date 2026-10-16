/**
 * Plakietka statusu w nagłówku rekrutacji = jedyne miejsce wskazywania
 * championów (D2, 15.10.2026): Delivery Lead zaznacza osoby i zapisuje pełną
 * listę, rekruter widzi championów do odczytu, a bez championów — samą
 * plakietkę.
 */

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobChampionsStatus } from "@/components/v2/jobs/JobChampionsStatus";
import type { JobChampionsFields } from "@/lib/job-champions";
import type { JobChampionsView } from "@/lib/job-champions-api";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
const toast = vi.hoisted(() => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ default: apiMock, api: apiMock }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const VIEW: JobChampionsView = {
  job_id: 42,
  can_edit: true,
  seats: 1,
  hired_count: 0,
  search_stopped: true,
  legacy_flag: false,
  work_state: "searching",
  champions: [
    {
      candidate_id: 1,
      name: "Karol Wzorcowy",
      column: "client_interview",
      stage_label: "Rozmowa u klienta",
      marked_by_name: "Olga Wzorcowa",
      marked_at: "2026-10-15T10:12:00Z",
    },
  ],
  eligible: [
    {
      candidate_id: 3,
      name: "Iza Umowna",
      column: "contract",
      stage_label: "Umowa wysłana",
      is_champion: false,
    },
    {
      candidate_id: 2,
      name: "Bartek Testowy",
      column: "client_interview",
      stage_label: "Rozmowa u klienta",
      is_champion: false,
    },
    {
      candidate_id: 1,
      name: "Karol Wzorcowy",
      column: "client_interview",
      stage_label: "Rozmowa u klienta",
      is_champion: true,
    },
  ],
};

const ONE_CHAMPION: JobChampionsFields = {
  request_status: "champion",
  champions: [{ candidate_id: 1, name: "Karol Wzorcowy" }],
  champion_seats: 1,
  hired_count: 0,
};

function Harness({
  job,
  canEdit,
  onOpenPerson,
}: {
  job: JobChampionsFields;
  canEdit: boolean;
  onOpenPerson?: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <JobChampionsStatus
      jobId={42}
      job={job}
      canEdit={canEdit}
      open={open}
      onOpenChange={setOpen}
      onOpenPerson={onOpenPerson}
    />
  );
}

function renderStatus(props: Parameters<typeof Harness>[0]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

const status = () => screen.getByTestId("job-champions-status");

describe("JobChampionsStatus", () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.put.mockReset();
    toast.showSuccess.mockReset();
    apiMock.get.mockResolvedValue({ data: VIEW });
  });

  it("Delivery Lead: klik otwiera listę po kolumnach, zaznaczenie i Zapisz wysyła pełną listę", async () => {
    apiMock.put.mockResolvedValue({ data: { ...VIEW, changed: true, work_state_changed: false } });
    const { invalidate } = renderStatus({ job: ONE_CHAMPION, canEdit: true });

    expect(status()).toHaveTextContent("Champion: Karol W.");
    expect(status()).toHaveAttribute("data-help", "job.champion.found");
    // Lista dopiero po otwarciu okienka.
    expect(apiMock.get).not.toHaveBeenCalled();
    await userEvent.click(status());
    const popover = await screen.findByTestId("job-champions-popover");
    expect(apiMock.get).toHaveBeenCalledWith("/api/jobs/42/champions");

    const groups = await within(popover).findAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual([
      "Akceptacja i umowa",
      "Rozmowa u klienta",
    ]);
    // Etap z serwera jako drugi tekst, gdy mówi więcej niż nazwa kolumny.
    expect(within(groups[0]).getByText("Umowa wysłana")).toBeInTheDocument();
    expect(within(popover).getByLabelText("Karol Wzorcowy")).toBeChecked();
    expect(within(popover).getByTestId("job-champions-save")).toBeDisabled();

    await userEvent.click(within(popover).getByLabelText("Bartek Testowy"));
    expect(within(popover).getByTestId("job-champions-effects")).toHaveTextContent(
      "Po zapisie rekrutacja nie szuka",
    );
    await userEvent.click(within(popover).getByTestId("job-champions-save"));

    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/jobs/42/champions", {
        candidate_ids: [2, 1],
      }),
    );
    await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith("Zapisano championów."));
    await waitFor(() => expect(screen.queryByTestId("job-champions-popover")).toBeNull());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "42"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs-v2"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "42"] });
  });

  it("odznaczenie wszystkich zapowiada powrót do „Szukamy” i wysyła pustą listę", async () => {
    apiMock.put.mockResolvedValue({ data: { ...VIEW, champions: [], changed: true } });
    renderStatus({ job: ONE_CHAMPION, canEdit: true });
    await userEvent.click(status());
    const popover = await screen.findByTestId("job-champions-popover");
    await userEvent.click(await within(popover).findByLabelText("Karol Wzorcowy"));
    expect(within(popover).getByTestId("job-champions-effects")).toHaveTextContent(
      "Po zapisie rekrutacja wróci do „Szukamy”.",
    );
    await userEvent.click(within(popover).getByTestId("job-champions-save"));
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/jobs/42/champions", { candidate_ids: [] }),
    );
  });

  it("stara flaga bez osób: ostrzeżenie i „Mamy championa” na plakietce (D1)", async () => {
    apiMock.get.mockResolvedValue({
      data: {
        ...VIEW,
        legacy_flag: true,
        champions: [],
        eligible: VIEW.eligible.map((e) => ({ ...e, is_champion: false })),
      },
    });
    renderStatus({ job: { request_status: "champion", champions: [] }, canEdit: true });
    expect(status()).toHaveTextContent("Mamy championa");
    await userEvent.click(status());
    expect(await screen.findByTestId("job-champions-legacy")).toHaveTextContent(
      "Oznaczone wcześniej bez wskazania osoby. Zaznacz, kto jest championem.",
    );
  });

  it("nikt jeszcze u klienta: zdanie, od kiedy można wskazać championa", async () => {
    apiMock.get.mockResolvedValue({ data: { ...VIEW, champions: [], eligible: [] } });
    renderStatus({ job: { request_status: "searching", champions: [] }, canEdit: true });
    await userEvent.click(status());
    expect(await screen.findByTestId("job-champions-empty")).toHaveTextContent(
      "Nikt z tej rekrutacji nie jest jeszcze u klienta. Championa można wskazać od „CV wysłane”.",
    );
  });

  it("błąd 422 z serwera: komunikat `detail.message` w okienku, okienko zostaje", async () => {
    apiMock.put.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            code: "champion_not_eligible",
            message: "Bartek Testowy nie jest już u klienta — odśwież listę.",
            candidate_ids: [2],
          },
        },
      },
    });
    renderStatus({ job: ONE_CHAMPION, canEdit: true });
    await userEvent.click(status());
    const popover = await screen.findByTestId("job-champions-popover");
    await userEvent.click(await within(popover).findByLabelText("Bartek Testowy"));
    await userEvent.click(within(popover).getByTestId("job-champions-save"));
    expect(await within(popover).findByTestId("job-champions-error")).toHaveTextContent(
      "Bartek Testowy nie jest już u klienta — odśwież listę.",
    );
    expect(toast.showSuccess).not.toHaveBeenCalled();
  });

  it("rekruter: lista championów do odczytu — etap, kto oznaczył, imię otwiera panel osoby", async () => {
    const onOpenPerson = vi.fn();
    renderStatus({ job: ONE_CHAMPION, canEdit: false, onOpenPerson });
    await userEvent.click(status());
    const list = await screen.findByTestId("job-champions-read-list");
    expect(within(list).queryByRole("checkbox")).toBeNull();
    expect(within(list).getByText("· Rozmowa u klienta")).toBeInTheDocument();
    expect(within(list).getByText(/Oznaczył\(a\): Olga Wzorcowa, 15\.10\.2026/)).toBeInTheDocument();
    const link = within(list).getByRole("link", { name: "Karol Wzorcowy" });
    expect(link).toHaveAttribute("href", "/jobs/42?candidate=1");
    await userEvent.click(link);
    expect(onOpenPerson).toHaveBeenCalledWith(1);
    await waitFor(() => expect(screen.queryByTestId("job-champions-popover")).toBeNull());
  });

  it("rekruter bez championów: sama plakietka, bez przycisku i bez zapytania", () => {
    renderStatus({ job: { request_status: "searching", champions: [] }, canEdit: false });
    expect(status().tagName).toBe("SPAN");
    expect(status()).toHaveTextContent("Szukamy");
    expect(screen.queryByRole("button")).toBeNull();
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("championów mniej niż miejsc: „Szukamy · 1 z 2” z pucharem", () => {
    renderStatus({
      job: { ...ONE_CHAMPION, request_status: "searching", champion_seats: 2 },
      canEdit: false,
    });
    expect(status()).toHaveTextContent("Szukamy ·1 z 2");
    expect(status()).toHaveAttribute("data-kind", "partial");
  });
});
