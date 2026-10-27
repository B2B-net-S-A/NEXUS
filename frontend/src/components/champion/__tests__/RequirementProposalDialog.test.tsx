import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showSuccess = vi.fn();
const showInfo = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/components/Toast", () => ({
  useOptionalToast: () => ({ showSuccess, showInfo, showError }),
}));

import { RequirementProposalDialog } from "@/components/champion/RequirementProposalDialog";
import type {
  RequirementProposal,
  RequirementProposalResponse,
} from "@/lib/requirement-proposal-api";

const HASH = "a".repeat(64);
const DIGEST = "d".repeat(64);

function proposal(over: Partial<RequirementProposal> = {}): RequirementProposal {
  return {
    job_id: 7,
    reasons: [
      { code: "prose_rows", text: "zdania w wymaganiach — wyszukiwanie ich nie znajdzie" },
      { code: "paren", text: "komentarz w nawiasie wyłącza technologię z wyszukiwania" },
    ],
    before: {
      must: ["Java (najlepiej 17)", "Praca z klientem z bankowości"],
      critical: ["Praca z klientem z bankowości"],
      language: null,
    },
    after: {
      rows: [
        { words: ["Java"], level: "must" },
        { words: ["Kafka", "RabbitMQ"], level: "nice" },
      ],
      critical: null,
      talk: [{ name: "Praca z klientem z bankowości", kind: "domains", level: "must" }],
      language: "angielski B2",
    },
    profile_hash: HASH,
    digest: DIGEST,
    contract_reviewed: false,
    can_apply: true,
    ...over,
  };
}

function respond(data: RequirementProposalResponse) {
  get.mockResolvedValue({ data });
}

function renderDialog(onOpenChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RequirementProposalDialog jobId={7} open onOpenChange={onOpenChange} jobTitle="Programista Java" />
    </QueryClientProvider>,
  );
  return { onOpenChange, qc };
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showSuccess.mockReset();
  showInfo.mockReset();
  showError.mockReset();
});

describe("RequirementProposalDialog", () => {
  it("pokazuje powody i porównanie „Teraz” → „Po zmianie”", async () => {
    respond({ proposal: proposal({ contract_reviewed: true }), can_decide: true });
    renderDialog();
    const after = await screen.findByRole("region", { name: "Po zmianie" });
    expect(get).toHaveBeenCalledWith("/api/jobs/7/requirement-proposal");
    expect(screen.getByRole("dialog")).toHaveTextContent("Programista Java");
    expect(screen.getByTestId("proposal-reasons")).toHaveTextContent(
      "Zdania w wymaganiach — wyszukiwanie ich nie znajdzie",
    );
    const before = screen.getByRole("region", { name: "Teraz" });
    expect(before).toHaveTextContent("Java (najlepiej 17)");
    expect(before).toHaveTextContent("Praca z klientem z bankowości · krytyczne");
    expect(before).toHaveTextContent("Język: brak");
    expect(within(after).getByTestId("proposal-rows-must")).toHaveTextContent("Java");
    expect(within(after).getByTestId("proposal-rows-nice")).toHaveTextContent("Kafka lub RabbitMQ");
    expect(within(after).getByText("Mile widziane")).toBeInTheDocument();
    expect(within(after).getByText("Rekruter sprawdza w rozmowie")).toBeInTheDocument();
    expect(within(after).getByTestId("proposal-talk")).toHaveTextContent("Praca z klientem z bankowości");
    expect(after).toHaveTextContent("Język: angielski B2");
    expect(screen.getByTestId("proposal-reviewed-note")).toHaveTextContent(
      "Zatwierdzenie zastąpi wymagania sprawdzone wcześniej przez człowieka.",
    );
  });

  it("słowa ponad limit wierszy są wymienione jako idące do opisu wymagań", async () => {
    respond({
      proposal: proposal({
        after: {
          rows: [{ words: ["Java"], level: "must" }],
          critical: [],
          talk: [],
          language: null,
          overflow: ["Oracle", "DB2"],
        },
      }),
      can_decide: true,
    });
    renderDialog();
    const after = await screen.findByRole("region", { name: "Po zmianie" });
    expect(within(after).getByTestId("proposal-overflow")).toHaveTextContent(
      "Nie mieści się w wierszach, trafi do opisu wymagań: Oracle, DB2",
    );
    // Wszystkie krytyczne schodzą do „musi mieć” — decyzja to „brak”, nie „nie wybrano”.
    expect(within(after).getByTestId("proposal-no-critical")).toHaveTextContent("Krytyczne: brak");
  });

  it("rzadkie słowa mówią, ile osób mają i co się z nimi stanie", async () => {
    respond({
      proposal: proposal({
        reasons: [
          {
            code: "rare_word",
            text: "słowo „musi mieć” ma w bazie mniej niż 20 osób — w CV opisują to inaczej",
          },
        ],
        after: {
          rows: [
            { words: ["Java"], level: "must" },
            { words: ["SoapUI", "ReadyAPI"], level: "must" },
          ],
          critical: null,
          talk: [{ name: "Crisis plans", kind: "skills", level: "must" }],
          language: null,
          rare: [
            { words: ["SoapUI/ReadyAPI"], people: 5, action: "split", parts: ["SoapUI", "ReadyAPI"] },
            { words: ["Crisis plans"], people: 0, action: "talk", parts: null },
          ],
        },
      }),
      can_decide: true,
    });
    renderDialog();
    const after = await screen.findByRole("region", { name: "Po zmianie" });
    const rare = within(after).getByTestId("proposal-rare");
    expect(rare).toHaveTextContent("„SoapUI/ReadyAPI” — tylko 5 osób, rozdzielone: SoapUI lub ReadyAPI");
    expect(rare).toHaveTextContent("„Crisis plans” — nikt w bazie, rekruter sprawdzi w rozmowie");
  });

  it("bez słów do szukania „Zatwierdź” jest wyłączone i prowadzi do Profilu Championa", async () => {
    respond({
      proposal: proposal({
        can_apply: false,
        after: { rows: [], critical: null, talk: [], language: null },
      }),
      can_decide: true,
    });
    renderDialog();
    const approve = await screen.findByRole("button", { name: "Zatwierdź" });
    expect(approve).toBeDisabled();
    expect(screen.getByTestId("proposal-hint")).toHaveTextContent(
      "Najpierw dodaj słowo do szukania w Profilu Championa",
    );
    expect(screen.getByRole("link", { name: "Uzupełnij" })).toHaveAttribute(
      "href",
      "/jobs/7?tab=champion&mode=edit",
    );
    expect(screen.getByRole("button", { name: "Odrzuć" })).toBeEnabled();
  });

  it("„Zatwierdź” wysyła odcisk profilu, pokazuje uwagi zapisu i zamyka okno", async () => {
    const user = userEvent.setup();
    respond({ proposal: proposal(), can_decide: true });
    post.mockResolvedValue({
      data: { job_id: 7, champion_profile: {}, notices: ["Krytyczna „Kafka” przestała być technologią."] },
    });
    const { onOpenChange } = renderDialog();
    await user.click(await screen.findByRole("button", { name: "Zatwierdź" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(post).toHaveBeenCalledWith("/api/jobs/7/requirement-proposal/apply", {
      profile_hash: HASH,
      proposal_digest: DIGEST,
    });
    expect(showSuccess).toHaveBeenCalledWith("Wymagania uporządkowane.");
    expect(showInfo).toHaveBeenCalledWith("Krytyczna „Kafka” przestała być technologią.");
  });

  it("„Odrzuć” pyta o potwierdzenie; anulowanie nic nie wysyła", async () => {
    const user = userEvent.setup();
    respond({ proposal: proposal(), can_decide: true });
    post.mockResolvedValue({ data: { job_id: 7, status: "dismissed" } });
    const { onOpenChange } = renderDialog();
    await user.click(await screen.findByRole("button", { name: "Odrzuć" }));
    const confirm = await screen.findByRole("dialog", { name: "Odrzucić propozycję?" });
    expect(confirm).toHaveTextContent("Wróci dopiero po zmianie Profilu Championa.");
    await user.click(within(confirm).getByRole("button", { name: "Anuluj" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Odrzucić propozycję?" })).not.toBeInTheDocument(),
    );
    expect(post).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Odrzuć" }));
    const again = await screen.findByRole("dialog", { name: "Odrzucić propozycję?" });
    await user.click(within(again).getByRole("button", { name: "Odrzuć" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/jobs/7/requirement-proposal/dismiss", {
        profile_hash: HASH,
        proposal_digest: DIGEST,
      }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(showSuccess).toHaveBeenCalledWith("Propozycja odrzucona.");
  });

  it("bez prawa do decyzji okno jest tylko do odczytu", async () => {
    respond({ proposal: proposal(), can_decide: false });
    renderDialog();
    expect(await screen.findByTestId("proposal-hint")).toHaveTextContent(
      "Zatwierdza Delivery Lead tej rekrutacji albo Head of Recruitment.",
    );
    expect(screen.queryByRole("button", { name: "Zatwierdź" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Odrzuć" })).not.toBeInTheDocument();
    // Krzyżyk w rogu i „Zamknij” w stopce.
    expect(screen.getAllByRole("button", { name: "Zamknij" })).toHaveLength(2);
  });

  it("409 — profil się zmienił: zdanie z serwera i nowa propozycja w oknie", async () => {
    const user = userEvent.setup();
    respond({ proposal: proposal(), can_decide: true });
    const fresh = proposal({
      profile_hash: "b".repeat(64),
      digest: "e".repeat(64),
      after: {
        rows: [{ words: ["Python"], level: "must" }],
        critical: null,
        talk: [],
        language: "angielski B2",
      },
    });
    post.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: {
            code: "requirement_proposal_stale",
            message: "Profil Championa zmienił się — sprawdź nową propozycję.",
            proposal: fresh,
          },
        },
      },
    });
    const { onOpenChange } = renderDialog();
    await user.click(await screen.findByRole("button", { name: "Zatwierdź" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Profil Championa zmienił się — sprawdź nową propozycję.",
    );
    await waitFor(() =>
      expect(screen.getByTestId("proposal-rows-must")).toHaveTextContent("Python"),
    );
    expect(onOpenChange).not.toHaveBeenCalled();

    post.mockResolvedValueOnce({ data: { job_id: 7, champion_profile: {}, notices: [] } });
    await user.click(screen.getByRole("button", { name: "Zatwierdź" }));
    await waitFor(() =>
      expect(post).toHaveBeenLastCalledWith("/api/jobs/7/requirement-proposal/apply", {
        profile_hash: "b".repeat(64),
        proposal_digest: "e".repeat(64),
      }),
    );
  });

  it("propozycji już nie ma — zdanie zamiast porównania", async () => {
    respond({ proposal: null, can_decide: true });
    renderDialog();
    expect(
      await screen.findByText("Wymagania tej rekrutacji nie wymagają już poprawek."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zatwierdź" })).not.toBeInTheDocument();
  });
});
