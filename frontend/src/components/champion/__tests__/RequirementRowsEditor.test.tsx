import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  /** Liczby osób w bazie podane wprost (`null` = prawdziwy hook). */
  counts: null as null | {
    perRow: Record<string, number | null>;
    required: number | null | undefined;
    critical: number | null | undefined;
    failed: boolean;
  },
}));

vi.mock("@/lib/requirement-rows-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/requirement-rows-api")>();
  return {
    ...actual,
    useRowCounts: (...args: Parameters<typeof actual.useRowCounts>) =>
      mocks.counts ?? actual.useRowCounts(...args),
  };
});

// Edytor w trybie bez liczników (`countEnabled={false}`) nie pyta serwera —
// podpowiedzi słów w `ChipField` ruszają dopiero po wpisaniu tekstu.
vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  };
  return { api: client, default: client };
});

import {
  OUTSIDE_DICTIONARY_NOTE,
  RequirementRowsEditor,
  type RequirementRowsEditorProps,
} from "@/components/champion/RequirementRowsEditor";
import { clearSearchMemory, pushRecentSearch } from "@/lib/search-memory";
import { useAuthStore } from "@/store/auth";
import type {
  RequirementLevel,
  RequirementRowForm,
  RowCriticalInfo,
  RowCriticalState,
} from "@/lib/requirement-rows";

const ROWS: RequirementRowForm[] = [
  { key: "java", words: ["Java"], level: "must" },
  { key: "kafka", words: ["Kafka", "RabbitMQ"], level: "must" },
  { key: "pay", words: ["płatności"], level: "must" },
  { key: "k8s", words: ["Kubernetes"], level: "nice" },
];

const INFO: Record<string, RowCriticalInfo> = {
  java: { label: "Java", eligible: true, suggested: true, stat: { rate: 0.96, jobs: 41 } },
  kafka: { label: "Kafka lub RabbitMQ", eligible: true, suggested: false },
  pay: { label: "płatności", eligible: false, suggested: false },
};

const known = (info: RowCriticalState["info"] = INFO): RowCriticalState => ({
  info,
  isLoading: false,
  isError: false,
  retry: () => undefined,
});

const withLevels = (levels: Record<string, RequirementLevel>): RequirementRowForm[] =>
  ROWS.map((row) => ({ ...row, level: levels[row.key] ?? row.level }));

function renderEditor(props: Partial<RequirementRowsEditorProps> = {}) {
  const onRowsChange = vi.fn();
  const onNoCriticalChange = vi.fn();
  const onExcludeChange = vi.fn();
  const view = render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RequirementRowsEditor
        rows={ROWS}
        onRowsChange={onRowsChange}
        noCritical={false}
        onNoCriticalChange={onNoCriticalChange}
        exclude={[]}
        onExcludeChange={onExcludeChange}
        critical={known()}
        countEnabled={false}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onRowsChange, onNoCriticalChange, onExcludeChange, unmount: view.unmount };
}

/** Renderuje edytor, czyta jedną rzecz z ekranu i sprząta — kilka stanów w jednym teście. */
function readFromEditor<T>(props: Partial<RequirementRowsEditorProps>, read: () => T): T {
  const { unmount } = renderEditor(props);
  const value = read();
  unmount();
  return value;
}

/** Opcja poziomu w wierszu rozpoznawanym po pierwszym słowie. */
const levelOption = (head: string, level: "Krytyczne" | "Musi mieć" | "Mile widziane") =>
  within(screen.getByRole("radiogroup", { name: `Poziom wymagania: ${head}` })).getByRole(
    "radio",
    { name: level },
  );

/** Poziomy z ostatniego wywołania `onRowsChange`, po kluczu wiersza. */
const lastLevels = (onRowsChange: ReturnType<typeof vi.fn>) =>
  Object.fromEntries(
    (onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[]).map((r) => [r.key, r.level]),
  );

beforeEach(() => {
  vi.clearAllMocks();
  mocks.counts = null;
  mocks.get.mockResolvedValue({ data: {} });
  mocks.post.mockResolvedValue({ data: {} });
  clearSearchMemory();
  useAuthStore.setState({ user: null });
});

describe("RequirementRowsEditor — wiersze i poziomy", () => {
  it("pokazuje wiersz na wymaganie z zaznaczonym poziomem", () => {
    renderEditor();
    expect(
      screen.getByRole("group", { name: "Wymagania — słowa kluczowe" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("radiogroup")).toHaveLength(4);
    expect(levelOption("Java", "Musi mieć")).toBeChecked();
    expect(levelOption("Kubernetes", "Mile widziane")).toBeChecked();
    // Warianty stoją w tym samym wierszu, połączone słowem „lub”.
    expect(screen.getByText("RabbitMQ")).toBeInTheDocument();
    expect(screen.getByText("lub")).toBeInTheDocument();
  });

  it("zmiana poziomu oddaje nową listę i nie rusza „Brak krytycznych”", () => {
    const { onRowsChange, onNoCriticalChange } = renderEditor();
    fireEvent.click(levelOption("Java", "Mile widziane"));
    expect(lastLevels(onRowsChange)).toEqual({
      java: "nice",
      kafka: "must",
      pay: "must",
      k8s: "nice",
    });
    fireEvent.click(levelOption("Kafka", "Krytyczne"));
    expect(lastLevels(onRowsChange)).toMatchObject({ java: "must", kafka: "critical" });
    expect(onNoCriticalChange).not.toHaveBeenCalled();
  });

  it("wariant dopisuje się świadomie: wypełniony wiersz nie ma pola, dopiero „+ lub” je otwiera", () => {
    const { onRowsChange } = renderEditor();
    // Bez pola w wypełnionym wierszu kolejne słowo nie stanie się po cichu
    // wariantem — a wiersz „A lub B” spełnia kandydat z jednym z nich.
    expect(screen.queryByLabelText("Wymaganie 1 — słowo albo wariant")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wariant do wymagania 1" }));
    const input = screen.getByLabelText("Wymaganie 1 — słowo albo wariant");
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "JVM" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const rows = onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[];
    expect(rows[0]).toEqual({ key: "java", words: ["Java", "JVM"], level: "must" });
    expect(rows.slice(1)).toEqual(ROWS.slice(1));
  });

  it("„Dodaj słowo kluczowe” dokłada pusty wiersz obowiązkowy, kosz usuwa wiersz", () => {
    const { onRowsChange } = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj słowo kluczowe" }));
    const added = onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[];
    expect(added).toHaveLength(5);
    expect(added.at(-1)).toMatchObject({ words: [], level: "must" });

    fireEvent.click(screen.getByRole("button", { name: "Usuń wymaganie: Kafka" }));
    expect(
      (onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[]).map((r) => r.key),
    ).toEqual(["java", "pay", "k8s"]);
  });

  it("pusta lista pokazuje jeden pusty wiersz, którego nie da się usunąć", () => {
    renderEditor({ rows: [], critical: known({}) });
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Usuń wymaganie: wiersz 1" })).toBeDisabled();
    // Poziom da się wybrać także przed wpisaniem słowa — klik zaraz po
    // wpisaniu trafiał w wyłączony przycisk (zgłoszenie 09.10.2026).
    expect(levelOption("wiersz 1", "Krytyczne")).toBeEnabled();
  });

  it("„Wyklucz” oddaje listę słów osobnym kanałem", () => {
    const { onExcludeChange, onRowsChange } = renderEditor({ exclude: ["junior"] });
    const input = screen.getByLabelText("Wyklucz — żadne z tych słów");
    fireEvent.change(input, { target: { value: "stażysta" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onExcludeChange).toHaveBeenCalledWith(["junior", "stażysta"]);
    expect(onRowsChange).not.toHaveBeenCalled();
  });

  it("bez liczników nie pyta serwera i nie pokazuje liczby osób", () => {
    renderEditor({ rows: withLevels({ java: "critical" }) });
    expect(screen.queryByText(/Wszystkie „musi mieć” naraz/)).toBeNull();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});

describe("RequirementRowsEditor — kto może być krytyczny", () => {
  it("każdy wiersz da się oznaczyć — decyduje Delivery Lead, nie słownik (09.10.2026)", () => {
    const { onRowsChange } = renderEditor();
    const option = levelOption("płatności", "Krytyczne");
    expect(option).toBeEnabled();
    expect(option).not.toHaveAttribute("title");
    expect(screen.queryByTestId("requirement-row-critical-blocked")).toBeNull();
    fireEvent.click(option);
    expect(onRowsChange).toHaveBeenCalledWith(withLevels({ pay: "critical" }));
  });

  it("krytyczny wiersz spoza słownika mówi, jak działa bramka, i daje się odznaczyć", () => {
    const { onRowsChange } = renderEditor({ rows: withLevels({ pay: "critical" }) });
    expect(screen.getByTestId("requirement-row-outside-dictionary")).toHaveTextContent(
      OUTSIDE_DICTIONARY_NOTE,
    );
    fireEvent.click(levelOption("płatności", "Musi mieć"));
    expect(onRowsChange).toHaveBeenCalledWith(withLevels({ pay: "must" }));
  });

  it("„Krytyczne” nie czeka na serwer ani na jego awarię", () => {
    const pending = renderEditor({ critical: { ...known(null), isLoading: true } });
    expect(levelOption("Java", "Krytyczne")).toBeEnabled();
    fireEvent.click(levelOption("Java", "Krytyczne"));
    expect(pending.onRowsChange).toHaveBeenCalledWith(withLevels({ java: "critical" }));
    pending.unmount();

    renderEditor({ critical: { info: null, isLoading: false, isError: true, retry: vi.fn() } });
    expect(levelOption("Java", "Krytyczne")).toBeEnabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("trzeci krytyczny da się oznaczyć (limit 3 od 08.10.2026)", () => {
    const { onRowsChange } = renderEditor({
      rows: withLevels({ java: "critical", kafka: "critical" }),
    });
    const third = levelOption("płatności", "Krytyczne");
    expect(third).toBeEnabled();
    fireEvent.click(third);
    expect(onRowsChange).toHaveBeenCalledWith(
      withLevels({ java: "critical", kafka: "critical", pay: "critical" }),
    );
  });

  it("czwarty krytyczny jest nieaktywny — najwyżej trzy, a odznaczenie działa", () => {
    const { onRowsChange } = renderEditor({
      rows: withLevels({ java: "critical", kafka: "critical", pay: "critical" }),
    });
    const fourth = levelOption("Kubernetes", "Krytyczne");
    expect(fourth).toBeDisabled();
    expect(fourth).toHaveAttribute(
      "title",
      "Najwyżej 3 krytyczne — zdejmij jedno, żeby dodać kolejne.",
    );
    expect(levelOption("Java", "Krytyczne")).toBeChecked();
    fireEvent.click(levelOption("Java", "Musi mieć"));
    expect(onRowsChange).toHaveBeenCalledWith(
      withLevels({ java: "must", kafka: "critical", pay: "critical" }),
    );
  });
});

/** Edytor z rodzicem, który trzyma stan — tak jak `/jobs/new`. */
function StatefulEditor({ initial = [] }: { initial?: RequirementRowForm[] }) {
  const [rows, setRows] = useState<RequirementRowForm[]>(initial);
  const [noCritical, setNoCritical] = useState(false);
  const [exclude, setExclude] = useState<string[]>([]);
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RequirementRowsEditor
        rows={rows}
        onRowsChange={setRows}
        noCritical={noCritical}
        onNoCriticalChange={setNoCritical}
        exclude={exclude}
        onExcludeChange={setExclude}
        critical={{ info: null, isLoading: true, isError: false, retry: () => undefined }}
        countEnabled={false}
      />
    </QueryClientProvider>
  );
}

const rowInput = (n: number) => screen.getByLabelText(`Wymaganie ${n} — słowo albo wariant`);

function typeWord(input: HTMLElement, text: string, key = "Enter") {
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key });
}

describe("RequirementRowsEditor — wpisywanie z klawiatury (zgłoszenie 09.10.2026)", () => {
  it("Enter po słowie przenosi kursor do następnego wymagania — dwa must-have to dwa wiersze", () => {
    render(<StatefulEditor />);
    typeWord(rowInput(1), "Java");
    // Kursor stoi w nowym, pustym wierszu — kolejne słowo nie jest wariantem „lub”.
    expect(rowInput(2)).toHaveFocus();
    typeWord(rowInput(2), "Spring Boot");
    expect(rowInput(3)).toHaveFocus();
    expect(levelOption("Java", "Musi mieć")).toBeChecked();
    expect(levelOption("Spring Boot", "Musi mieć")).toBeChecked();
    expect(screen.queryByText("lub")).toBeNull();
  });

  // Zgłoszenie 10.10.2026: „Java”, przecinek, „Spring” dawało JEDNO wymaganie
  // „Java lub Spring” — spełnia je kandydat z samą Javą, więc lista must-have
  // po cichu się rozluźniała.
  it("przecinek kończy wymaganie tak jak Enter — „Java, Spring,” to dwa wiersze", () => {
    render(<StatefulEditor />);
    typeWord(rowInput(1), "Java", ",");
    expect(rowInput(2)).toHaveFocus();
    typeWord(rowInput(2), "Spring", ",");
    expect(rowInput(3)).toHaveFocus();
    expect(levelOption("Java", "Musi mieć")).toBeChecked();
    expect(levelOption("Spring", "Musi mieć")).toBeChecked();
    expect(screen.queryByText("lub")).toBeNull();
    expect(screen.getAllByRole("radiogroup")).toHaveLength(3);
  });

  it("lista po przecinkach wpisana naraz to osobne wymagania — „Kafka, Redis, AWS” to trzy wiersze", () => {
    render(<StatefulEditor />);
    typeWord(rowInput(1), "Kafka, Redis, AWS");
    for (const head of ["Kafka", "Redis", "AWS"]) {
      expect(levelOption(head, "Musi mieć")).toBeChecked();
    }
    expect(screen.queryByText("lub")).toBeNull();
    // Trzy wymagania i pusty wiersz z kursorem na następne.
    expect(screen.getAllByRole("radiogroup")).toHaveLength(4);
    expect(rowInput(4)).toHaveFocus();
  });

  it("średnik też kończy wymaganie", () => {
    render(<StatefulEditor />);
    typeWord(rowInput(1), "Kafka", ";");
    expect(levelOption("Kafka", "Musi mieć")).toBeChecked();
    expect(rowInput(2)).toHaveFocus();
  });

  it("wklejona lista rozkłada się na wiersze, przecinek w nawiasie nie dzieli", () => {
    render(<StatefulEditor />);
    fireEvent.paste(rowInput(1), {
      clipboardData: { getData: () => "Java\nSpring (Boot, Data)\nSQL" },
    });
    for (const head of ["Java", "Spring (Boot, Data)", "SQL"]) {
      expect(levelOption(head, "Musi mieć")).toBeChecked();
    }
    expect(screen.queryByText("lub")).toBeNull();
    expect(rowInput(4)).toHaveFocus();
  });

  it("przecinek wpisany w otwartym nawiasie nie kończy wymagania — „Spring (Boot, Data)” to jeden wiersz", () => {
    render(<StatefulEditor />);
    const input = rowInput(1);
    // W trakcie pisania nawias nie jest jeszcze zamknięty: wpis czeka na „)”.
    typeWord(input, "Spring (Boot", ",");
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1);
    expect(input).toHaveValue("Spring (Boot");
    typeWord(input, "Spring (Boot, Data)");
    expect(levelOption("Spring (Boot, Data)", "Musi mieć")).toBeChecked();
    expect(screen.getAllByRole("radiogroup")).toHaveLength(2);
  });

  it("„Kafka / RabbitMQ” to jedno wymaganie z dwoma wariantami, „CI/CD” to jedno słowo", () => {
    render(<StatefulEditor />);
    typeWord(rowInput(1), "Kafka / RabbitMQ");
    expect(screen.getByText("RabbitMQ")).toBeInTheDocument();
    expect(screen.getByText("lub")).toBeInTheDocument();
    expect(levelOption("Kafka", "Musi mieć")).toBeChecked();
    typeWord(rowInput(2), "CI/CD");
    expect(levelOption("CI/CD", "Musi mieć")).toBeChecked();
    expect(screen.getAllByText("lub")).toHaveLength(1);
  });

  it("w polu wariantu średnik działa jak przecinek — także w tekście zatwierdzonym Enterem", () => {
    render(<StatefulEditor initial={[{ key: "a", words: ["Kafka"], level: "must" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wariant do wymagania 1" }));
    typeWord(rowInput(1), "RabbitMQ", ";");
    expect(screen.getByText("RabbitMQ")).toBeInTheDocument();
    expect(rowInput(1)).toHaveValue("");
    typeWord(rowInput(1), "Pulsar; NATS");
    expect(screen.getByText("Pulsar")).toBeInTheDocument();
    expect(screen.getByText("NATS")).toBeInTheDocument();
    // Wszystko zostało wariantami jednego wymagania.
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1);
    expect(screen.getAllByText("lub")).toHaveLength(3);
  });

  it("„+ lub” dopisuje warianty w środku listy i nie wstawia pustego wiersza", () => {
    render(
      <StatefulEditor
        initial={[
          { key: "a", words: ["Kafka"], level: "must" },
          { key: "b", words: ["Java"], level: "must" },
        ]}
      />,
    );
    const addVariant = () => screen.getByRole("button", { name: "Dodaj wariant do wymagania 1" });
    fireEvent.click(addVariant());
    // W polu wariantu Enter i przecinek dopisują kolejne warianty tego wiersza.
    typeWord(rowInput(1), "RabbitMQ");
    typeWord(rowInput(1), "Pulsar", ",");
    expect(screen.getAllByRole("radiogroup")).toHaveLength(2);
    expect(screen.getByText("RabbitMQ")).toBeInTheDocument();
    expect(screen.getByText("Pulsar")).toBeInTheDocument();
    expect(screen.getAllByText("lub")).toHaveLength(2);
    // Pusty Enter zamyka pole wariantu.
    fireEvent.keyDown(rowInput(1), { key: "Enter" });
    expect(screen.queryByLabelText("Wymaganie 1 — słowo albo wariant")).toBeNull();
    expect(addVariant()).toHaveFocus();
    // Esc w pustym polu też je zamyka.
    fireEvent.click(addVariant());
    fireEvent.keyDown(rowInput(1), { key: "Escape" });
    expect(screen.queryByLabelText("Wymaganie 1 — słowo albo wariant")).toBeNull();
    expect(screen.getAllByRole("radiogroup")).toHaveLength(2);
  });

  it("wyjście z pola zapisuje słowo, ale nie dokłada pustego wiersza", () => {
    render(<StatefulEditor />);
    fireEvent.focus(rowInput(1));
    fireEvent.change(rowInput(1), { target: { value: "Java" } });
    fireEvent.blur(rowInput(1));
    expect(levelOption("Java", "Musi mieć")).toBeChecked();
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1);
  });

  it("słowo, które już jest na liście, nie tworzy drugiego wiersza — edytor mówi dlaczego", () => {
    render(<StatefulEditor initial={[{ key: "a", words: ["Java"], level: "must" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Dodaj słowo kluczowe" }));
    typeWord(rowInput(2), "java, Spring");
    expect(screen.getByTestId("requirement-entry-note")).toHaveTextContent("Już na liście: java.");
    // Java, Spring i pusty wiersz z kursorem.
    expect(screen.getAllByRole("radiogroup")).toHaveLength(3);
    expect(levelOption("Spring", "Musi mieć")).toBeChecked();
    // Kolejny wpis bez uwag zdejmuje notkę.
    typeWord(rowInput(3), "SQL");
    expect(screen.queryByTestId("requirement-entry-note")).toBeNull();
  });

  it("ponad limit 30 wymagań: reszta nie znika po cichu", () => {
    const initial: RequirementRowForm[] = [
      ...Array.from({ length: 10 }, (_, i) => ({
        key: `m${i}`,
        words: [`Must${i}`],
        level: "must" as const,
      })),
      ...Array.from({ length: 19 }, (_, i) => ({
        key: `n${i}`,
        words: [`Nice${i}`],
        level: "nice" as const,
      })),
      { key: "e", words: [], level: "nice" },
    ];
    render(<StatefulEditor initial={initial} />);
    typeWord(rowInput(30), "Alfa, Beta / Gamma");
    expect(levelOption("Alfa", "Mile widziane")).toBeChecked();
    expect(screen.getByTestId("requirement-entry-note")).toHaveTextContent(
      "Nie zmieściło się: Beta lub Gamma — lista ma najwyżej 30 wymagań.",
    );
    expect(screen.getAllByRole("radiogroup")).toHaveLength(30);
    // Nie ma miejsca na pusty wiersz — fokus zostaje przy wpisanym wymaganiu.
    expect(screen.getByRole("button", { name: "Dodaj wariant do wymagania 30" })).toHaveFocus();
  });

  it("podpowiedź wybrana strzałką w pustym wierszu to całe wymaganie — kursor idzie dalej", () => {
    useAuthStore.setState({ user: { id: 7 } as never });
    pushRecentSearch(7, {
      kind: "list",
      jobId: null,
      label: "kotlin",
      query: "q_any=kotlin",
      keywords: ["kotlin"],
      total: null,
    });
    render(<StatefulEditor />);
    fireEvent.focus(rowInput(1));
    fireEvent.change(rowInput(1), { target: { value: "kot" } });
    fireEvent.keyDown(rowInput(1), { key: "ArrowDown" });
    fireEvent.keyDown(rowInput(1), { key: "Enter" });
    expect(levelOption("kotlin", "Musi mieć")).toBeChecked();
    expect(rowInput(2)).toHaveFocus();
  });

  it("„Krytyczne” działa zaraz po wpisaniu słowa, bez odpowiedzi serwera", () => {
    render(<StatefulEditor />);
    typeWord(rowInput(1), "bankowość");
    const option = levelOption("bankowość", "Krytyczne");
    expect(option).toBeEnabled();
    fireEvent.click(option);
    expect(levelOption("bankowość", "Krytyczne")).toBeChecked();
  });

  it("pole w wierszu nie otwiera listy „Ostatnio używane” na pustym polu", () => {
    useAuthStore.setState({ user: { id: 7 } as never });
    pushRecentSearch(7, {
      kind: "list",
      jobId: null,
      label: "java",
      query: "q_any=java",
      keywords: ["java", "kotlin"],
      total: null,
    });
    render(<StatefulEditor />);
    fireEvent.focus(rowInput(1));
    expect(screen.queryByRole("listbox")).toBeNull();
    typeWord(rowInput(1), "Java");
    // Po Enterze lista też się nie otwiera — nie zasłania „Dodaj słowo kluczowe”.
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj słowo kluczowe" }));
    expect(screen.queryByText("kotlin")).toBeNull();
  });
});

describe("RequirementRowsEditor — „Brak krytycznych” i podpowiedź z historii", () => {
  const noCriticalBox = () => screen.getByRole("checkbox", { name: "Brak krytycznych" });

  it("„Brak krytycznych” zdejmuje oznaczone wiersze i zapisuje decyzję", () => {
    const { onRowsChange, onNoCriticalChange } = renderEditor({
      rows: withLevels({ java: "critical", kafka: "critical" }),
    });
    expect(noCriticalBox()).not.toBeChecked();
    fireEvent.click(noCriticalBox());
    expect(lastLevels(onRowsChange)).toEqual({
      java: "must",
      kafka: "must",
      pay: "must",
      k8s: "nice",
    });
    expect(onNoCriticalChange).toHaveBeenCalledWith(true);
  });

  it("bez oznaczonych wierszy „Brak krytycznych” zmienia tylko decyzję", () => {
    const { onRowsChange, onNoCriticalChange } = renderEditor();
    fireEvent.click(noCriticalBox());
    expect(onNoCriticalChange).toHaveBeenCalledWith(true);
    expect(onRowsChange).not.toHaveBeenCalled();
  });

  it("zaznaczone „Brak krytycznych” da się odznaczyć", () => {
    const { onNoCriticalChange, onRowsChange } = renderEditor({ noCritical: true });
    expect(noCriticalBox()).toBeChecked();
    fireEvent.click(noCriticalBox());
    expect(onNoCriticalChange).toHaveBeenCalledWith(false);
    expect(onRowsChange).not.toHaveBeenCalled();
  });

  it("wybór „Krytyczne” przy włączonym „Brak krytycznych” cofa tę decyzję", () => {
    const { onRowsChange, onNoCriticalChange } = renderEditor({ noCritical: true });
    fireEvent.click(levelOption("Java", "Krytyczne"));
    expect(lastLevels(onRowsChange)).toMatchObject({ java: "critical", kafka: "must" });
    expect(onNoCriticalChange).toHaveBeenCalledWith(false);
  });

  it("wiersz krytyczny wygrywa z flagą: pole nie jest zaznaczone", () => {
    renderEditor({ rows: withLevels({ java: "critical" }), noCritical: true });
    expect(noCriticalBox()).not.toBeChecked();
  });

  it("przycisk podpowiedzi oznacza wiersze z historii", () => {
    const { onRowsChange } = renderEditor();
    expect(
      screen.getByText("Podpowiedź z historii: 96% wysłanych ją miało."),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Oznacz krytyczne z historii: Java" }),
    );
    expect(lastLevels(onRowsChange)).toEqual({
      java: "critical",
      kafka: "must",
      pay: "must",
      k8s: "nice",
    });
  });

  it("podpowiedź wymienia najwyżej dwa wiersze, które wolno oznaczyć", () => {
    const info = {
      java: { ...INFO.java },
      kafka: { ...INFO.kafka, suggested: true },
      // Podpowiedź dla słowa spoza słownika się nie liczy.
      pay: { ...INFO.pay, suggested: true },
    };
    const { onRowsChange } = renderEditor({ critical: known(info) });
    fireEvent.click(
      screen.getByRole("button", { name: "Oznacz krytyczne z historii: Java, Kafka" }),
    );
    expect(lastLevels(onRowsChange)).toMatchObject({
      java: "critical",
      kafka: "critical",
      pay: "must",
    });
  });

  it("po decyzji przycisk podpowiedzi znika", () => {
    const suggestion = () => screen.queryByRole("button", { name: /Oznacz krytyczne z historii/ });
    expect(readFromEditor({ rows: withLevels({ kafka: "critical" }) }, suggestion)).toBeNull();
    expect(readFromEditor({ noCritical: true }, suggestion)).toBeNull();
    expect(readFromEditor({ critical: known(null) }, suggestion)).toBeNull();
    expect(readFromEditor({}, suggestion)).not.toBeNull();
  });
});

describe("RequirementRowsEditor — zdanie pod listą", () => {
  const summary = (props: Partial<RequirementRowsEditorProps>) =>
    readFromEditor(props, () =>
      [
        "Krytyczne: Java, Kafka — propozycje AI ukrywają osoby, które ich nie mają.",
        "Brak krytycznych — propozycje AI nie ukrywają nikogo, wszystkie wymagania dają punkty.",
        "Nie zdecydowano — oznacz najwyżej 3 wiersze jako krytyczne albo wybierz „Brak krytycznych”.",
        "Po tych słowach szukamy w bazie. Krytyczne ukrywają w propozycjach AI osoby, które ich nie mają.",
        "Dodaj co najmniej jedno słowo kluczowe — bez niego rekrutacja nie trafi do searchu.",
      ].filter((sentence) => screen.queryByText(sentence) != null),
    );

  it("trzy stany decyzji o krytycznych", () => {
    expect(summary({ rows: withLevels({ java: "critical", kafka: "critical" }) })).toEqual([
      "Krytyczne: Java, Kafka — propozycje AI ukrywają osoby, które ich nie mają.",
    ]);
    expect(summary({ noCritical: true })).toEqual([
      "Brak krytycznych — propozycje AI nie ukrywają nikogo, wszystkie wymagania dają punkty.",
    ]);
    expect(summary({})).toEqual([
      "Nie zdecydowano — oznacz najwyżej 3 wiersze jako krytyczne albo wybierz „Brak krytycznych”.",
    ]);
  });

  it("bez wymagań obowiązkowych: objaśnienie, a przy braku blokującym search — wezwanie", () => {
    expect(summary({ rows: [], critical: known({}) })).toEqual([
      "Po tych słowach szukamy w bazie. Krytyczne ukrywają w propozycjach AI osoby, które ich nie mają.",
    ]);
    expect(summary({ rows: [], critical: known({}), invalid: true })).toEqual([
      "Dodaj co najmniej jedno słowo kluczowe — bez niego rekrutacja nie trafi do searchu.",
    ]);
  });
});

// Audyt 06.10.2026: nadmiar „musi mieć” (N3), podpowiedzi przy liczbie osób
// (N8) i jednoliterowe technologie („C”, „R”) w wierszach (P4).
describe("RequirementRowsEditor — audyt 06.10.2026", () => {
  const manyRequired = (count: number): RequirementRowForm[] =>
    Array.from({ length: count }, (_, i) => ({
      key: `m${i}`,
      words: [`Słowo${i}`],
      level: "must" as const,
    }));

  it("ponad 10 „musi mieć”: zdanie o zapisie jako „mile widziane”, bez blokady", () => {
    renderEditor({ rows: manyRequired(11), critical: known({}) });
    expect(
      screen.getByText("Ponad 10 wymagań „musi mieć” — kolejne zapiszą się jako „mile widziane”."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dodaj słowo kluczowe" })).toBeEnabled();
  });

  it("dokładnie 10 „musi mieć” — bez zdania, a „mile widziane” może awansować", () => {
    const rows = [
      ...manyRequired(10),
      { key: "n", words: ["Docker"], level: "nice" as const },
    ];
    const { onRowsChange } = renderEditor({ rows, critical: known({}) });
    expect(screen.queryByText(/Ponad 10 wymagań/)).toBeNull();
    const must = levelOption("Docker", "Musi mieć");
    expect(must).toBeEnabled();
    fireEvent.click(must);
    expect(lastLevels(onRowsChange).n).toBe("must");
  });

  it("liczba osób: słowo bardzo ogólne i słowo, którego nikt nie ma — tylko podpowiedź", () => {
    mocks.counts = {
      perRow: { java: 22_000, kafka: 0, pay: 120 },
      required: 10,
      critical: undefined,
      failed: false,
    };
    renderEditor({ countEnabled: true });
    expect(
      screen.getByText("Słowo bardzo ogólne — zawęź (np. dodaj technologię)."),
    ).toBeInTheDocument();
    // Zero osób to nie literówka, tylko słowo, którym ludzie tego nie opisują (27.10.2026).
    expect(screen.getByTestId("requirement-row-rare")).toHaveTextContent(
      "„Kafka lub RabbitMQ” — nikt w bazie.",
    );
    // Jedna podpowiedź na wiersz z problemem — „płatności” (120) jej nie ma.
    expect(screen.getAllByText(/Słowo bardzo ogólne|nikt w bazie/)).toHaveLength(2);
  });

  it("rzadkie „musi mieć”: do rozmowy, zostaw, a przy zerze razem — które zawężają", () => {
    mocks.counts = {
      perRow: { java: 9_000, kafka: 7, pay: 0 },
      required: 0,
      critical: undefined,
      failed: false,
    };
    const onMoveToTalk = vi.fn();
    const { onRowsChange } = renderEditor({ countEnabled: true, onMoveToTalk });
    expect(screen.getByTestId("requirement-rows-narrowest")).toHaveTextContent(
      "Najbardziej zawężają: „płatności” (0), „Kafka” (7).",
    );
    const [kafkaNote] = screen
      .getAllByTestId("requirement-row-rare")
      .filter((note) => note.textContent?.includes("Kafka"));
    expect(kafkaNote).toHaveTextContent("tylko 7 osób w bazie");
    fireEvent.click(within(kafkaNote).getByRole("button", { name: "Do rozmowy" }));
    expect(onMoveToTalk).toHaveBeenCalledWith({
      name: "Kafka / RabbitMQ",
      kind: "skills",
      level: "must",
    });
    expect(
      (onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[]).map((row) => row.key),
    ).not.toContain("kafka");
    const payNote = screen
      .getAllByTestId("requirement-row-rare")
      .find((note) => note.textContent?.includes("płatności"))!;
    fireEvent.click(within(payNote).getByRole("button", { name: "Zostaw" }));
    expect(
      screen.getAllByTestId("requirement-row-rare").some((n) => n.textContent?.includes("płatności")),
    ).toBe(false);
  });

  it("jednoliterowe słowo z litery („C”) wchodzi do wiersza; cyfra nie", () => {
    const { onRowsChange } = renderEditor({ rows: [], critical: known({}) });
    const input = screen.getByLabelText("Wymaganie 1 — słowo albo wariant");
    fireEvent.change(input, { target: { value: "C" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect((onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[])[0].words).toEqual(["C"]);
    onRowsChange.mockClear();
    fireEvent.change(input, { target: { value: "7" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRowsChange).not.toHaveBeenCalled();
  });
});

describe("wariant A (13.10.2026): słowo do szukania czy rozmowa", () => {
  const TENDER: RequirementRowForm[] = [
    { key: "azure", words: ["Azure"], level: "must" },
    { key: "tender", words: ["doświadczenie w przetargach"], level: "must" },
    { key: "sql", words: ["SQL (bardzo dobra znajomość)"], level: "must" },
  ];
  const reading = (over: Record<string, unknown>) => ({
    text: "",
    kind: "keyword",
    keyword: null,
    comment: null,
    talk: null,
    talk_text: null,
    suggestions: [],
    needs_decision: false,
    ...over,
  });
  const TENDER_INFO = {
    azure: { label: "Azure", eligible: true, suggested: false },
    tender: {
      label: "doświadczenie w przetargach",
      eligible: false,
      suggested: false,
      readings: [
        reading({
          text: "doświadczenie w przetargach",
          kind: "prose",
          talk: "skills",
          talk_text: "doświadczenie w przetargach",
          suggestions: ["przetarg*", "PZP"],
          needs_decision: true,
        }),
      ],
    },
    sql: {
      label: "SQL (bardzo dobra znajomość)",
      eligible: false,
      suggested: false,
      readings: [
        reading({
          text: "SQL (bardzo dobra znajomość)",
          kind: "technology",
          keyword: "SQL",
          comment: "bardzo dobra znajomość",
          talk: "skills",
          talk_text: "SQL — bardzo dobra znajomość",
        }),
      ],
    },
  } as unknown as Record<string, RowCriticalInfo>;

  it("zdanie czeka na decyzję: słowo z podpowiedzi albo „Do rozmowy”", () => {
    const onMoveToTalk = vi.fn();
    const { onRowsChange } = renderEditor({
      rows: TENDER,
      critical: known(TENDER_INFO),
      onMoveToTalk,
    });
    const callout = screen.getByTestId("requirement-row-decision");
    expect(callout).toHaveTextContent("to zdanie");
    fireEvent.click(within(callout).getByRole("button", { name: /przetarg\*/ }));
    const rows = onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[];
    expect(rows.find((r) => r.key === "tender")?.words).toEqual(["przetarg*"]);
    // Zdanie nie przepada — trafia do „Rekruter sprawdza w rozmowie”.
    expect(onMoveToTalk).toHaveBeenCalledWith({
      name: "doświadczenie w przetargach",
      kind: "skills",
      level: "must",
    });
  });

  it("„Do rozmowy” zdejmuje wiersz i oddaje zdanie rodzicowi", () => {
    const onMoveToTalk = vi.fn();
    const { onRowsChange } = renderEditor({
      rows: TENDER,
      critical: known(TENDER_INFO),
      onMoveToTalk,
    });
    fireEvent.click(
      within(screen.getByTestId("requirement-row-decision")).getByRole("button", {
        name: "Do rozmowy",
      }),
    );
    const rows = onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[];
    expect(rows.map((r) => r.key)).toEqual(["azure", "sql"]);
    expect(onMoveToTalk).toHaveBeenCalledTimes(1);
  });

  it("zdanie nie może być krytyczne, dopóki nie zapadnie decyzja", () => {
    renderEditor({ rows: TENDER, critical: known(TENDER_INFO) });
    expect(levelOption("doświadczenie w przetargach", "Krytyczne")).toBeDisabled();
    expect(levelOption("Azure", "Krytyczne")).not.toBeDisabled();
  });

  it("komentarz w nawiasie: „Rozdziel teraz” zostawia słowo, poziom idzie do rozmowy", () => {
    const onMoveToTalk = vi.fn();
    const { onRowsChange } = renderEditor({
      rows: TENDER,
      critical: known(TENDER_INFO),
      onMoveToTalk,
    });
    const note = screen.getByTestId("requirement-row-comment");
    expect(note).toHaveTextContent("Szukamy „SQL”");
    fireEvent.click(within(note).getByRole("button", { name: "Rozdziel teraz" }));
    const rows = onRowsChange.mock.calls.at(-1)![0] as RequirementRowForm[];
    expect(rows.find((r) => r.key === "sql")?.words).toEqual(["SQL"]);
    expect(onMoveToTalk).toHaveBeenCalledWith({
      name: "SQL — bardzo dobra znajomość",
      kind: "skills",
      level: "must",
    });
  });

  it("krytyczne zostawiające mniej niż 20 osób dostają ostrzeżenie pod listą", () => {
    mocks.counts = { perRow: {}, required: 9, critical: 3, failed: false };
    renderEditor({
      rows: [{ key: "azure", words: ["Azure"], level: "critical" }],
      critical: known({ azure: { label: "Azure", eligible: true, suggested: false } }),
      countEnabled: true,
    });
    expect(screen.getByTestId("requirement-critical-reach")).toHaveTextContent(
      "Krytyczne razem zostawiają 3 osoby",
    );
  });
});
