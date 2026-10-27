import { describe, expect, it } from "vitest";

import {
  CRITICAL_ROWS_MAX,
  NICE_ROWS_MAX,
  REQUIRED_ROWS_MAX,
  addRow,
  applySuggestion,
  canAddRow,
  countLevel,
  criticalDecision,
  criticalDecisionMissing,
  criticalRows,
  criticalSummary,
  enterRequirements,
  filledRows,
  levelBlockedReason,
  mustHeads,
  newRowKey,
  niceHeads,
  addRowVariants,
  parseRequirementEntry,
  requiredOverflowNotice,
  requiredRows,
  rowCountHint,
  gluedVariants,
  isRareRowCount,
  rowCriticalInfo,
  rowHead,
  rowsFromStored,
  searchRows,
  setRowLevel,
  suggestedRowKeys,
  toStoredRows,
  type RequirementLevel,
  type RequirementRowForm,
  type RowCriticalInfo,
} from "@/lib/requirement-rows";

const row = (
  key: string,
  words: string[],
  level: RequirementLevel = "must",
): RequirementRowForm => ({ key, words, level });

/** `count` wypełnionych wierszy o różnych pierwszych słowach. */
const many = (count: number, level: RequirementLevel, prefix: string) =>
  Array.from({ length: count }, (_, i) => row(`${prefix}${i}`, [`${prefix}-${i}`], level));

const ROWS: RequirementRowForm[] = [
  row("java", ["Java"], "critical"),
  row("kafka", ["Kafka", "RabbitMQ"]),
  row("pay", ["płatnoś*", "płatności", "payments"]),
  row("k8s", ["Kubernetes", "k8s"], "nice"),
];

describe("rowHead — słowo, po którym wiersz jest rozpoznawany", () => {
  it("pierwsze słowo bez gwiazdki, także gdy rdzeń stoi wcześniej", () => {
    expect(rowHead(["Java", "JVM"])).toBe("Java");
    expect(rowHead(["płatnoś*", "płatności", "payments"])).toBe("płatności");
  });

  it("same rdzenie: pierwszy rdzeń bez gwiazdki", () => {
    expect(rowHead(["bankow*", "bank*"])).toBe("bankow");
    expect(rowHead(["test**"])).toBe("test");
  });

  it("puste i białe słowa się nie liczą, `|` w słowie to spacja", () => {
    expect(rowHead([])).toBe("");
    expect(rowHead(["  ", ""])).toBe("");
    expect(rowHead(["  ", " Spring   Boot "])).toBe("Spring Boot");
    expect(rowHead(["CI|CD"])).toBe("CI CD");
  });
});

describe("filledRows i widoki listy", () => {
  it("pomija puste wiersze, czyści słowa i zostawia klucz oraz poziom", () => {
    const rows = [
      row("a", [" Java ", "java", "JVM"], "critical"),
      row("empty", []),
      row("blank", ["  "]),
    ];
    expect(filledRows(rows)).toEqual([row("a", ["Java", "JVM"], "critical")]);
  });

  it("dwa wiersze o tym samym pierwszym słowie to jedno wymaganie — zostaje pierwszy", () => {
    const rows = [
      row("a", ["Java", "JVM"]),
      row("b", ["java"], "nice"),
      row("c", ["bankow*"]),
      row("d", ["Bankow", "banking"]),
    ];
    expect(filledRows(rows).map((r) => r.key)).toEqual(["a", "c"]);
  });

  it("obowiązkowe = krytyczne i „musi mieć”; nazwy to pierwsze słowa wierszy", () => {
    expect(requiredRows(ROWS).map((r) => r.key)).toEqual(["java", "kafka", "pay"]);
    expect(criticalRows(ROWS).map((r) => r.key)).toEqual(["java"]);
    expect(mustHeads(ROWS)).toEqual(["Java", "Kafka", "płatności"]);
    expect(niceHeads(ROWS)).toEqual(["Kubernetes"]);
  });

  it("wiersze wyszukiwania niosą wszystkie warianty, bez „mile widzianych”", () => {
    expect(searchRows(ROWS)).toEqual([
      ["Java"],
      ["Kafka", "RabbitMQ"],
      ["płatnoś*", "płatności", "payments"],
    ]);
  });

  it("countLevel liczy tylko wypełnione wiersze", () => {
    const rows = [...ROWS, row("empty", [], "nice")];
    expect(countLevel(rows, "critical")).toBe(1);
    expect(countLevel(rows, "must")).toBe(2);
    expect(countLevel(rows, "nice")).toBe(1);
  });
});

describe("limity poziomów (lustro serwera)", () => {
  it("stałe: 10 obowiązkowych, 20 mile widzianych, 3 krytyczne", () => {
    expect([REQUIRED_ROWS_MAX, NICE_ROWS_MAX, CRITICAL_ROWS_MAX]).toEqual([10, 20, 3]);
  });

  it("trzeci krytyczny wchodzi (od 08.10.2026), czwarty jest zablokowany", () => {
    const two = [
      row("a", ["Java"], "critical"),
      row("b", ["Kafka"], "critical"),
      row("c", ["Spring"]),
      row("d", ["Docker"]),
    ];
    expect(levelBlockedReason(two, "c", "critical")).toBeNull();
    const rows = setRowLevel(two, "c", "critical");
    expect(rows.map((r) => r.level)).toEqual(["critical", "critical", "critical", "must"]);
    expect(levelBlockedReason(rows, "d", "critical")).toBe(
      "Najwyżej 3 krytyczne — zdejmij jedno, żeby dodać kolejne.",
    );
    expect(levelBlockedReason(rows, "a", "critical")).toBeNull();
    expect(levelBlockedReason(rows, "a", "must")).toBeNull();
    expect(setRowLevel(rows, "d", "critical")).toEqual(rows);
    expect(setRowLevel(rows, "a", "must").map((r) => r.level)).toEqual([
      "must",
      "critical",
      "critical",
      "must",
    ]);
  });

  // Audyt 06.10.2026 (N3): serwer zapisuje nadmiar „musi mieć” jako „mile
  // widziane” (do 20), więc jedenasty obowiązkowy nie jest już blokowany —
  // edytor mówi tylko, co się z nim stanie (`requiredOverflowNotice`).
  it("jedenasty obowiązkowy: „mile widziane” może przejść na „musi mieć”, ale nie na krytyczne", () => {
    const rows = [...many(REQUIRED_ROWS_MAX, "must", "m"), row("n", ["Docker"], "nice")];
    expect(levelBlockedReason(rows, "n", "must")).toBeNull();
    expect(levelBlockedReason(rows, "n", "critical")).toBe(
      "Najwyżej 10 wierszy obowiązkowych — krytyczne musi się w nich zmieścić.",
    );
    // Zmiana w obrębie obowiązkowych nie zwiększa ich liczby.
    expect(levelBlockedReason(rows, "m0", "critical")).toBeNull();
    expect(setRowLevel(rows, "n", "must").at(-1)!.level).toBe("must");
  });

  it("dwudziesty pierwszy „mile widziane” jest zablokowany — nadmiar „musi mieć” też zajmuje te miejsca", () => {
    const rows = [...many(NICE_ROWS_MAX, "nice", "n"), row("m", ["Java"])];
    expect(levelBlockedReason(rows, "m", "nice")).toBe(
      "Najwyżej 20 wierszy „mile widziane”.",
    );
    expect(levelBlockedReason(rows.slice(1), "m", "nice")).toBeNull();
    // 12 obowiązkowych (2 ponad limit) + 18 mile widzianych = 20 miejsc zajętych.
    const crowded = [
      ...many(12, "must", "m"),
      ...many(17, "nice", "n"),
      row("x", ["Docker"]),
    ];
    expect(levelBlockedReason(crowded, "x", "nice")).toBeNull();
    const full = [...many(12, "must", "m"), ...many(18, "nice", "n"), row("x", ["Docker"])];
    // „x” jest obowiązkowy (13.) i już zajmuje miejsce nadmiaru — zmiana nic nie dokłada.
    expect(levelBlockedReason(full, "x", "nice")).toBeNull();
  });

  it("zdanie o nadmiarze „musi mieć” tylko powyżej 10 wierszy obowiązkowych", () => {
    expect(requiredOverflowNotice(many(REQUIRED_ROWS_MAX, "must", "m"))).toBeNull();
    expect(requiredOverflowNotice(many(11, "must", "m"))).toBe(
      "Ponad 10 wymagań „musi mieć” — kolejne zapiszą się jako „mile widziane”.",
    );
  });

  it("puste wiersze nie zajmują limitu, a nieznany klucz niczego nie blokuje", () => {
    const rows = [
      row("a", ["Java"], "critical"),
      row("empty", [], "critical"),
      row("c", ["Spring"]),
    ];
    expect(levelBlockedReason(rows, "c", "critical")).toBeNull();
    expect(levelBlockedReason(rows, "nie-ma", "critical")).toBeNull();
    expect(setRowLevel(rows, "nie-ma", "nice")).toEqual(rows);
  });

  it("nowy wiersz jest obowiązkowy, a przy pełnym limicie — „mile widziane”", () => {
    const added = addRow(ROWS);
    expect(added).toHaveLength(ROWS.length + 1);
    expect(added.at(-1)).toMatchObject({ words: [], level: "must" });
    expect(added.at(-1)!.key).not.toBe("");

    const full = many(REQUIRED_ROWS_MAX, "must", "m");
    expect(addRow(full).at(-1)).toMatchObject({ words: [], level: "nice" });
    expect(canAddRow(full)).toBe(true);
    expect(canAddRow([...full, ...many(NICE_ROWS_MAX, "nice", "n")])).toBe(false);
    // Nadmiar „musi mieć” zajmuje miejsca „mile widzianych” — razem najwyżej 30.
    expect(canAddRow([...many(15, "must", "m"), ...many(15, "nice", "n")])).toBe(false);
    expect(canAddRow([...many(15, "must", "m"), ...many(14, "nice", "n")])).toBe(true);
    expect(canAddRow([])).toBe(true);
  });

  it("podpowiedź przy liczbie osób: słowo bardzo ogólne albo nieznane w bazie", () => {
    expect(rowCountHint(15_001)).toBe("Słowo bardzo ogólne — zawęź (np. dodaj technologię).");
    expect(rowCountHint(15_000)).toBeNull();
    // Zero i rzadkie słowo mówi okno pod wierszem (`RareWordCallout`).
    expect(rowCountHint(0)).toBeNull();
    expect(rowCountHint(42)).toBeNull();
    // „liczę…” i „nie policzono” to nie zero.
    expect(rowCountHint(undefined)).toBeNull();
    expect(rowCountHint(null)).toBeNull();
  });

  it("rzadkie słowo: poniżej 20 osób; „liczę…” i „nie policzono” nie są rzadkie", () => {
    expect(isRareRowCount(0)).toBe(true);
    expect(isRareRowCount(19)).toBe(true);
    expect(isRareRowCount(20)).toBe(false);
    expect(isRareRowCount(undefined)).toBe(false);
    expect(isRareRowCount(null)).toBe(false);
  });

  it("warianty sklejone ukośnikiem albo nawiasem (pomiar 27.10.2026)", () => {
    expect(gluedVariants("SoapUI/ReadyAPI")).toEqual(["SoapUI", "ReadyAPI"]);
    expect(gluedVariants("GitOps (ArgoCD/FluxCD)")).toEqual(["GitOps", "ArgoCD", "FluxCD"]);
    expect(gluedVariants("Kafka")).toBeNull();
    // Część krótsza niż 2 znaki odpada — „z/OS” nie ma czego rozdzielać.
    expect(gluedVariants("z/OS")).toBeNull();
  });

  it("klucze nowych wierszy się nie powtarzają", () => {
    expect(new Set([newRowKey(), newRowKey(), newRowKey()]).size).toBe(3);
  });
});

describe("zapis: stack.rows i stack.critical", () => {
  it("toStoredRows oddaje słowa i poziom bez klucza i bez pustych wierszy", () => {
    expect(toStoredRows([...ROWS, row("empty", [])])).toEqual([
      { words: ["Java"], level: "critical" },
      { words: ["Kafka", "RabbitMQ"], level: "must" },
      { words: ["płatnoś*", "płatności", "payments"], level: "must" },
      { words: ["Kubernetes", "k8s"], level: "nice" },
    ]);
  });

  it("criticalDecision: [] to świadome „Brak krytycznych”, null — brak decyzji albo wiersze krytyczne", () => {
    const none = ROWS.map((r) => (r.level === "critical" ? { ...r, level: "must" as const } : r));
    expect(criticalDecision(none, false)).toBeNull();
    expect(criticalDecision(none, true)).toEqual([]);
    // Przy wierszu krytycznym serwer czyta poziomy — flaga nic nie zmienia.
    expect(criticalDecision(ROWS, true)).toBeNull();
    expect(criticalDecision(ROWS, false)).toBeNull();
  });
});

describe("rowsFromStored — wiersze z zapisu i z odczytu requestu", () => {
  it("nie-tablica, śmieci i puste wiersze dają pustą listę", () => {
    expect(rowsFromStored(null)).toEqual([]);
    expect(rowsFromStored({ rows: [] })).toEqual([]);
    expect(
      rowsFromStored([null, "Java", { words: "Java" }, { words: [] }, { words: ["  ", 7] }]),
    ).toEqual([]);
  });

  it("czyta słowa i poziom; nieznany poziom to „musi mieć”", () => {
    const rows = rowsFromStored([
      { words: ["Java", 17, " JVM "], level: "must" },
      { words: ["Kubernetes"], level: "nice" },
      { words: ["Kafka"], level: "critical" },
      { words: ["Spring"], level: "cokolwiek" },
      { words: ["Docker"] },
    ]);
    expect(rows.map((r) => [r.words, r.level])).toEqual([
      [["Java", "JVM"], "must"],
      [["Kubernetes"], "nice"],
      [["Kafka"], "critical"],
      [["Spring"], "must"],
      [["Docker"], "must"],
    ]);
    expect(new Set(rows.map((r) => r.key)).size).toBe(rows.length);
  });

  it("etykiety z stack.critical wracają jako poziom wiersza — po pierwszym słowie etykiety", () => {
    const stored = [
      { words: ["Java"], level: "must" },
      { words: ["Kafka", "RabbitMQ"], level: "must" },
      { words: ["płatnoś*", "płatności"], level: "must" },
      { words: ["Kubernetes"], level: "nice" },
    ];
    const rows = rowsFromStored(stored, ["kafka lub RabbitMQ", "Kubernetes", "Oracle"]);
    // „Kubernetes” jest mile widziane, „Oracle” nie ma na liście — nic nie oznaczają.
    expect(rows.map((r) => r.level)).toEqual(["must", "critical", "must", "nice"]);
    expect(rowsFromStored(stored, ["płatności"]).map((r) => r.level)).toEqual([
      "must",
      "must",
      "critical",
      "nice",
    ]);
    expect(rowsFromStored(stored, null).map((r) => r.level)).toEqual([
      "must",
      "must",
      "must",
      "nice",
    ]);
  });

  it("z etykiet powstają najwyżej trzy krytyczne, licząc już oznaczone wiersze", () => {
    const stored = [
      { words: ["Java"], level: "must" },
      { words: ["Kafka"], level: "must" },
      { words: ["Spring"], level: "must" },
      { words: ["Docker"], level: "must" },
    ];
    expect(
      rowsFromStored(stored, ["Java", "Kafka", "Spring", "Docker"]).map((r) => r.level),
    ).toEqual(["critical", "critical", "critical", "must"]);
    expect(
      rowsFromStored(
        [{ words: ["Oracle"], level: "critical" }, ...stored],
        ["Java", "Kafka", "Spring"],
      ).map((r) => r.level),
    ).toEqual(["critical", "critical", "critical", "must", "must"]);
  });

  it("wiersze o tym samym pierwszym słowie zlewają się w jeden", () => {
    const rows = rowsFromStored([
      { words: ["Java", "JVM"], level: "must" },
      { words: ["java"], level: "nice" },
    ]);
    expect(rows.map((r) => r.words)).toEqual([["Java", "JVM"]]);
  });
});

describe("criticalSummary — zdanie pod listą", () => {
  const none = ROWS.map((r) => (r.level === "critical" ? { ...r, level: "must" as const } : r));

  it("trzy stany: wybrane, „Brak krytycznych”, nie zdecydowano", () => {
    expect(criticalSummary(ROWS, false)).toBe(
      "Krytyczne: Java — propozycje AI ukrywają osoby, które ich nie mają.",
    );
    expect(criticalSummary(none, true)).toBe(
      "Brak krytycznych — propozycje AI nie ukrywają nikogo, wszystkie wymagania dają punkty.",
    );
    expect(criticalSummary(none, false)).toBe(
      "Nie zdecydowano — oznacz najwyżej 3 wiersze jako krytyczne albo wybierz „Brak krytycznych”.",
    );
  });

  it("wiersz krytyczny wygrywa z flagą „Brak krytycznych”", () => {
    expect(criticalSummary(ROWS, true)).toMatch(/^Krytyczne: Java/);
  });
});

describe("rowCriticalInfo — odpowiedź serwera po kolei wierszy obowiązkowych", () => {
  it("mapuje po indeksie, pomijając „mile widziane” i puste wiersze", () => {
    const rows = [row("k8s", ["Kubernetes"], "nice"), row("empty", []), ...ROWS.slice(0, 3)];
    const info = rowCriticalInfo(rows, {
      labels: ["Java", "Kafka lub RabbitMQ", "płatności"],
      eligible: ["java", "Kafka lub RabbitMQ"],
      suggested: ["Java"],
      stats: { Java: { rate: 0.96, jobs: 41 } },
    });
    expect(info).toEqual({
      java: {
        label: "Java",
        eligible: true,
        suggested: true,
        stat: { rate: 0.96, jobs: 41 },
      },
      kafka: { label: "Kafka lub RabbitMQ", eligible: true, suggested: false, stat: undefined },
      pay: { label: "płatności", eligible: false, suggested: false, stat: undefined },
    });
    expect(info).not.toHaveProperty("k8s");
  });

  it("wymóg decyzji przy przekazaniu liczy tylko technologie ze słownika", () => {
    const rows = [row("java", ["Java"]), row("camunda", ["Camunda BPM"]), row("bank", ["bankowości"])];
    const info = rowCriticalInfo(rows, {
      labels: ["Java", "Camunda BPM", "bankowości"],
      eligible: ["Java"],
      suggested: [],
      stats: {},
    });
    expect(info.camunda).toMatchObject({ eligible: false });
    expect(info.bank).toMatchObject({ eligible: false });
    expect(criticalDecisionMissing(rows.slice(1), false, info)).toBe(false);
    expect(criticalDecisionMissing(rows, false, info)).toBe(true);
  });

  it("bez etykiet z serwera etykietą jest pierwsze słowo wiersza", () => {
    const info = rowCriticalInfo(ROWS, { eligible: ["Kafka"], suggested: [], stats: {} });
    expect(info.kafka).toMatchObject({ label: "Kafka", eligible: true });
    expect(info.java).toMatchObject({ label: "Java", eligible: false });
  });
});

describe("criticalDecisionMissing — bramka „Przekaż do searchu”", () => {
  const none = ROWS.map((r) => (r.level === "critical" ? { ...r, level: "must" as const } : r));
  const info: Record<string, RowCriticalInfo> = {
    java: { label: "Java", eligible: true, suggested: true },
    kafka: { label: "Kafka lub RabbitMQ", eligible: true, suggested: false },
    pay: { label: "płatności", eligible: false, suggested: false },
  };

  it("jest wiersz do oznaczenia, a decyzji nie ma — brak", () => {
    expect(criticalDecisionMissing(none, false, info)).toBe(true);
  });

  it("„Brak krytycznych” albo wiersz krytyczny to decyzja", () => {
    expect(criticalDecisionMissing(none, true, info)).toBe(false);
    expect(criticalDecisionMissing(ROWS, false, info)).toBe(false);
  });

  it("dopóki serwer nie odpowie, nie zgadujemy", () => {
    expect(criticalDecisionMissing(none, false, null)).toBe(false);
    expect(criticalDecisionMissing(none, false, undefined)).toBe(false);
  });

  it("lista bez technologii ze słownika nie wymaga decyzji", () => {
    expect(criticalDecisionMissing(none, false, {})).toBe(false);
    expect(
      criticalDecisionMissing([row("pay", ["płatności"])], false, { pay: info.pay }),
    ).toBe(false);
    // „Mile widziane” nie może być krytyczne — jego wpis nic nie znaczy.
    expect(
      criticalDecisionMissing([row("java", ["Java"], "nice")], false, { java: info.java }),
    ).toBe(false);
  });
});

describe("podpowiedź z historii", () => {
  const none = ROWS.map((r) => (r.level === "critical" ? { ...r, level: "must" as const } : r));

  it("suggestedRowKeys: podpowiedziane i dopuszczalne, najwyżej dwa (trzecią wybiera człowiek)", () => {
    expect(suggestedRowKeys(none, null)).toEqual([]);
    expect(
      suggestedRowKeys(none, {
        java: { label: "Java", eligible: true, suggested: true },
        kafka: { label: "Kafka", eligible: false, suggested: true },
        pay: { label: "płatności", eligible: true, suggested: false },
      }),
    ).toEqual(["java"]);
    const three = [row("a", ["Java"]), row("b", ["Kafka"]), row("c", ["Spring"])];
    const all = Object.fromEntries(
      three.map((r) => [r.key, { label: r.words[0], eligible: true, suggested: true }]),
    );
    expect(suggestedRowKeys(three, all)).toEqual(["a", "b"]);
  });

  it("applySuggestion oznacza wskazane wiersze i zdejmuje pozostałe krytyczne", () => {
    const next = applySuggestion(ROWS, ["kafka"]);
    expect(next.map((r) => [r.key, r.level])).toEqual([
      ["java", "must"],
      ["kafka", "critical"],
      ["pay", "must"],
      ["k8s", "nice"],
    ]);
    // Wejście zostaje nietknięte.
    expect(ROWS[0].level).toBe("critical");
  });
});

// Decyzja D1 (10.10.2026): przecinek, średnik, Enter i wklejona lista dają
// OSOBNE wymagania; wariant („lub”) powstaje tylko świadomie.
describe("addRowVariants — pole „+ lub” dopisuje warianty do TEGO wiersza", () => {
  it("przecinek, średnik, nowa linia i „A / B” to kolejne warianty, nie nowe wymagania", () => {
    expect(addRowVariants(["Java"], "JDK; OpenJDK, GraalVM\nJ2EE / Jakarta EE")).toEqual({
      words: ["Java", "JDK", "OpenJDK", "GraalVM", "J2EE", "Jakarta EE"],
      rejected: [],
    });
  });

  it("słowo, które już jest w wierszu, nie wraca drugi raz; nawias zostaje jednym słowem", () => {
    expect(addRowVariants(["Java", "Spring"], "java; Spring (Boot, Data)").words).toEqual([
      "Java",
      "Spring",
      "Spring (Boot, Data)",
    ]);
  });

  it("słowa, którego nie da się szukać, nie dopisuje — oddaje je do komunikatu", () => {
    expect(addRowVariants(["Java"], "+; JDK")).toEqual({ words: ["Java", "JDK"], rejected: ["+"] });
  });
});

describe("parseRequirementEntry — wpisany albo wklejony tekst → wymagania", () => {
  const groups = (text: string) => parseRequirementEntry(text).groups;

  it("przecinek, średnik i nowa linia rozdzielają wymagania", () => {
    expect(groups("Kafka, Redis; AWS\nSQL\r\nDocker")).toEqual([
      ["Kafka"],
      ["Redis"],
      ["AWS"],
      ["SQL"],
      ["Docker"],
    ]);
    expect(groups("Spring Boot")).toEqual([["Spring Boot"]]);
  });

  it("„A / B”, „A lub B”, „A or B” to jedno wymaganie z wariantami; „CI/CD” to jedno słowo", () => {
    expect(groups("Kafka / RabbitMQ")).toEqual([["Kafka", "RabbitMQ"]]);
    expect(groups("React lub Vue OR Angular, CI/CD, PL/SQL")).toEqual([
      ["React", "Vue", "Angular"],
      ["CI/CD"],
      ["PL/SQL"],
    ]);
  });

  it("separator w nawiasie nie dzieli; niedomknięty nawias nie skleja reszty listy", () => {
    expect(groups("Spring (Boot, Data), SQL")).toEqual([["Spring (Boot, Data)"], ["SQL"]]);
    expect(groups("Bazy danych (Oracle lub PostgreSQL); AWS")).toEqual([
      ["Bazy danych (Oracle lub PostgreSQL)"],
      ["AWS"],
    ]);
    expect(groups("Java (11, Spring, SQL")).toEqual([["Java (11"], ["Spring"], ["SQL"]]);
  });

  it("jedna litera wchodzi („C”, „R”), cyfra i sam znak wracają jako odrzucone", () => {
    expect(parseRequirementEntry("C, 7, R / Python, +")).toEqual({
      groups: [["C"], ["R", "Python"]],
      rejected: ["7", "+"],
    });
  });

  it("puste kawałki znikają, powtórzony wariant liczy się raz, `|` to spacja", () => {
    expect(parseRequirementEntry(" Java ,, ;\n  ")).toEqual({ groups: [["Java"]], rejected: [] });
    expect(groups("Kafka / kafka / KAFKA")).toEqual([["Kafka"]]);
    expect(groups("CI|CD")).toEqual([["CI CD"]]);
    expect(parseRequirementEntry("   ")).toEqual({ groups: [], rejected: [] });
  });

  it("znaczniki listy z wklejonego maila nie trafiają do słów", () => {
    expect(groups("- Java\n• Spring Boot\n1. SQL\n2) AWS\n* Docker")).toEqual([
      ["Java"],
      ["Spring Boot"],
      ["SQL"],
      ["AWS"],
      ["Docker"],
    ]);
    // Kropka i myślnik w nazwie zostają.
    expect(groups(".NET, e-commerce, bankow*")).toEqual([[".NET"], ["e-commerce"], ["bankow*"]]);
  });

  it("najwyżej 20 słów w wierszu", () => {
    const text = Array.from({ length: 25 }, (_, i) => `Słowo${i}`).join(" / ");
    expect(groups(text)[0]).toHaveLength(20);
  });
});

describe("enterRequirements — każda grupa to osobny wiersz", () => {
  const empty = (key = "e", level: RequirementLevel = "must") => row(key, [], level);
  const words = (rows: readonly RequirementRowForm[]) => rows.map((r) => r.words);

  it("pierwsza grupa wypełnia wiersz, kolejne dochodzą pod nim, kursor w pustym wierszu na końcu", () => {
    const result = enterRequirements([row("a", ["Java"]), empty()], "e", [
      ["Kafka"],
      ["Redis", "KeyDB"],
    ]);
    expect(words(result.rows)).toEqual([["Java"], ["Kafka"], ["Redis", "KeyDB"], []]);
    expect(result.rows[1].key).toBe("e");
    expect(result.rows.map((r) => r.level)).toEqual(["must", "must", "must", "must"]);
    expect(result.focusKey).toBe(result.rows[3].key);
    expect(result).toMatchObject({ added: 2, duplicates: [], overLimit: [] });
    // Klucze się nie powtarzają — React nie pomyli wierszy.
    expect(new Set(result.rows.map((r) => r.key)).size).toBe(4);
  });

  it("pusty wiersz, który już stoi na końcu, dostaje kursor — bez dokładania kolejnego", () => {
    const result = enterRequirements([empty("e"), empty("t")], "e", [["Kafka"], ["Redis"]]);
    expect(words(result.rows)).toEqual([["Kafka"], ["Redis"], []]);
    expect(result.focusKey).toBe("t");
  });

  it("wpis w środku listy: nowe wiersze pod nim, kursor na końcu listy", () => {
    const result = enterRequirements([empty("e"), row("b", ["Java"])], "e", [["Kafka"], ["Redis"]]);
    expect(words(result.rows)).toEqual([["Kafka"], ["Redis"], ["Java"], []]);
    expect(result.focusKey).toBe(result.rows[3].key);
  });

  it("bez pustego wiersza na końcu (wyjście z pola): lista nie rośnie o pusty wiersz", () => {
    const result = enterRequirements([empty()], "e", [["Kafka"], ["Redis"]], { trailing: false });
    expect(words(result.rows)).toEqual([["Kafka"], ["Redis"]]);
    expect(result.focusKey).toBeNull();
  });

  it("poziom: wiersz docelowy zostaje, nowe to „musi mieć”, po 10 obowiązkowych „mile widziane” — nigdy krytyczne", () => {
    const result = enterRequirements(
      [...many(8, "must", "m"), empty("e", "critical")],
      "e",
      [["Alfa"], ["Beta"], ["Gamma"]],
    );
    expect(result.rows.slice(8).map((r) => [r.words[0] ?? "", r.level])).toEqual([
      ["Alfa", "critical"],
      ["Beta", "must"],
      ["Gamma", "nice"],
      ["", "nice"],
    ]);
  });

  it("słowo, które już prowadzi inny wiersz, jest pomijane — także powtórzone w tym samym wpisie", () => {
    const result = enterRequirements([row("a", ["Java", "JVM"]), empty()], "e", [
      ["java"],
      ["Spring"],
      ["spring", "Boot"],
      // Wariant innego wiersza to nie jego pierwsze słowo — wolno.
      ["JVM"],
    ]);
    expect(result.duplicates).toEqual(["java", "spring"]);
    expect(words(result.rows)).toEqual([["Java", "JVM"], ["Spring"], ["JVM"], []]);
    expect(result.added).toBe(2);
  });

  it("same powtórki albo puste grupy: lista bez zmian, kursor zostaje w wierszu", () => {
    const rows = [row("a", ["Java"]), empty()];
    const result = enterRequirements(rows, "e", [["JAVA"], [], ["  "]]);
    expect(result.rows).toEqual(rows);
    expect(result).toMatchObject({ added: 0, focusKey: "e", duplicates: ["JAVA"], overLimit: [] });
  });

  it("ponad limit 30 wierszy: reszta wraca jako lista, bez pustego wiersza na końcu", () => {
    const rows = [...many(10, "must", "m"), ...many(19, "nice", "n"), empty("e", "nice")];
    const result = enterRequirements(rows, "e", [["Alfa"], ["Beta", "Gamma"], ["Delta"]]);
    expect(result.rows).toHaveLength(30);
    expect(result.rows[29]).toEqual(row("e", ["Alfa"], "nice"));
    expect(result.overLimit).toEqual(["Beta lub Gamma", "Delta"]);
    expect(result.focusKey).toBeNull();
    expect(canAddRow(result.rows)).toBe(false);
  });

  it("nieznany klucz niczego nie zmienia", () => {
    const rows = [row("a", ["Java"])];
    expect(enterRequirements(rows, "nie-ma", [["Kafka"]])).toMatchObject({
      rows,
      added: 0,
      focusKey: null,
    });
  });
});

describe("wariant A (13.10.2026): odczyt słów wiersza", () => {
  const rows = [
    { key: "a", words: ["Azure"], level: "must" as const },
    { key: "b", words: ["doświadczenie w przetargach", "przetarg*"], level: "must" as const },
  ];
  const prose = {
    text: "doświadczenie w przetargach",
    kind: "prose" as const,
    keyword: null,
    comment: null,
    talk: "skills" as const,
    talk_text: "doświadczenie w przetargach",
    suggestions: ["przetarg*"],
    needs_decision: true,
  };

  it("rowCriticalInfo niesie odczyt słów w kolejności wierszy", async () => {
    const { rowCriticalInfo, rowDecision, rowsNeedingDecision } = await import(
      "@/lib/requirement-rows"
    );
    const info = rowCriticalInfo(rows, {
      labels: ["Azure", "doświadczenie w przetargach"],
      eligible: ["Azure"],
      suggested: [],
      stats: {},
      readings: [[], [prose, { ...prose, text: "przetarg*", kind: "keyword", needs_decision: false }]],
    });
    expect(rowDecision(info.a)).toBeNull();
    expect(rowDecision(info.b)?.text).toBe("doświadczenie w przetargach");
    expect(rowsNeedingDecision(rows, info)).toEqual(["b"]);
    // Bez odpowiedzi serwera nie zgadujemy.
    expect(rowsNeedingDecision(rows, null)).toEqual([]);
  });

  it("replaceRowWord podmienia słowo, a wiersz bez słów znika", async () => {
    const { replaceRowWord } = await import("@/lib/requirement-rows");
    expect(replaceRowWord(rows, "b", "doświadczenie w przetargach", [])).toEqual([
      rows[0],
      { ...rows[1], words: ["przetarg*"] },
    ]);
    expect(replaceRowWord(rows, "a", "azure", [])).toEqual([rows[1]]);
    // Podpowiedź równa słowu, które już jest, nie dubluje go.
    expect(
      replaceRowWord(rows, "b", "doświadczenie w przetargach", ["przetarg*"])[1].words,
    ).toEqual(["przetarg*"]);
  });

  it("ostrzeżenie o krytycznych tylko poniżej 20 osób", async () => {
    const { criticalReachWarning } = await import("@/lib/requirement-rows");
    expect(criticalReachWarning(undefined)).toBeNull();
    expect(criticalReachWarning(20)).toBeNull();
    expect(criticalReachWarning(0)).toContain("nie zostawiają nikogo");
    expect(criticalReachWarning(1)).toContain("1 osobę");
    expect(criticalReachWarning(9)).toContain("9 osób");
  });
});
