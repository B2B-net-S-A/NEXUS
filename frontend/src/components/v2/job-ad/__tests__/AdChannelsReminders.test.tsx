/**
 * Przypomnienia o ogłoszeniach w kolumnie „Gdzie publikujesz” (27.10.2026):
 * kto robi brak, „Nie publikujemy” z powodem tylko dla DL-a, „Przypomnij”
 * z potwierdzeniem i wejście z maila (okno „Nie publikujemy”, pytanie
 * o przypomnienie). Dane fikcyjne.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import type { AdChannelView, AdReminders, JobAdState } from "@/lib/api/jobAd";

import { AdChannels, type AdReminderApi } from "../AdChannels";
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
  recruiter_names: ["Julia Przykładowa"],
  channels: [
    channel({ channel: "kariera", owner_names: ["Julia Przykładowa"] }),
    channel({ channel: "pracuj", mine: true, owner_names: ["Marta Prowadząca"] }),
    channel({ channel: "jjit", mine: true, owner_names: ["Marta Prowadząca"] }),
  ],
};

const RECRUITER: AdReminders = {
  ...LEAD,
  can_manage: false,
  channels: [
    channel({ channel: "kariera", mine: true, owner_names: ["Julia Przykładowa"] }),
    channel({ channel: "pracuj", owner_names: ["Marta Prowadząca"] }),
    channel({
      channel: "jjit",
      state: "skipped",
      skip_reason: "Klient nie chce JustJoin.IT",
      skipped_by_name: "Marta Prowadząca",
      since: "2026-10-27T09:00:00Z",
    }),
  ],
};

function setup(
  reminders: AdReminders,
  props: { openSkip?: boolean; askRemind?: boolean } = {},
) {
  const reminderApi = {
    skipChannel: vi.fn<AdReminderApi["skipChannel"]>(async () => adState({ reminders })),
    unskipChannel: vi.fn<AdReminderApi["unskipChannel"]>(async () => adState({ reminders })),
    remindRecruiters: vi.fn<AdReminderApi["remindRecruiters"]>(async () => ({
      sent_to: ["Julia Przykładowa"],
      already: [],
    })),
  };
  const onIntentHandled = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const state: JobAdState = adState({ reminders });
  render(
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
        reminderApi={reminderApi}
        onIntentHandled={onIntentHandled}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { reminderApi, onIntentHandled };
}

beforeEach(() => vi.clearAllMocks());

describe("AdChannels — przypomnienia o ogłoszeniach", () => {
  it("DL widzi, kto robi stronę kariery, i może przypomnieć z potwierdzeniem", async () => {
    const { reminderApi } = setup(LEAD);
    expect(screen.getByTestId("ad-channel-missing-kariera")).toHaveTextContent(
      "Robi: Julia P. — dostaje przypomnienie codziennie rano.",
    );
    expect(screen.getByTestId("ad-channel-missing-pracuj")).toHaveTextContent(
      "Przypomnienie przychodzi do Ciebie codziennie rano.",
    );
    fireEvent.click(screen.getByTestId("ad-remind-recruiters"));
    expect(reminderApi.remindRecruiters).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog", { name: "Przypomnieć: Julia P.?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Przypomnij" }));
    await waitFor(() => expect(reminderApi.remindRecruiters).toHaveBeenCalledWith(7));
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith("Wysłano przypomnienie: Julia P."),
    );
  });

  it("„Nie publikujemy” wymaga powodu i zapisuje zaznaczone kanały", async () => {
    const { reminderApi } = setup(LEAD);
    const line = screen.getByTestId("ad-channel-missing-jjit");
    fireEvent.click(within(line).getByRole("button", { name: "Nie publikujemy tu" }));
    const dialog = await screen.findByTestId("ad-skip-dialog");
    const save = within(dialog).getByRole("button", { name: "Zapisz „nie publikujemy”" });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "  Klient nie chce JustJoin.IT  " },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() =>
      expect(reminderApi.skipChannel).toHaveBeenCalledWith(7, "jjit", "Klient nie chce JustJoin.IT"),
    );
    expect(reminderApi.skipChannel).toHaveBeenCalledTimes(1);
  });

  it("rekruter nie ma „Nie publikujemy”, „Cofnij” ani „Przypomnij”", () => {
    setup(RECRUITER);
    expect(screen.queryByRole("button", { name: "Nie publikujemy tu" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cofnij" })).toBeNull();
    expect(screen.queryByTestId("ad-remind-recruiters")).toBeNull();
    expect(screen.getByTestId("ad-channel-skipped-jjit")).toHaveTextContent(
      "Nie publikujemy: Klient nie chce JustJoin.IT (Marta P., 27.10.2026)",
    );
  });

  it("z maila „Nie publikujemy tej rekrutacji” otwiera okno ze wszystkimi brakami", async () => {
    const { onIntentHandled } = setup(LEAD, { openSkip: true });
    const dialog = await screen.findByTestId("ad-skip-dialog");
    for (const name of ["Strona kariery", "Pracuj.pl", "JustJoin.IT"]) {
      expect(within(dialog).getByRole("checkbox", { name })).toBeChecked();
    }
    expect(onIntentHandled).toHaveBeenCalledTimes(1);
  });

  it("z maila „Przypomnij” od razu pyta, ale nic nie wysyła bez potwierdzenia", async () => {
    const { reminderApi } = setup(LEAD, { askRemind: true });
    const dialog = await screen.findByRole("dialog", { name: "Przypomnieć: Julia P.?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(reminderApi.remindRecruiters).not.toHaveBeenCalled();
  });

  it("rekruter z linku „pomin” nie dostaje okna — decyduje DL", () => {
    const { onIntentHandled } = setup(RECRUITER, { openSkip: true });
    expect(screen.queryByTestId("ad-skip-dialog")).toBeNull();
    expect(onIntentHandled).toHaveBeenCalledTimes(1);
  });
});
