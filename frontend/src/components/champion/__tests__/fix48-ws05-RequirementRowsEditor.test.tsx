/**
 * Audyt 48 h (13.10.2026), pkt 19: „Do rozmowy” przy zdaniu z kropką na końcu
 * albo dłuższym niż 100 znaków nic nie zmieniało, a „Zapisz” zostawało
 * zablokowane — serwer czyta słowo po swoim sicie, edytor porównywał dosłownie.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  };
  return { api: client, default: client };
});

import { RequirementRowsEditor } from "@/components/champion/RequirementRowsEditor";
import type {
  PhraseReading,
  RequirementRowForm,
  RowCriticalInfo,
  RowCriticalState,
} from "@/lib/requirement-rows";
import { useAuthStore } from "@/store/auth";

const LONG =
  "Minimum 5 lat doświadczenia komercyjnego w projektowaniu i wdrażaniu hurtowni danych w sektorze bankowym oraz ubezpieczeniowym";
const LONG_CUT =
  "Minimum 5 lat doświadczenia komercyjnego w projektowaniu i wdrażaniu hurtowni danych w sektorze";

const prose = (text: string): PhraseReading => ({
  text,
  kind: "prose",
  keyword: null,
  comment: null,
  talk: "skills",
  talk_text: text,
  suggestions: ["przetarg*"],
  needs_decision: true,
});

function renderEditor(rows: RequirementRowForm[], info: Record<string, RowCriticalInfo>) {
  const onRowsChange = vi.fn();
  const onMoveToTalk = vi.fn();
  const critical: RowCriticalState = {
    info,
    isLoading: false,
    isError: false,
    retry: () => undefined,
  };
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RequirementRowsEditor
        rows={rows}
        onRowsChange={onRowsChange}
        noCritical={false}
        onNoCriticalChange={vi.fn()}
        exclude={[]}
        onExcludeChange={vi.fn()}
        critical={critical}
        countEnabled={false}
        onMoveToTalk={onMoveToTalk}
      />
    </QueryClientProvider>,
  );
  return { onRowsChange, onMoveToTalk };
}

const clickToTalk = () =>
  fireEvent.click(
    within(screen.getByTestId("requirement-row-decision")).getByRole("button", {
      name: "Do rozmowy",
    }),
  );

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ data: {} });
  mocks.post.mockResolvedValue({ data: {} });
  useAuthStore.setState({ user: null });
});

describe("RequirementRowsEditor — „Do rozmowy” trafia w słowo wiersza", () => {
  it("zdanie z kropką na końcu znika z wierszy", () => {
    const { onRowsChange, onMoveToTalk } = renderEditor(
      [
        { key: "java", words: ["Java"], level: "must" },
        { key: "tender", words: ["Doświadczenie w przetargach."], level: "must" },
      ],
      {
        java: { label: "Java", eligible: true, suggested: false },
        tender: {
          label: "Doświadczenie w przetargach.",
          eligible: false,
          suggested: false,
          readings: [prose("Doświadczenie w przetargach")],
        },
      },
    );
    clickToTalk();
    const rows = onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[];
    expect(rows.map((r) => r.key)).toEqual(["java"]);
    expect(onMoveToTalk).toHaveBeenCalledWith({
      name: "Doświadczenie w przetargach",
      kind: "skills",
      level: "must",
    });
  });

  it("zdanie dłuższe niż 100 znaków znika z wierszy i idzie do rozmowy w całości", () => {
    const { onRowsChange, onMoveToTalk } = renderEditor(
      [
        { key: "java", words: ["Java"], level: "must" },
        { key: "dwh", words: [LONG], level: "must" },
      ],
      {
        java: { label: "Java", eligible: true, suggested: false },
        dwh: {
          label: LONG_CUT,
          eligible: false,
          suggested: false,
          readings: [prose(LONG_CUT)],
        },
      },
    );
    clickToTalk();
    const rows = onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[];
    expect(rows.map((r) => r.key)).toEqual(["java"]);
    expect(onMoveToTalk).toHaveBeenCalledWith({ name: LONG, kind: "skills", level: "must" });
  });
});
