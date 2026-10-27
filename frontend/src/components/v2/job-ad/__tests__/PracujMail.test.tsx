/**
 * Pracuj.pl mailem do opiekuna (27.10.2026): okno maila z podglądem
 * z serwera, stawka, skrzynka niepodłączona, wysyłka i stan „wysłane”
 * w karcie Pracuj.pl; wejście z maila (`&wyslij=opiekun`). Dane fikcyjne.
 */

import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import type {
  AdChannelView,
  AdReminders,
  JobAdState,
  PracujMailPreview,
  PracujMailRates,
} from "@/lib/api/jobAd";

import { AdChannels } from "../AdChannels";
import { parseRate, type PracujMailApi } from "../PracujMailDialog";
import { adState } from "./job-ad-fixtures";

function channel(patch: Partial<AdChannelView> & Pick<AdChannelView, "channel">): AdChannelView {
  return {
    state: "missing",
    since: null,
    mine: false,
    owner_names: [],
    skip_reason: null,
    skipped_by_name: null,
    ...patch,
  };
}

const LEAD: AdReminders = {
  can_manage: true,
  recruiter_names: [],
  channels: [
    channel({ channel: "kariera", mine: true }),
    channel({ channel: "pracuj", mine: true }),
    channel({ channel: "jjit", mine: true }),
  ],
};

function preview(rates: PracujMailRates, patch: Partial<PracujMailPreview> = {}): PracujMailPreview {
  const both = rates.rate_from && rates.rate_to;
  return {
    to_name: "Opiekunka",
    to_email: "ogloszenia@example.com",
    mailbox: "ready",
    from_address: "dl@example.com",
    subject: "Prośba o publikację ogłoszenia: Java Developer (k/m/x)",
    body_text: `Dzień dobry Opiekunka,\n\nStawka: ${both ? `${rates.rate_from}–${rates.rate_to} zł/h netto (B2B)` : "…"}`,
    rate_error: both ? null : "Wpisz stawkę dla kandydata.",
    ...patch,
  };
}

function setup({
  state = adState({ reminders: LEAD }),
  previewPatch = {},
  openSend = false,
  strict = false,
}: {
  state?: JobAdState;
  previewPatch?: Partial<PracujMailPreview>;
  openSend?: boolean;
  strict?: boolean;
} = {}) {
  const sent = adState({
    reminders: {
      ...LEAD,
      channels: LEAD.channels.map((c) =>
        c.channel === "pracuj" ? { ...c, state: "requested", since: "2026-10-27T15:00:00Z" } : c,
      ),
    },
    pracuj_request: {
      sent_at: "2026-10-27T15:00:00Z",
      sent_by_name: "Marta Prowadząca",
      to: "ogloszenia@example.com",
      waiting: true,
    },
  });
  const pracujMailApi = {
    previewPracujMail: vi.fn<PracujMailApi["previewPracujMail"]>(async (_jobId, rates) =>
      preview(rates, previewPatch),
    ),
    sendPracujMail: vi.fn<PracujMailApi["sendPracujMail"]>(async () => sent),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["job-ad", 7], state);
  const Wrapper = strict
    ? StrictMode
    : ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const view = render(
    <Wrapper>
      <QueryClientProvider client={client}>
        <AdChannels
          jobId={7}
          state={state}
          jobClosed={false}
          locked={false}
          publishBlockedReason={null}
          publishingCareer={false}
          careerCopied={false}
          onPublishCareer={vi.fn()}
          onCopyCareerLink={vi.fn()}
          onShowFinding={vi.fn()}
          onRemoveFinding={vi.fn()}
          api={{ markPublished: vi.fn(), markRemoved: vi.fn() }}
          pracujMailApi={pracujMailApi}
          openSend={openSend}
          onIntentHandled={vi.fn()}
        />
      </QueryClientProvider>
    </Wrapper>,
  );
  return { pracujMailApi, client, view };
}

async function typeRates(dialog: HTMLElement, from: string, to: string) {
  fireEvent.change(within(dialog).getByLabelText("Stawka od"), { target: { value: from } });
  fireEvent.change(within(dialog).getByLabelText("Stawka do"), { target: { value: to } });
}

beforeEach(() => vi.clearAllMocks());

describe("parseRate", () => {
  it("bierze same cyfry, puste = brak", () => {
    expect(parseRate("120")).toBe(120);
    expect(parseRate(" 1 2 0 zł")).toBe(120);
    expect(parseRate("")).toBeNull();
    expect(parseRate("abc")).toBeNull();
  });
});

describe("Pracuj.pl mailem do opiekuna", () => {
  it("DL otwiera mail z karty; bez stawki nie wyśle, ze stawką wysyła treść z serwera", async () => {
    const { pracujMailApi } = setup();
    fireEvent.click(screen.getByTestId("pracuj-send"));
    const dialog = await screen.findByRole("dialog", { name: "Wyślij ogłoszenie do Pracuj.pl" });
    expect(await within(dialog).findByText(/Stawka: …/)).toBeInTheDocument();
    expect(within(dialog).getByText("Opiekunka · ogloszenia@example.com")).toBeInTheDocument();
    const sendButton = within(dialog).getByRole("button", { name: "Wyślij z mojej skrzynki" });
    expect(sendButton).toBeDisabled();

    await typeRates(dialog, "110", "125");
    expect(
      await within(dialog).findByText(/Stawka: 110–125 zł\/h netto \(B2B\)/, {}, { timeout: 2000 }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sendButton).toBeEnabled());
    fireEvent.click(sendButton);

    await waitFor(() => expect(pracujMailApi.sendPracujMail).toHaveBeenCalledTimes(1));
    const [jobId, body] = pracujMailApi.sendPracujMail.mock.calls[0];
    expect(jobId).toBe(7);
    expect(body).toMatchObject({
      rate_from: 110,
      rate_to: 125,
      expected_updated_at: "2026-10-12T09:20:00Z",
    });
    expect(body.client_request_id).toEqual(expect.any(String));
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith(
        expect.stringContaining("Wysłane do ogloszenia@example.com"),
      ),
    );
  });

  it("bez podłączonej skrzynki okno prosi o podłączenie i zostawia tylko kopiowanie", async () => {
    setup({ previewPatch: { mailbox: "missing", from_address: null } });
    fireEvent.click(screen.getByTestId("pracuj-send"));
    const dialog = await screen.findByRole("dialog", { name: "Wyślij ogłoszenie do Pracuj.pl" });
    expect(
      await within(dialog).findByText("Twoja skrzynka Microsoft 365 nie jest podłączona"),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Podłącz w Ustawieniach" })).toHaveAttribute(
      "href",
      "/settings?area=me&item=outlook",
    );
    expect(
      within(dialog).queryByRole("button", { name: "Wyślij z mojej skrzynki" }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kopiuj treść maila" })).toBeEnabled();
  });

  it("awaria podglądu nie wygląda jak pusty mail", async () => {
    const { pracujMailApi } = setup();
    pracujMailApi.previewPracujMail.mockRejectedValue({
      response: { status: 500, data: { detail: "Coś poszło nie tak." } },
    });
    fireEvent.click(screen.getByTestId("pracuj-send"));
    const dialog = await screen.findByRole("dialog", { name: "Wyślij ogłoszenie do Pracuj.pl" });
    expect(await within(dialog).findByText("Nie udało się złożyć maila")).toBeInTheDocument();
    expect(within(dialog).queryByTestId("pracuj-mail-body")).not.toBeInTheDocument();
  });

  it("po wysyłce karta mówi, że czeka na opiekuna; rekruter widzi stan bez przycisku", () => {
    const requested = adState({
      reminders: { ...LEAD, can_manage: false },
      pracuj_request: {
        sent_at: "2026-10-27T15:00:00Z",
        sent_by_name: "Marta Prowadząca",
        to: "ogloszenia@example.com",
        waiting: true,
      },
    });
    setup({ state: requested });
    expect(screen.getByTestId("pracuj-request-status")).toHaveTextContent(
      "Wysłane do opiekuna 27.10.2026 · Marta Prowadząca · czeka na publikację",
    );
    expect(screen.queryByTestId("pracuj-send")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wisi — dodaj link" })).toBeInTheDocument();
  });

  it("ogłoszenie oznaczone jako wiszące — nie ma czego wysyłać", () => {
    const live = adState({
      reminders: LEAD,
      publications: [
        {
          portal: "pracuj",
          url: null,
          outdated: false,
          published_at: "2026-10-20T10:00:00Z",
          published_by_name: "Marta Prowadząca",
          removed_at: null,
        },
      ],
    });
    setup({ state: live });
    expect(screen.queryByTestId("pracuj-send")).not.toBeInTheDocument();
  });

  it("link z maila (`&wyslij=opiekun`) otwiera okno maila raz, także w StrictMode", async () => {
    setup({ openSend: true, strict: true });
    expect(
      await screen.findByRole("dialog", { name: "Wyślij ogłoszenie do Pracuj.pl" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("kopiowanie bierze temat i treść z podglądu", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    setup();
    fireEvent.click(screen.getByTestId("pracuj-send"));
    const dialog = await screen.findByRole("dialog", { name: "Wyślij ogłoszenie do Pracuj.pl" });
    await within(dialog).findByText(/Stawka: …/);
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Kopiuj treść maila" }));
    });
    expect(writeText).toHaveBeenCalledWith(
      expect.stringMatching(/^Prośba o publikację ogłoszenia: Java Developer \(k\/m\/x\)\n\nDzień dobry/),
    );
    expect(within(dialog).getByRole("button", { name: "Skopiowano" })).toBeInTheDocument();
  });
});
