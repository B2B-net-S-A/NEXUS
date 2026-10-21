/**
 * Okno minimum dla Delivery Leada z Tablicy (21.10.2026): pyta tylko o brakujące
 * pola, wpisuje pola o osobie z innej rekrutacji i zapisuje je jednym `PUT`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScreeningFormSave, ScreeningFormState } from "@/lib/api/screeningForm";
import {
  FORM_CANDIDATE_ID,
  FORM_JOB_ID,
  formSaveResult,
  formState,
} from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  };
  return { __esModule: true, default: client, api: client };
});

import { MinimumFieldsDialog } from "../MinimumFieldsDialog";

let serverState: ScreeningFormState;

function stateWith(overrides: Partial<ScreeningFormState["card"]> = {}): ScreeningFormState {
  const base = formState().card!;
  return formState({
    board_column: "screening",
    version: 4,
    state_token: "token-4",
    card: {
      ...base,
      labels: { ...base.labels, location: "Lokalizacja" },
      editable_fields: [...base.editable_fields, "location"],
      required: ["location", "work_mode", "availability", "recommendation"],
      fields: {
        availability: { raw: "od zaraz", source: "manual" },
        recommendation: { raw: "6 lat w Javie.", source: "manual" },
      },
      ...overrides,
    },
  });
}

function mount(props: { onDone?: () => void; onOpenFull?: () => void; onClose?: () => void } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onDone = props.onDone ?? vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <MinimumFieldsDialog
        open
        candidateId={FORM_CANDIDATE_ID}
        jobId={FORM_JOB_ID}
        candidateName="Tomasz Wzorcowy"
        actionLabel="Zapisz i przesuń"
        onDone={onDone}
        onOpenFull={props.onOpenFull ?? vi.fn()}
        onClose={props.onClose ?? vi.fn()}
      />
    </QueryClientProvider>,
  );
  return { onDone };
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.put.mockReset();
  mocks.get.mockImplementation(() => Promise.resolve({ data: serverState }));
});

describe("MinimumFieldsDialog", () => {
  it("pyta tylko o brakujące pola, wpisuje lokalizację z innej rekrutacji i zapisuje same pola karty", async () => {
    serverState = stateWith({
      carried: { location: { raw: "Warszawa", at: "2026-10-20T10:00:00+00:00", job_id: 7, job_title: "Analityk — Bank C" } },
    });
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState) }));
    const user = userEvent.setup();
    const { onDone } = mount();

    expect(await screen.findByLabelText("Lokalizacja")).toHaveValue("Warszawa");
    expect(screen.getByText("z rozmowy 20.10.2026 · Analityk — Bank C — sprawdź")).toBeInTheDocument();
    expect(screen.queryByLabelText("Dostępność")).toBeNull();
    expect(screen.getByText(/Delivery Lead potrzebuje jeszcze 2 pól/)).toBeInTheDocument();

    const save = screen.getByRole("button", { name: "Zapisz i przesuń" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Tryb pracy"), "hybryda, 2 dni");
    await user.click(save);

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.put.mock.calls[0] as [string, ScreeningFormSave];
    expect(url).toBe("/api/screening-form");
    expect(body).toMatchObject({
      expected_version: 4,
      state_token: "token-4",
      sheet: null,
      rate: null,
      card: { fields: { location: "Warszawa", work_mode: "hybryda, 2 dni" } },
    });
  });

  it("„-” nie odblokowuje zapisu; błąd zapisu zostaje w oknie", async () => {
    serverState = stateWith();
    mocks.put.mockRejectedValue(
      Object.assign(new Error("HTTP 409"), { response: { status: 409, data: { detail: "Ktoś zapisał formularz." } } }),
    );
    const user = userEvent.setup();
    const { onDone } = mount();
    await user.type(await screen.findByLabelText("Lokalizacja"), "-");
    await user.type(screen.getByLabelText("Tryb pracy"), "zdalnie");
    const save = screen.getByRole("button", { name: "Zapisz i przesuń" });
    expect(save).toBeDisabled();
    await user.clear(screen.getByLabelText("Lokalizacja"));
    await user.type(screen.getByLabelText("Lokalizacja"), "Łódź");
    await user.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent("Ktoś zapisał formularz.");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("komplet — przycisk od razu przesuwa, bez zapisu", async () => {
    serverState = stateWith({
      fields: {
        location: { raw: "Kraków", source: "manual" },
        work_mode: { raw: "zdalnie", source: "manual" },
        availability: { raw: "od zaraz", source: "manual" },
        recommendation: { raw: "6 lat w Javie.", source: "manual" },
      },
    });
    const user = userEvent.setup();
    const { onDone } = mount();
    expect(await screen.findByText("Minimum dla Delivery Leada jest już wpisane.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz i przesuń" }));
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(mocks.put).not.toHaveBeenCalled();
  });
});
