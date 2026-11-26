import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import type { CvHighlightProposal, CvPage1Extras } from "@/lib/api";
import { CvEditorSection } from "@/lib/cv-editor-section";

import { pendingProposals, searched } from "../CvNewLayoutHighlightAi";
import { CvNewLayoutPage1 } from "../CvNewLayoutPage1";

// Wyróżnik z propozycji AI (Artur 26.11.2026): propozycja stoi obok trybów,
// do CV trafia dopiero po „Przyjmij”. Dane fikcyjne.

const CV =
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad <strong>7 lat</strong> w Javie.</p></li></ul>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Kierownik projektu</strong> 01.2019 – obecnie</p>' +
  '<p data-cv-section="employer">Example Bank</p>';

const AWARD: CvHighlightProposal = {
  kind: "award",
  label: "Wyróżnienie Best Project Manager",
  token: "2021",
  text: "**Best Project Manager 2021** za program KYC w Example Bank.",
  quote: "Wyróżnienie Best Project Manager 2021 za program KYC",
  key: "k-award",
  verified: true,
  source: "role",
  company: "Example Bank",
};
const CERT: CvHighlightProposal = {
  kind: "certificate",
  label: "Certyfikat PRINCE2 Practitioner",
  token: "PRINCE2",
  text: "Certyfikat **PRINCE2 Practitioner** wydany przez Axelos w 2021 r.",
  quote: "PRINCE2 Practitioner - Axelos (2021)",
  key: "k-cert",
  verified: true,
  source: "certification",
};
const UNVERIFIED: CvHighlightProposal = {
  ...AWARD,
  label: "Nagroda bez cytatu",
  key: "k-bad",
  verified: false,
  issue: "quote_not_in_cv",
};
const WITH_PROPOSALS: CvPage1Extras = { highlight_proposals: [UNVERIFIED, AWARD, CERT], highlight_source_sha: "s" };

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

function renderPage1(overrides: Partial<Parameters<typeof CvNewLayoutPage1>[0]> = {}) {
  const editor = new Editor({ extensions: [StarterKit, CvEditorSection], content: CV });
  editors.push(editor);
  const props = {
    editor,
    extras: WITH_PROPOSALS,
    disabled: false,
    onSaveResult: vi.fn(async () => undefined),
    onFindHighlight: vi.fn(async () => undefined),
    onOpenPositions: vi.fn(),
    onOpenText: vi.fn(),
    ...overrides,
  };
  render(<CvNewLayoutPage1 {...props} />);
  return props;
}

describe("propozycje do przyjęcia", () => {
  it("tylko sprawdzone, bez już przyjętej; brak listy = jeszcze nie szukano", () => {
    expect(pendingProposals(WITH_PROPOSALS).map((p) => p.index)).toEqual([1, 2]);
    const accepted = { ...WITH_PROPOSALS, highlight: { mode: "ai" as const, label: AWARD.label, text: AWARD.text, key: "k-award" } };
    expect(pendingProposals(accepted).map((p) => p.index)).toEqual([2]);
    expect(searched(WITH_PROPOSALS)).toBe(true);
    expect(searched({ highlight_proposals: [] })).toBe(true);
    expect(searched({})).toBe(false);
  });
});

describe("Wyróżnik — propozycja AI (26.11.2026)", () => {
  it("propozycja stoi obok automatu i bez kliknięcia nic się nie zapisuje", () => {
    const props = renderPage1();
    expect(screen.getByRole("radio", { name: "Automatycznie" })).toHaveAttribute("aria-checked", "true");
    const cards = screen.getAllByTestId("cv-new-highlight-proposal");
    expect(cards).toHaveLength(2); // niesprawdzona się nie pokazuje
    expect(within(cards[0]).getByText("Wyróżnienie Best Project Manager")).toBeInTheDocument();
    expect(within(cards[0]).getByText("Best Project Manager 2021 za program KYC w Example Bank.")).toBeInTheDocument();
    expect(within(cards[0]).getByText(/Z CV: „Wyróżnienie Best Project Manager 2021 za program KYC” · Example Bank/)).toBeInTheDocument();
    expect(within(cards[1]).getByText("Certyfikat z wymagań MUST")).toBeInTheDocument();
    expect(screen.queryByText("Nagroda bez cytatu")).not.toBeInTheDocument();
    expect(screen.getByText("Bez przyjęcia propozycja nie trafia do CV.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Propozycja AI" })).not.toBeDisabled();
    expect(props.onSaveResult).not.toHaveBeenCalled();
  });

  it("„Przyjmij” zapisuje tryb „ai” z numerem propozycji na liście", async () => {
    const user = userEvent.setup();
    const props = renderPage1();
    const [, cert] = screen.getAllByTestId("cv-new-highlight-proposal");
    await user.click(within(cert).getByRole("button", { name: "Przyjmij" }));
    await waitFor(() =>
      expect(props.onSaveResult).toHaveBeenCalledWith({ highlight: { mode: "ai", proposal: 2 } }),
    );
  });

  it("wybór „Propozycja AI” przyjmuje pierwszą propozycję", async () => {
    const user = userEvent.setup();
    const props = renderPage1();
    await user.click(screen.getByRole("radio", { name: "Propozycja AI" }));
    await waitFor(() =>
      expect(props.onSaveResult).toHaveBeenCalledWith({ highlight: { mode: "ai", proposal: 1 } }),
    );
  });

  it("„Odrzuć” wysyła numer propozycji do odrzucenia", async () => {
    const user = userEvent.setup();
    const props = renderPage1();
    const [award] = screen.getAllByTestId("cv-new-highlight-proposal");
    await user.click(within(award).getByRole("button", { name: "Odrzuć" }));
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ highlight_reject: 1 }));
  });

  it("przyjęta stoi jako „Na stronie 1”, inne zostają do wyboru, odrzucenie przyjętej idzie po jej numerze", async () => {
    const user = userEvent.setup();
    const props = renderPage1({
      extras: {
        ...WITH_PROPOSALS,
        highlight: { mode: "ai", label: AWARD.label, token: "2021", text: AWARD.text, quote: AWARD.quote, key: "k-award", kind: "award" },
      },
    });
    expect(screen.getByRole("radio", { name: "Propozycja AI" })).toHaveAttribute("aria-checked", "true");
    const accepted = screen.getByTestId("cv-new-highlight-accepted");
    expect(within(accepted).getByText("Na stronie 1")).toBeInTheDocument();
    expect(within(accepted).getByText("Wyróżnienie Best Project Manager")).toBeInTheDocument();
    expect(screen.getAllByTestId("cv-new-highlight-proposal")).toHaveLength(1);
    await user.click(within(accepted).getByRole("button", { name: "Odrzuć" }));
    await waitFor(() => expect(props.onSaveResult).toHaveBeenCalledWith({ highlight_reject: 1 }));
  });

  it("„Popraw jako własny” przenosi słowa propozycji do „Własnego” bez gwiazdek", async () => {
    const user = userEvent.setup();
    // Zapis w toku: w edytorze odpowiedź serwera podmienia dodatki, zanim zapis się skończy,
    // a tu dodatki stoją w miejscu — pola sprawdzamy w trakcie zapisu.
    const props = renderPage1({ onSaveResult: vi.fn(() => new Promise<void>(() => undefined)) });
    const [award] = screen.getAllByTestId("cv-new-highlight-proposal");
    await user.click(within(award).getByRole("button", { name: "Popraw jako własny" }));
    expect(screen.getByRole("radio", { name: "Własny" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("Etykieta")).toHaveValue("Wyróżnienie Best Project Manager");
    expect(screen.getByLabelText("Znak w wieńcu")).toHaveValue("2021");
    expect(screen.getByLabelText("Zdanie")).toHaveValue("Best Project Manager 2021 za program KYC w Example Bank.");
    await waitFor(() =>
      expect(props.onSaveResult).toHaveBeenCalledWith({
        highlight: {
          mode: "custom",
          label: "Wyróżnienie Best Project Manager",
          token: "2021",
          text: "Best Project Manager 2021 za program KYC w Example Bank.",
        },
      }),
    );
  });

  it("bez propozycji tryb „Propozycja AI” jest wyłączony, a „Poszukaj w CV” woła serwer", async () => {
    const user = userEvent.setup();
    const props = renderPage1({ extras: {} });
    expect(screen.getByRole("radio", { name: "Propozycja AI" })).toBeDisabled();
    expect(screen.getByText(/AI może poszukać w CV nagrody, wyróżnienia albo certyfikatu/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Poszukaj w CV" }));
    expect(props.onFindHighlight).toHaveBeenCalledTimes(1);
    expect(props.onSaveResult).not.toHaveBeenCalled();
  });

  it("po szukaniu bez wyniku mówi, że w CV nie ma czego zaproponować", () => {
    renderPage1({ extras: { highlight_proposals: [UNVERIFIED], highlight_source_sha: "s" } });
    expect(screen.getByText(/W CV nie ma nagrody, wyróżnienia ani certyfikatu z wymagań MUST/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Poszukaj od nowa" })).toBeInTheDocument();
  });

  it("awaria modelu (503) to zdanie serwera, nie błąd ekranu", async () => {
    const user = userEvent.setup();
    const onFindHighlight = vi.fn(async () => {
      throw { response: { status: 503, data: { detail: "Nie udało się teraz poszukać wyróżnika w CV." } } };
    });
    renderPage1({ extras: {}, onFindHighlight });
    await user.click(screen.getByRole("button", { name: "Poszukaj w CV" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się teraz poszukać wyróżnika w CV.");
    expect(screen.getByRole("radio", { name: "Automatycznie" })).toHaveAttribute("aria-checked", "true");
  });

  it("bez trasy szukania nie ma przycisku, a zablokowany formularz blokuje przyjęcie", () => {
    renderPage1({ onFindHighlight: undefined, disabled: true });
    expect(screen.queryByRole("button", { name: /Poszukaj/ })).not.toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: "Przyjmij" })) expect(button).toBeDisabled();
  });
});
