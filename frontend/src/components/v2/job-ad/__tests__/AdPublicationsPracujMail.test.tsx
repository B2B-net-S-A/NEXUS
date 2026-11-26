/**
 * Link do Pracuj.pl z maila Pracuj.pl (26.11.2026): karta mówi, skąd jest link,
 * „To nie to ogłoszenie” pyta o potwierdzenie, a niepewny mail jest propozycją
 * „To ta rekrutacja” / „Nie”, której rekruter nie potwierdza.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import type { JobAdState, PracujMailSuggestion } from "@/lib/api/jobAd";

import { AdPublications, type AdPublicationsApi } from "../AdPublications";
import { adState, CLIENT_FINDING, publication } from "./job-ad-fixtures";

const PUBLIC_URL = "https://www.pracuj.pl/praca?groupId=00000000-0000-4000-8000-000000000001";

const MAIL: PracujMailSuggestion = {
  email_id: 41,
  subject: "Publikacja ogłoszenia na Senior Java Developer (k/m/x)",
  received_at: "2026-11-20T14:59:00Z",
  url: PUBLIC_URL,
};

function setup(state: JobAdState) {
  const api = {
    markPublished: vi.fn<AdPublicationsApi["markPublished"]>(async () => state),
    markRemoved: vi.fn<AdPublicationsApi["markRemoved"]>(async () => state),
    confirmPracujMail: vi.fn<NonNullable<AdPublicationsApi["confirmPracujMail"]>>(async () =>
      adState({
        publications: [
          publication({
            url: PUBLIC_URL,
            from_mail: { email_id: 41, subject: MAIL.subject, received_at: MAIL.received_at },
          }),
        ],
      }),
    ),
    rejectPracujMail: vi.fn<NonNullable<AdPublicationsApi["rejectPracujMail"]>>(async () =>
      adState(),
    ),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AdPublications jobId={7} portals={["pracuj"]} state={state} api={api} />
    </QueryClientProvider>,
  );
  return api;
}

const card = () => screen.getByRole("listitem", { name: "Publikacja: Pracuj.pl" });

beforeEach(() => vi.clearAllMocks());

describe("AdPublications — link z maila Pracuj.pl", () => {
  it("mówi, z którego maila jest link, a „To nie to ogłoszenie” pyta przed zdjęciem", async () => {
    const api = setup(
      adState({
        publications: [
          publication({
            url: PUBLIC_URL,
            from_mail: { email_id: 41, subject: MAIL.subject, received_at: MAIL.received_at },
          }),
        ],
      }),
    );
    expect(screen.getByTestId("pracuj-from-mail")).toHaveTextContent(
      "Link z maila Pracuj.pl z 20.11.2026: „Publikacja ogłoszenia na Senior Java Developer (k/m/x)”",
    );
    fireEvent.click(within(card()).getByRole("button", { name: "To nie to ogłoszenie" }));
    const dialog = await screen.findByRole("dialog", { name: "To nie to ogłoszenie?" });
    expect(api.rejectPracujMail).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "To nie to ogłoszenie" }));
    await waitFor(() => expect(api.rejectPracujMail).toHaveBeenCalledWith(7, 41));
  });

  it("ręcznie wklejony link nie ma źródła ani przycisku „To nie to ogłoszenie”", () => {
    setup(adState({ publications: [publication()] }));
    expect(screen.queryByTestId("pracuj-from-mail")).toBeNull();
    expect(within(card()).queryByRole("button", { name: "To nie to ogłoszenie" })).toBeNull();
  });

  it("niepewny mail to propozycja: „To ta rekrutacja” oznacza, „Nie” odrzuca", async () => {
    const api = setup(adState({ pracuj_mail_suggestions: [MAIL] }));
    const suggestion = screen.getByTestId("pracuj-mail-suggestion");
    expect(suggestion).toHaveTextContent("Pracuj.pl potwierdził publikację 20.11.2026");
    expect(within(suggestion).getByRole("link", { name: /Otwórz ogłoszenie/ })).toHaveAttribute(
      "href",
      PUBLIC_URL,
    );
    fireEvent.click(within(suggestion).getByRole("button", { name: "To ta rekrutacja" }));
    await waitFor(() => expect(api.confirmPracujMail).toHaveBeenCalledWith(7, 41));

    fireEvent.click(within(suggestion).getByRole("button", { name: "Nie" }));
    await waitFor(() => expect(api.rejectPracujMail).toHaveBeenCalledWith(7, 41));
  });

  it("propozycji z blokującym znaleziskiem nie da się potwierdzić", () => {
    setup(adState({ pracuj_mail_suggestions: [MAIL], findings: [CLIENT_FINDING] }));
    expect(
      within(screen.getByTestId("pracuj-mail-suggestion")).getByRole("button", {
        name: "To ta rekrutacja",
      }),
    ).toBeDisabled();
  });

  it("rekruter widzi propozycję bez przycisków", () => {
    setup({ ...adState({ pracuj_mail_suggestions: [MAIL] }), can_mark_publications: false });
    const suggestion = screen.getByTestId("pracuj-mail-suggestion");
    expect(within(suggestion).queryByRole("button")).toBeNull();
  });
});
