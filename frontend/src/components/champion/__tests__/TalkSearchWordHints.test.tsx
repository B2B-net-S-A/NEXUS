import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  };
  return { api: client, default: client };
});

import { TalkSearchWordHints } from "@/components/champion/TalkSearchWordHints";
import type { ExperienceItem } from "@/lib/api";
import {
  addTalkSearchRow,
  talkItemHead,
  talkItemTexts,
  type PhraseReading,
  type RequirementRowForm,
} from "@/lib/requirement-rows";

/** Odczyty jak z `critical-suggestion` na stagingu 27.10.2026. */
const READ: Record<string, Omit<PhraseReading, "text">> = {
  "Alteryx (good/advanced)": {
    kind: "prose",
    keyword: null,
    comment: null,
    talk: "skills",
    talk_text: "Alteryx (good/advanced)",
    suggestions: ["alteryx*", "good/advanced*"],
    needs_decision: true,
  },
  Alteryx: word("keyword", "Alteryx"),
  "Excel — advanced": {
    kind: "prose",
    keyword: null,
    comment: null,
    talk: "skills",
    talk_text: "Excel — advanced",
    suggestions: ["advanced*"],
    needs_decision: true,
  },
  Excel: word("technology", "Excel"),
  GCP: word("technology", "GCP"),
  BigQuery: word("technology", "BigQuery"),
  "Flexible approach to change": {
    kind: "soft",
    keyword: null,
    comment: null,
    talk: "skills",
    talk_text: "Flexible approach to change",
    suggestions: [],
    needs_decision: true,
  },
  "Python (advanced)": {
    ...word("technology", "Python"),
    comment: "advanced",
    talk: "skills",
    talk_text: "Python — advanced",
  },
  "SQL (PostgreSQL, Oracle)": word("technology", "SQL lub PostgreSQL lub Oracle"),
  "Python + SQL": word("keyword", "Python + SQL"),
};

function word(kind: PhraseReading["kind"], keyword: string): Omit<PhraseReading, "text"> {
  return {
    kind,
    keyword,
    comment: null,
    talk: null,
    talk_text: null,
    suggestions: [],
    needs_decision: false,
  };
}

const item = (name: string, level: ExperienceItem["level"] = "must"): ExperienceItem => ({
  name,
  level,
});
const row = (key: string, ...words: string[]): RequirementRowForm => ({
  key,
  words,
  level: "must",
});

// 663525: „Alteryx” tylko na liście do rozmowy, w wierszach go nie ma.
const ROWS_663525 = [row("excel", "Excel"), row("data", "Data handling"), row("rep", "Reporting")];

beforeEach(() => {
  mocks.post.mockReset();
  mocks.get.mockReset();
  mocks.post.mockImplementation((_url: string, body: { rows: string[][] }) =>
    Promise.resolve({
      data: {
        readings: body.rows.map(([text]) => [
          { text, ...(READ[text] ?? READ["Flexible approach to change"]) },
        ]),
        eligible: [],
        suggested: [],
        stats: {},
      },
    }),
  );
  mocks.get.mockResolvedValue({ data: { total: 412 } });
});

function renderHints(items: ExperienceItem[], rows: RequirementRowForm[], onAdd = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TalkSearchWordHints items={items} rows={rows} onAdd={onAdd} />
    </QueryClientProvider>,
  );
  return onAdd;
}

describe("TalkSearchWordHints", () => {
  it("technologia spoza wierszy dostaje „To słowo do szukania?” z liczbą osób", async () => {
    const onAdd = renderHints(
      [
        item("Alteryx (good/advanced)"),
        item("Excel — advanced"),
        item("Flexible approach to change"),
      ],
      ROWS_663525,
    );
    const hint = await screen.findByTestId("talk-search-word-hint");
    expect(hint.textContent).toContain("To słowo do szukania?");
    expect(hint.textContent).toContain("„Alteryx”");
    await waitFor(() => expect(hint.textContent).toContain("W bazie: 412 osób"));
    // Excel jest w wierszach, umiejętność miękka nie jest słowem — bez podpowiedzi.
    expect(screen.getAllByTestId("talk-search-word-hint")).toHaveLength(1);
    // Pozycja z poziomem zostaje na liście do rozmowy.
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do słów do szukania" }));
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ words: ["Alteryx"], keepItem: true }),
    );
    // Odczyt to ten sam endpoint co edytor wierszy.
    expect(mocks.post).toHaveBeenCalledWith(
      "/api/job-intake/critical-suggestion",
      expect.objectContaining({ rows: expect.arrayContaining([["Alteryx"]]) }),
      expect.anything(),
    );
  });

  it("ta sama technologia w wierszach — brak podpowiedzi", async () => {
    renderHints(
      [
        item("Alteryx (good/advanced)"),
        item("GCP"),
        item("BigQuery"),
        // Kontrola: Pythona w wierszach nie ma — jego podpowiedź dowodzi, że odczyt doszedł.
        item("Python (advanced)"),
      ],
      [...ROWS_663525, row("alt", "Alteryx"), row("gcp", "Google Cloud", "GCP"), row("bq", "BigQuery")],
    );
    const hints = await screen.findAllByTestId("talk-search-word-hint");
    expect(hints).toHaveLength(1);
    expect(hints[0].textContent).toContain("„Python”");
  });

  it("słowo, którego każdy człon jest już wierszem, nie dostaje podpowiedzi (789160)", async () => {
    renderHints(
      [item("Python + SQL"), item("GCP")],
      [row("bq", "BigQuery"), row("py", "Python"), row("sql", "SQL")],
    );
    const hints = await screen.findAllByTestId("talk-search-word-hint");
    expect(hints).toHaveLength(1);
    expect(hints[0].textContent).toContain("„GCP”");
  });

  it("sama technologia bez komentarza przenosi się do słów", async () => {
    const onAdd = renderHints([item("GCP")], [row("bq", "BigQuery")]);
    fireEvent.click(await screen.findByRole("button", { name: "Przenieś do słów do szukania" }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ words: ["GCP"], keepItem: false }));
  });
});

describe("pozycja do rozmowy jako słowo do szukania", () => {
  it("nazwa bez komentarza na końcu", () => {
    expect(talkItemHead("Alteryx (good/advanced)")).toBe("Alteryx");
    expect(talkItemHead("Excel — advanced")).toBe("Excel");
    expect(talkItemHead("Cloud Composer / Apache Airflow")).toBe("Cloud Composer / Apache Airflow");
    expect(talkItemTexts([item("GCP"), item("Excel — advanced")])).toEqual([
      "GCP",
      "Excel — advanced",
      "Excel",
    ]);
  });

  it("nowy wiersz: warianty z „lub”, poziom jak pozycja", () => {
    const rows = addTalkSearchRow([row("x", "Excel")], {
      item: item("SQL (PostgreSQL, Oracle)", "nice"),
      words: ["SQL", "PostgreSQL", "Oracle"],
      keepItem: false,
    });
    expect(rows.at(-1)).toMatchObject({ words: ["SQL", "PostgreSQL", "Oracle"], level: "nice" });
    const must = addTalkSearchRow([row("x", "Excel")], {
      item: item("Alteryx (good/advanced)"),
      words: ["Alteryx"],
      keepItem: true,
    });
    expect(must.at(-1)).toMatchObject({ words: ["Alteryx"], level: "must" });
  });
});
