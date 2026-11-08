/**
 * JustJoin.IT przez API w oknie „Ogłoszenie”: kto widzi przycisk, kiedy jest
 * wyłączony, co wysyła okno publikacji i jak karta mówi o ogłoszeniu w kolejce.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

vi.mock("@/components/v2/recruitment/PortalListingForm", () => ({
  PortalListingForm: ({
    value,
    onChange,
    problems,
  }: {
    value: { category: string | null };
    onChange: (next: unknown) => void;
    problems: string[];
  }) => (
    <div>
      <button type="button" onClick={() => onChange({ ...value, category: "java" })}>
        Wybierz kategorię
      </button>
      {problems.map((problem) => (
        <p key={problem}>{problem}</p>
      ))}
    </div>
  ),
}));

import type { AdJjitApi, AdPublication, JobAdState } from "@/lib/api/jobAd";

import { AdChannels } from "../AdChannels";
import { AdPublications, type AdPublicationsApi } from "../AdPublications";
import { JjitPublishDialog } from "../JjitPublishDialog";
import { adState, publication } from "./job-ad-fixtures";

const OPTIONS = {
  category: null,
  experience_level: "senior",
  working_time: "full_time",
  workplace_type: "remote",
  office_days: null,
  city: "Warszawa",
  salary: null,
};

const READY: AdJjitApi = {
  ready: true,
  status: null,
  pending_action: null,
  last_error: null,
  options: null,
};

const LIVE_CAREER = { status: "live" as const, url: "https://kariera.example/r/x", published_at: null, published_by_name: null };

const API: AdPublicationsApi = {
  markPublished: vi.fn(),
  markRemoved: vi.fn(async () => adState()),
};

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function card(state: JobAdState, actions = true, onPublish = vi.fn()) {
  wrap(
    <AdPublications
      jobId={7}
      portals={["jjit"]}
      state={state}
      api={API}
      jjitActions={
        actions
          ? { onPublish, onUpdate: vi.fn(), updating: false, blockedReason: null }
          : undefined
      }
    />,
  );
  return within(screen.getByRole("listitem", { name: "Publikacja: JustJoin.IT" }));
}

const jjit = (patch: Partial<AdPublication> = {}) => publication({ portal: "jjit", ...patch });

beforeEach(() => vi.clearAllMocks());

describe("karta JustJoin.IT przy włączonym portalu", () => {
  it("przy wyłączonym portalu zostaje kopiuj-wklej, bez przycisku publikacji", () => {
    const row = card(adState({ jjit_api: null }));
    expect(row.queryByTestId("jjit-publish")).toBeNull();
    expect(row.getByRole("button", { name: "Kopiuj opis JustJoin.IT" })).toBeTruthy();
  });

  it("DL publikuje jednym kliknięciem, opis do kopiowania znika", () => {
    const onPublish = vi.fn();
    const row = card(adState({ jjit_api: READY }), true, onPublish);
    fireEvent.click(row.getByTestId("jjit-publish"));
    expect(onPublish).toHaveBeenCalledOnce();
    expect(row.queryByRole("button", { name: "Kopiuj opis JustJoin.IT" })).toBeNull();
  });

  it("rekruter nie ma przycisku i wie, kto publikuje", () => {
    const row = card(adState({ jjit_api: READY }), false);
    expect(row.queryByTestId("jjit-publish")).toBeNull();
    expect(row.getByText(/publikuje Delivery Lead/)).toBeTruthy();
  });

  it("w trakcie wysyłki nie ma ani publikacji, ani ręcznego oznaczania", () => {
    const row = card(adState({ jjit_api: { ...READY, status: "publishing", pending_action: "publish" } }));
    expect(row.getByTestId("jjit-api-status").textContent).toBe("Wysyłam na portal…");
    expect(row.queryByTestId("jjit-publish")).toBeNull();
    expect(row.queryByRole("button", { name: "Oznacz jako opublikowane" })).toBeNull();
  });

  it("odmowa portalu mówi o sobie i pozwala wysłać ponownie", () => {
    const row = card(
      adState({
        jjit_api: { ...READY, status: "failed", last_error: "Portal wymaga logo firmy." },
      }),
    );
    expect(row.getByRole("alert").textContent).toContain("logo");
    expect(row.getByTestId("jjit-publish").textContent).toBe("Wyślij ponownie");
  });

  it("ogłoszenie z API zdejmuje się przez portal, bez ręcznych oznaczeń", async () => {
    const row = card(
      adState({
        publications: [jjit()],
        jjit_api: { ...READY, status: "published" },
      }),
    );
    expect(row.queryByRole("button", { name: "Zdjęte z portalu" })).toBeNull();
    expect(row.queryByRole("button", { name: /link/ })).toBeNull();
    fireEvent.click(row.getByRole("button", { name: "Zdejmij z JustJoin.IT" }));
    const dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    expect(dialog.textContent).toContain("nowy kredyt");
    fireEvent.click(within(dialog).getByRole("button", { name: "Zdejmij z JustJoin.IT" }));
    await waitFor(() => expect(API.markRemoved).toHaveBeenCalledWith(7, "jjit"));
  });

  it("rekruter widzi ogłoszenie z API, ale go nie zdejmie", () => {
    const row = card(
      adState({ publications: [jjit()], jjit_api: { ...READY, status: "published" } }),
      false,
    );
    expect(row.queryByRole("button", { name: "Zdejmij z JustJoin.IT" })).toBeNull();
    expect(row.getByText(/Opublikowane/)).toBeTruthy();
  });

  it("zmieniona treść prowadzi przez stronę kariery", () => {
    const row = card(
      adState({
        publications: [jjit({ outdated: true })],
        jjit_api: { ...READY, status: "published" },
      }),
    );
    expect(row.getByTestId("jjit-update")).toBeTruthy();
    expect(row.getByText(/Zaktualizuj stronę kariery/)).toBeTruthy();
    expect(row.queryByRole("button", { name: "Zaktualizowane na portalu" })).toBeNull();
  });

  it("przy formularzu portalu podpowiedź nie odsyła do strony kariery", () => {
    const row = card(
      adState({
        publications: [jjit({ outdated: true })],
        jjit_api: { ...READY, status: "published", career_required: false },
      }),
    );
    expect(row.getByText(/Kliknij „Zaktualizuj na JustJoin.IT”/)).toBeTruthy();
    expect(row.queryByText(/Zaktualizuj stronę kariery/)).toBeNull();
  });

  it("ogłoszenie oznaczone ręcznie zostaje ręczne, bez publikacji przez API", () => {
    const row = card(adState({ publications: [jjit()], jjit_api: READY }));
    expect(row.queryByTestId("jjit-publish")).toBeNull();
    expect(row.getByRole("button", { name: "Zdjęte z portalu" })).toBeTruthy();
  });
});

describe("AdChannels", () => {
  const channels = (state: JobAdState) =>
    wrap(
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
        api={API}
      />,
    );
  const reminders = { channels: [], can_manage: true, recruiter_names: [] };

  it("bez strony kariery przycisk jest wyłączony, a powód widać", () => {
    channels(adState({ jjit_api: READY, reminders }));
    expect((screen.getByTestId("jjit-publish") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Najpierw opublikuj na stronie kariery/)).toBeTruthy();
  });

  it("przy formularzu JJIT strona kariery nie blokuje publikacji (06.11.2026)", () => {
    channels(adState({ jjit_api: { ...READY, career_required: false }, reminders }));
    expect((screen.getByTestId("jjit-publish") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(/Najpierw opublikuj na stronie kariery/)).toBeNull();
  });

  it("„Opublikuj ogłoszenie” otwiera najpierw okno JustJoin.IT (07.11.2026)", async () => {
    channels(adState({ jjit_api: { ...READY, career_required: false }, reminders }));
    expect(screen.getByTestId("publish-all")).toBeTruthy();

    fireEvent.click(screen.getByTestId("publish-all-start"));

    expect(await screen.findByRole("dialog", { name: /Opublikuj na JustJoin.IT/ })).toBeTruthy();
  });

  it("osoba bez prawa decyzji nie dostaje przycisku", () => {
    channels(
      adState({
        jjit_api: READY,
        career: LIVE_CAREER,
        reminders: { ...reminders, can_manage: false },
      }),
    );
    expect(screen.queryByTestId("jjit-publish")).toBeNull();
  });
});

describe("okno publikacji", () => {
  function dialog(api: { publishJjit: ReturnType<typeof vi.fn> }) {
    const onPublished = vi.fn();
    wrap(
      <JjitPublishDialog
        open
        jobId={7}
        state={adState({ jjit_api: { ...READY, options: OPTIONS } })}
        api={api as never}
        onClose={vi.fn()}
        onPublished={onPublished}
      />,
    );
    return onPublished;
  }

  it("bez kategorii nie wysyła i mówi, czego brakuje", () => {
    const api = { publishJjit: vi.fn() };
    dialog(api);
    fireEvent.click(screen.getByTestId("jjit-publish-confirm"));
    expect(api.publishJjit).not.toHaveBeenCalled();
    expect(screen.getByText("Wybierz kategorię ogłoszenia.")).toBeTruthy();
  });

  it("wysyła ustawienia z wersją z ekranu", async () => {
    const next = adState();
    const api = { publishJjit: vi.fn(async () => next) };
    const onPublished = dialog(api);
    fireEvent.click(screen.getByRole("button", { name: "Wybierz kategorię" }));
    fireEvent.click(screen.getByTestId("jjit-publish-confirm"));
    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(next));
    const [jobId, input] = api.publishJjit.mock.calls[0] as unknown as [
      number,
      { options: { category: string }; expected_updated_at: string },
    ];
    expect(jobId).toBe(7);
    expect(input.options.category).toBe("java");
    expect(input.expected_updated_at).toBe(adState().ad?.updated_at);
  });

  it("odmowa serwera zostaje w oknie jako komunikat", async () => {
    const api = {
      publishJjit: vi.fn(async () => {
        throw { response: { status: 409, data: { detail: { code: "ad_marked_published", message: "Oznaczone jako wiszące." } } } };
      }),
    };
    const onPublished = dialog(api);
    fireEvent.click(screen.getByRole("button", { name: "Wybierz kategorię" }));
    fireEvent.click(screen.getByTestId("jjit-publish-confirm"));
    await waitFor(() => expect(toast.showError).toHaveBeenCalled());
    expect(onPublished).not.toHaveBeenCalled();
  });
});
