import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";

import {
  CV_DIFF_LINES_MAX,
  contentLines,
  diffLines,
  htmlToDoc,
  replaceContentStep,
  type CvDiffLine,
} from "../cv-editor-diff";
import { cvEditorExtensions, loadCvHtml } from "../cv-editor-structure";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych przez Firmę Przykładową.";
const CLAUSE_P = `<p data-cv-section="rodo">${CLAUSE}</p>`;
const OTHER_CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych przez Inną Firmę sp. z o.o. w celu rekrutacji.";

const HEAD =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad 7 lat doświadczenia w <strong>Javie</strong>.</p></li>" +
  "<li><p>Dobrze odnajduje się w zespole.</p></li></ul>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>';
const TAIL =
  '<p data-cv-section="technologies">Technologie: Java, Kafka</p>' +
  '<p data-cv-section="role"><strong>Developer</strong> 2017 – 2021</p>' +
  '<p data-cv-section="employer">Software House Przykład · IT</p>';

const CV =
  HEAD +
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong>.</p></li>" +
  "<li><p>Udział w planowaniu sprintów.</p></li>" +
  "<li><p>Udział w spotkaniach zespołu.</p></li></ul>" +
  TAIL +
  "<ul><li><p>Usługi REST w Java 11.</p></li></ul>" +
  CLAUSE_P;

/** Starsza zatwierdzona wersja: jeden punkt zmieniony, jeden tylko tutaj, jednego jeszcze nie było. */
const VERSION =
  HEAD +
  "<ul><li><p>Rozwój usług w <strong>Java 11</strong>.</p></li>" +
  "<li><p>Udział w planowaniu sprintów.</p></li></ul>" +
  TAIL +
  "<ul><li><p>Usługi REST w Java 11.</p></li><li><p>Dyżury wsparcia produkcyjnego.</p></li></ul>" +
  CLAUSE_P;

/** Treść z pliku Word: opakowanie, punkty bez akapitu, h3, klauzula jako `p.rodo` z INNYM tekstem. */
function wordHtml(clause: string): string {
  return (
    '<article class="cv">' +
    "<h1>Dev – Anna Przykładowa</h1>" +
    '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
    '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
    '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' +
    '<p data-cv-section="duties_label">Zakres zadań:</p>' +
    "<ul><li>Rozwój usług w <strong>Java 17</strong> i Kotlinie.</li><li>Udział w planowaniu sprintów.</li></ul>" +
    '<p data-cv-section="technologies">Technologie: Java, Kafka, Docker</p>' +
    "<h3>Projekty dodatkowe</h3>" +
    "<p>Mentoring młodszych programistów.</p>" +
    clause +
    "</article>"
  );
}

/** Ta sama treść w kształcie edytora, z klauzulą bieżącego CV na końcu. */
const WORD_IN_EDITOR =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong> i Kotlinie.</p></li><li><p>Udział w planowaniu sprintów.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java, Kafka, Docker</p>' +
  "<h3>Projekty dodatkowe</h3>" +
  "<p>Mentoring młodszych programistów.</p>";

const editors: Editor[] = [];

function open(html = CV): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, html);
  editors.push(editor);
  return editor;
}

/** HTML tak, jak zapisałby go edytor po wczytaniu tej treści. */
function saved(html: string): string {
  return open(html).getHTML();
}

function replace(editor: Editor, incoming: string): boolean {
  const transaction = replaceContentStep(editor.state, incoming);
  if (!transaction) return false;
  editor.view.dispatch(transaction);
  return true;
}

function diff(editor: Editor, incoming: string) {
  return diffLines(contentLines(editor.state.doc), contentLines(htmlToDoc(editor.schema, incoming)));
}

const line = (text: string): CvDiffLine => ({ text, place: null });

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("wiersze do porównania", () => {
  it("każdy blok tekstu to wiersz — także punkt zagnieżdżonej listy; klauzula, pusty akapit i linia nie", () => {
    const editor = open(
      "<h1>CV</h1><hr><p></p>" +
        '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
        '<p data-cv-section="role"><strong>Developer</strong> 2021 – 2024</p>' +
        "<ul><li><p>Projekt płatności</p><ul><li><p>Usługi w <strong>Java 17</strong></p></li></ul></li></ul>" +
        "<h2>ZAINTERESOWANIA</h2><p>Żeglarstwo,<br>fotografia.</p>" +
        CLAUSE_P,
    );
    expect(contentLines(editor.state.doc)).toEqual([
      { text: "CV", place: null },
      { text: "DOŚWIADCZENIE", place: null },
      { text: "**Developer** 2021 – 2024", place: "DOŚWIADCZENIE" },
      { text: "Projekt płatności", place: "Developer 2021 – 2024" },
      { text: "Usługi w **Java 17**", place: "Developer 2021 – 2024" },
      { text: "ZAINTERESOWANIA", place: null },
      // Twarde złamanie wiersza to odstęp, nie sklejone słowa.
      { text: "Żeglarstwo, fotografia.", place: "ZAINTERESOWANIA" },
    ]);
  });

  it("treść z pliku Word daje te same wiersze co ta sama treść w kształcie edytora", () => {
    const editor = open();
    const word = contentLines(htmlToDoc(editor.schema, wordHtml(`<p class="rodo">${OTHER_CLAUSE}</p>`)));
    expect(word).toEqual(contentLines(open(WORD_IN_EDITOR + CLAUSE_P).state.doc));
    expect(word.some((item) => item.text.includes("Wyrażam zgodę"))).toBe(false);
  });
});

describe("różnice wiersz po wierszu", () => {
  it("zmieniony, dodany i usunięty wiersz — każdy z miejscem w CV", () => {
    expect(diff(open(), VERSION)).toEqual([
      {
        kind: "changed",
        before: "Rozwój usług w **Java 17**.",
        after: "Rozwój usług w **Java 11**.",
        place: "Senior Developer 2021 – 2024",
      },
      { kind: "removed", before: "Udział w spotkaniach zespołu.", place: "Senior Developer 2021 – 2024" },
      { kind: "added", after: "Dyżury wsparcia produkcyjnego.", place: "Developer 2017 – 2021" },
    ]);
  });

  it("usunięte i dodane obok siebie łączą się po kolei; nadwyżka zostaje usunięta albo dodana", () => {
    const stay = line("zostaje");
    expect(diffLines([line("a"), line("b"), line("c"), stay], [line("x"), line("y"), stay])).toEqual([
      { kind: "changed", before: "a", after: "x", place: null },
      { kind: "changed", before: "b", after: "y", place: null },
      { kind: "removed", before: "c", place: null },
    ]);
    expect(diffLines([stay, line("a")], [stay, line("x"), line("y"), line("z")])).toEqual([
      { kind: "changed", before: "a", after: "x", place: null },
      { kind: "added", after: "y", place: null },
      { kind: "added", after: "z", place: null },
    ]);
    // Wspólny wiersz rozdziela zmiany: nie łączymy usunięcia z dodaniem po drugiej jego stronie.
    expect(diffLines([line("a"), stay], [stay, line("x")])).toEqual([
      { kind: "removed", before: "a", place: null },
      { kind: "added", after: "x", place: null },
    ]);
  });

  it("przestawiony wiersz to usunięcie w jednym miejscu i dodanie w drugim", () => {
    const [a, b, c] = [line("a"), line("b"), line("c")];
    expect(diffLines([a, b, c], [b, c, a])).toEqual([
      { kind: "removed", before: "a", place: null },
      { kind: "added", after: "a", place: null },
    ]);
  });

  it("zmiana pogrubienia jest różnicą, zmiana odstępów w zapisie HTML nie", () => {
    const editor = open("<h1>CV</h1><p>Rozwój usług w <strong>Java 17</strong>.</p>");
    expect(diff(editor, "<h1>CV</h1>\n  <p>Rozwój   usług w\n<strong>Java 17</strong>.</p>")).toEqual([]);
    expect(diff(editor, "<h1>CV</h1><p>Rozwój usług w Java 17.</p>")).toEqual([
      { kind: "changed", before: "Rozwój usług w **Java 17**.", after: "Rozwój usług w Java 17.", place: null },
    ]);
  });

  it("ta sama treść nie ma różnic — także gdy różni się tylko klauzula", () => {
    const editor = open();
    expect(diff(editor, CV)).toEqual([]);
    expect(diff(editor, CV.replace(CLAUSE, OTHER_CLAUSE))).toEqual([]);
    expect(diffLines([], [])).toEqual([]);
  });

  it("powyżej limitu wierszy nie porównuje wcale", () => {
    const many = Array.from({ length: CV_DIFF_LINES_MAX + 1 }, (_, index) => line(`wiersz ${index}`));
    expect(diffLines(many, [line("a")])).toBeNull();
    expect(diffLines([line("a")], many)).toBeNull();
    // Dokładnie na limicie po obu stronach porównanie jeszcze działa.
    const limit = many.slice(1);
    expect(diffLines(limit, [...limit.slice(0, 300), line("nowy"), ...limit.slice(301)])).toEqual([
      { kind: "changed", before: "wiersz 301", after: "nowy", place: null },
    ]);
    expect(diffLines(limit.slice(1), [...limit.slice(1, 300), line("nowy"), ...limit.slice(300)])).toEqual([
      { kind: "added", after: "nowy", place: null },
    ]);
  });
});

describe("zastąpienie treści edytora", () => {
  it("ta sama treść niczego nie zmienia", () => {
    const editor = open();
    expect(replaceContentStep(editor.state, CV)).toBeNull();
    expect(replaceContentStep(editor.state, editor.getHTML())).toBeNull();
    expect(replaceContentStep(editor.state, htmlToDoc(editor.schema, CV))).toBeNull();
  });

  it("przywrócenie wersji: zamienia tylko różniące się bloki, a jedno „Cofnij” wraca do treści sprzed zmiany", () => {
    const editor = open();
    const before = editor.getHTML();
    const transaction = replaceContentStep(editor.state, VERSION);
    // Dwie małe zamiany — po jednej w każdej zmienionej liście — a nie jedna na pół dokumentu.
    expect(transaction?.steps).toHaveLength(2);
    editor.view.dispatch(transaction!);
    expect(editor.getHTML()).toBe(saved(VERSION));
    expect(editor.getHTML()).toContain("<li><p>Dyżury wsparcia produkcyjnego.</p></li>");
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
    expect(editor.can().undo()).toBe(false);
  });

  it.each([
    ["inną klauzulą jako p.rodo", `<p class="rodo">${OTHER_CLAUSE}</p>`],
    ["inną klauzulą rozpoznaną po pierwszych słowach", `<p>${OTHER_CLAUSE}</p>`],
    ["tą samą klauzulą", CLAUSE_P],
    ["bez klauzuli", ""],
  ])("treść z pliku Word z %s: treść z pliku, klauzula bieżącego CV na końcu", (_name, clause) => {
    const editor = open();
    const before = editor.getHTML();
    expect(replace(editor, wordHtml(clause))).toBe(true);
    const html = editor.getHTML();
    expect(html).toBe(saved(WORD_IN_EDITOR + CLAUSE_P));
    expect(html).not.toContain("Inną Firmę");
    expect(html.match(/Wyrażam zgodę/g)).toHaveLength(1);
    expect(html.endsWith(`${CLAUSE}</p>`)).toBe(true);
    // Punkt bez akapitu dostał akapit, a nagłówek h3 został nagłówkiem.
    expect(html).toContain("<ul><li><p>Rozwój usług w <strong>Java 17</strong> i Kotlinie.</p></li>");
    expect(html).toContain("<h3>Projekty dodatkowe</h3><p>Mentoring młodszych programistów.</p>");
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("klauzula w środku treści przychodzącej znika stamtąd — bieżąca zostaje na końcu", () => {
    const editor = open();
    const before = editor.getHTML();
    const moved = wordHtml("").replace("<h3>", `<p class="rodo">${OTHER_CLAUSE}</p><p>${CLAUSE}</p><h3>`);
    expect(replace(editor, moved)).toBe(true);
    expect(editor.getHTML()).toBe(saved(WORD_IN_EDITOR + CLAUSE_P));
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("znaczniki struktury z treści przychodzącej zostają (stanowisko, firma, etykiety, sekcje)", () => {
    const editor = open("<h1>Stare CV</h1><p>Bez znaczników.</p>" + CLAUSE_P);
    expect(replace(editor, wordHtml(""))).toBe(true);
    const html = editor.getHTML();
    for (const marker of ["experience", "role", "employer", "duties_label", "technologies"]) {
      expect(html).toContain(`data-cv-section="${marker}"`);
    }
    expect(html).toContain('<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>');
    expect(html).toContain('<p data-cv-section="technologies">Technologie: Java, Kafka, Docker</p>');
  });

  it("wtyczka struktury nie odrzuca zmiany i niczego po niej nie naprawia", () => {
    const editor = open();
    const transaction = replaceContentStep(editor.state, wordHtml(`<p class="rodo">${OTHER_CLAUSE}</p>`))!;
    const applied = editor.state.applyTransaction(transaction);
    // Odrzucona transakcja dałaby pustą listę, naprawa — drugą transakcję.
    expect(applied.transactions).toHaveLength(1);
    expect(applied.state.doc.eq(transaction.doc)).toBe(true);
    // Sama klauzula nie jest ruszana: jej węzeł po zmianie to ten sam węzeł.
    expect(applied.state.doc.lastChild).toBe(editor.state.doc.lastChild);
  });

  it.each(["Wolontariat.", "Wyrażam się jasno.", "Jazda konna."])(
    "klauzula bez znacznika (starsze CV): akapit „%s” dopisany tuż przed nią nie rozcina klauzuli",
    (added) => {
      // Bez znacznika klauzula i zwykły akapit mają tę samą budowę, więc najmniejsza
      // zamiana zaczynała się W ŚRODKU klauzuli („W…” jak „Wyrażam…”), a wtyczka
      // struktury odrzucała taką transakcję po cichu.
      const editor = open(`<h1>CV</h1><p>Opis.</p><p>${CLAUSE}</p>`);
      const before = editor.getHTML();
      const incoming = `<h1>CV</h1><p>Opis.</p><p>${added}</p><p>${CLAUSE}</p>`;
      const transaction = replaceContentStep(editor.state, incoming)!;
      expect(editor.state.applyTransaction(transaction).transactions).toEqual([transaction]);
      editor.view.dispatch(transaction);
      expect(editor.getHTML()).toBe(saved(incoming));
      editor.commands.undo();
      expect(editor.getHTML()).toBe(before);
    },
  );

  it("CV bez klauzuli zostaje bez niej — klauzuli z pliku nie przyjmujemy", () => {
    const editor = open("<h1>CV</h1><p>Stara treść.</p>");
    const before = editor.getHTML();
    expect(replace(editor, wordHtml(`<p class="rodo">${OTHER_CLAUSE}</p>`))).toBe(true);
    expect(editor.getHTML()).toBe(saved(WORD_IN_EDITOR));
    expect(editor.getHTML()).not.toContain("Wyrażam zgodę");
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("plik z samą klauzulą nie zostawia pustego dokumentu ani cudzej klauzuli", () => {
    const editor = open();
    expect(replace(editor, `<p class="rodo">${OTHER_CLAUSE}</p>`)).toBe(true);
    expect(editor.getHTML()).toBe(saved(CLAUSE_P));
    const bare = open("<h1>CV</h1>");
    expect(replace(bare, `<p class="rodo">${OTHER_CLAUSE}</p>`)).toBe(true);
    expect(bare.getHTML()).toBe("<p></p>");
  });

  it("bieżące CV z klauzulą nie na końcu (stary zapis): po zmianie jedna klauzula, na końcu", () => {
    // Wczytanie omija naprawę wtyczki — taki dokument trafia do edytora, jaki jest zapisany.
    const editor = open(`<h1>CV</h1>${CLAUSE_P}<p>Dopisek pod klauzulą.</p>`);
    const before = editor.getHTML();
    expect(replace(editor, wordHtml(""))).toBe(true);
    expect(editor.getHTML()).toBe(saved(WORD_IN_EDITOR + CLAUSE_P));
    // „Cofnij” to też zmiana, więc wtyczka przenosi klauzulę na koniec — jak po
    // każdej innej edycji takiego dokumentu. Treść wraca cała.
    editor.commands.undo();
    expect(editor.getHTML()).not.toBe(before);
    expect(editor.getHTML()).toBe(saved(`<h1>CV</h1><p>Dopisek pod klauzulą.</p>${CLAUSE_P}`));
  });

  it("policzenie różnic i przygotowanie zmiany nie rusza edytora", () => {
    const editor = open();
    const state = editor.state;
    const html = editor.getHTML();
    const seen = vi.fn();
    editor.on("transaction", seen);
    editor.on("update", seen);
    const incoming = htmlToDoc(editor.schema, wordHtml(`<p class="rodo">${OTHER_CLAUSE}</p>`));
    expect(diffLines(contentLines(editor.state.doc), contentLines(incoming))?.length).toBeGreaterThan(0);
    expect(replaceContentStep(editor.state, incoming)).not.toBeNull();
    expect(seen).not.toHaveBeenCalled();
    expect(editor.state).toBe(state);
    expect(editor.getHTML()).toBe(html);
    expect(editor.can().undo()).toBe(false);
    expect(editor.view.dom.querySelector(".cv-rodo-locked")).not.toBeNull();
  });
});

// ── Dowolna treść ────────────────────────────────────────────────────────────

/** Powtarzalny generator liczb z [0, 1). */
function random(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

// „Wyrażam”, „Wyniki”: akapit zaczynający się jak klauzula zgody, ale nią niebędący.
const WORDS = ["Java", "Kafka", "bank", "zespół", "usługi", "testy", "REST", "sprint", "płatności", "kod", "Wyrażam", "Wyniki"];

function sentence(next: () => number): string {
  const words = Array.from({ length: 2 + Math.floor(next() * 4) }, () => WORDS[Math.floor(next() * WORDS.length)]);
  if (next() < 0.4) words[0] = `<strong>${words[0]}</strong>`;
  return words.join(" ");
}

function list(next: () => number, tag: "ul" | "ol"): string {
  const items = Array.from({ length: 1 + Math.floor(next() * 4) }, () => {
    const nested = next() < 0.2 ? `<ul><li><p>${sentence(next)}</p></li></ul>` : "";
    return `<li><p>${sentence(next)}</p>${nested}</li>`;
  });
  return `<${tag}>${items.join("")}</${tag}>`;
}

function block(next: () => number): string {
  switch (Math.floor(next() * 9)) {
    case 0:
      return '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>';
    case 1:
      return `<p data-cv-section="role"><strong>${sentence(next)}</strong> 2020 – 2024</p>`;
    case 2:
      return `<p data-cv-section="employer">${sentence(next)}</p>`;
    case 3:
      return list(next, "ol");
    case 4:
      return "<hr>";
    case 5:
      return `<h3>${sentence(next)}</h3>`;
    case 6:
    case 7:
      return list(next, "ul");
    default:
      return `<p>${sentence(next)}</p>`;
  }
}

describe("dowolna treść przychodząca", () => {
  it("po zmianie dokument to treść przychodząca z bieżącą klauzulą, a „Cofnij” wraca dokładnie", () => {
    let changed = 0;
    // 60 losowych dokumentów: 200 mieściło się w limicie tylko na wolnej maszynie.
    for (let seed = 1; seed <= 60; seed += 1) {
      const next = random(seed);
      const current = Array.from({ length: 1 + Math.floor(next() * 8) }, () => block(next));
      // Treść przychodząca: bieżąca po kilku usunięciach, wstawkach i podmianach.
      const incoming = current.flatMap((item) => {
        const roll = next();
        if (roll < 0.15) return [];
        if (roll < 0.3) return [block(next)];
        if (roll < 0.45) return [item, block(next)];
        return [item];
      });
      // Starsze CV mają klauzulę bez znacznika — poznajemy ją po pierwszych słowach.
      const own = next() < 0.5 ? CLAUSE_P : `<p>${CLAUSE}</p>`;
      const clause = [CLAUSE_P, `<p class="rodo">${OTHER_CLAUSE}</p>`, ""][Math.floor(next() * 3)];
      // Klauzula przychodząca stoi na końcu albo w środku treści.
      incoming.splice(next() < 0.3 ? Math.floor(next() * (incoming.length + 1)) : incoming.length, 0, clause);
      const body = incoming.filter((item) => item !== clause || clause === "").join("");

      const editor = open(`<h1>CV</h1>${current.join("")}${own}`);
      const before = editor.getHTML();
      const expected = saved(`<h1>CV</h1>${body}${own}`);
      const applied = replace(editor, `<article><h1>CV</h1>${incoming.join("")}</article>`);
      expect(applied, `ziarno ${seed}`).toBe(expected !== before);
      expect(editor.getHTML(), `ziarno ${seed}`).toBe(expected);
      if (applied) {
        changed += 1;
        editor.commands.undo();
        expect(editor.getHTML(), `ziarno ${seed}: cofnięcie`).toBe(before);
      }
      while (editors.length) editors.pop()?.destroy();
    }
    // Test nie jest pusty: prawie każda próba coś zmienia.
    expect(changed).toBeGreaterThan(30);
    // Jawny limit: każda próba zakłada prawdziwy edytor; na obciążonym runnerze
    // domyślne 5 s bywało za mało.
  }, 30_000);
});
