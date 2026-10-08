import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
  NOT_A_TECHNOLOGY_HINT,
  OUTSIDE_DICTIONARY_NOTE,
  RequirementRowsEditor,
  type RequirementRowsEditorProps,
} from "@/components/champion/RequirementRowsEditor";
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

  it("słowo wpisane w wierszu dochodzi jako wariant", () => {
    const { onRowsChange } = renderEditor();
    const input = screen.getByLabelText("Wymaganie 1 — słowo albo wariant");
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
    expect(levelOption("wiersz 1", "Krytyczne")).toBeDisabled();
    expect(levelOption("wiersz 1", "Krytyczne")).toHaveAttribute(
      "title",
      "Najpierw wpisz słowo kluczowe",
    );
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
  it("słowo, które nie jest nazwą technologii: „Krytyczne” nieaktywne, powód pod wierszem", () => {
    const { onRowsChange } = renderEditor();
    const option = levelOption("płatności", "Krytyczne");
    expect(option).toBeDisabled();
    expect(option).toHaveAttribute("title", NOT_A_TECHNOLOGY_HINT);
    fireEvent.click(option);
    expect(onRowsChange).not.toHaveBeenCalled();
    // Powód stoi też na widoku — sam dymek na wyłączonym przycisku to za mało.
    expect(screen.getAllByTestId("requirement-row-critical-blocked")).toHaveLength(1);
    expect(screen.getByTestId("requirement-row-critical-blocked")).toHaveTextContent(
      "Nie może być krytyczne: to nie jest nazwa technologii ani narzędzia — nie może ukrywać kandydatów.",
    );
    // Technologia ze słownika jest do wyboru, bez dopisku.
    expect(levelOption("Java", "Krytyczne")).toBeEnabled();
    expect(levelOption("Java", "Krytyczne")).not.toHaveAttribute("title");
  });

  it("powód blokady z serwera stoi pod wierszem i w dymku", () => {
    const reason = "To branża, nie technologia — daje punkty, nie ukrywa kandydatów.";
    renderEditor({
      critical: known({
        ...INFO,
        pay: { label: "płatności", eligible: false, selectable: false, suggested: false, blockedReason: reason },
      }),
    });
    expect(levelOption("płatności", "Krytyczne")).toHaveAttribute("title", reason);
    expect(screen.getByTestId("requirement-row-critical-blocked")).toHaveTextContent(
      "Nie może być krytyczne: to branża, nie technologia — daje punkty, nie ukrywa kandydatów.",
    );
  });

  it("nazwa narzędzia spoza słownika: da się oznaczyć i odznaczyć (08.10.2026)", () => {
    const outside = { label: "płatności", eligible: false, selectable: true, suggested: false };
    const first = renderEditor({ critical: known({ ...INFO, pay: outside }) });
    const option = levelOption("płatności", "Krytyczne");
    expect(option).toBeEnabled();
    expect(option).not.toHaveAttribute("title");
    expect(screen.queryByTestId("requirement-row-critical-blocked")).toBeNull();
    fireEvent.click(option);
    expect(first.onRowsChange).toHaveBeenCalledWith(withLevels({ pay: "critical" }));
    first.unmount();

    // Oznaczony wiersz mówi, jak działa bramka dla nazwy spoza słownika…
    const second = renderEditor({
      rows: withLevels({ pay: "critical" }),
      critical: known({ ...INFO, pay: outside }),
    });
    expect(screen.getByTestId("requirement-row-outside-dictionary")).toHaveTextContent(
      OUTSIDE_DICTIONARY_NOTE,
    );
    // …i daje się odznaczyć.
    fireEvent.click(levelOption("płatności", "Musi mieć"));
    expect(second.onRowsChange).toHaveBeenCalledWith(withLevels({ pay: "must" }));
  });

  it("dopóki serwer nie odpowie, „Krytyczne” czeka — oznaczony wiersz zostaje", () => {
    renderEditor({
      rows: withLevels({ kafka: "critical" }),
      critical: { ...known(null), isLoading: true },
    });
    expect(levelOption("Java", "Krytyczne")).toBeDisabled();
    expect(levelOption("Java", "Krytyczne")).toHaveAttribute(
      "title",
      "Sprawdzam, czy to technologia ze słownika…",
    );
    expect(levelOption("Kafka", "Krytyczne")).toBeChecked();
    expect(levelOption("Kafka", "Krytyczne")).toBeEnabled();
    expect(screen.getByText("sprawdzam słownik")).toBeInTheDocument();
    // Pozostałe poziomy działają bez odpowiedzi serwera.
    expect(levelOption("Java", "Mile widziane")).toBeEnabled();
  });

  it("trzeci krytyczny da się oznaczyć (limit 3 od 08.10.2026)", () => {
    const info = { ...INFO, pay: { label: "płatności", eligible: true, suggested: false } };
    const { onRowsChange } = renderEditor({
      rows: withLevels({ java: "critical", kafka: "critical" }),
      critical: known(info),
    });
    const third = levelOption("płatności", "Krytyczne");
    expect(third).toBeEnabled();
    fireEvent.click(third);
    expect(onRowsChange).toHaveBeenCalledWith(
      withLevels({ java: "critical", kafka: "critical", pay: "critical" }),
    );
  });

  it("czwarty krytyczny jest nieaktywny — najwyżej trzy, a odznaczenie działa", () => {
    const info = {
      ...INFO,
      pay: { label: "płatności", eligible: true, suggested: false },
      k8s: { label: "Kubernetes", eligible: true, suggested: false },
    };
    const { onRowsChange } = renderEditor({
      rows: withLevels({ java: "critical", kafka: "critical", pay: "critical" }),
      critical: known(info),
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

  it("awaria sprawdzenia słownika: komunikat, „Ponów” woła ponowienie", () => {
    const retry = vi.fn();
    renderEditor({ critical: { info: null, isLoading: false, isError: true, retry } });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "Nie udało się sprawdzić, które słowa mogą być krytyczne.",
    );
    expect(levelOption("Java", "Krytyczne")).toBeDisabled();
    expect(levelOption("Java", "Krytyczne")).toHaveAttribute(
      "title",
      "Nie udało się sprawdzić słownika — spróbuj ponownie niżej",
    );
    fireEvent.click(within(alert).getByRole("button", { name: "Ponów" }));
    expect(retry).toHaveBeenCalledTimes(1);
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
    expect(
      screen.getByText("Nikt w bazie nie ma tego słowa — sprawdź pisownię."),
    ).toBeInTheDocument();
    // Jedna podpowiedź na wiersz z problemem — „płatności” (120) jej nie ma.
    expect(screen.getAllByText(/Słowo bardzo ogólne|Nikt w bazie nie ma/)).toHaveLength(2);
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
