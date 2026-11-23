import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { CvEditorSection } from "../cv-editor-section";
import { canMoveRoleAt, cvOutline, insertRole, moveRoleAt, type CvCommand } from "../cv-editor-blocks";
import {
  addRoleDuty,
  allRoleFields,
  fieldText,
  joinPeriod,
  page1Summaries,
  parsePeriod,
  removeRoleDuty,
  roleDuration,
  roleFields,
  sectionStart,
  setRoleCompany,
  setRoleDuty,
  setRolePeriod,
  setRoleTechnologies,
  setRoleTitle,
  setWhyPoint,
  splitPeriod,
  tenureHint,
  whyPoints,
} from "../cv-new-layout-form";

const RODO = '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>';
const ROLE_A =
  '<p data-cv-section="role"><strong>Senior Java Developer</strong> 03.2021 – 06.2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy S.A. · Bankowość</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Mikroserwisy płatności w <strong>Java 17</strong>.</p></li><li><p>Przeglądy kodu.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 17, <strong>Kafka</strong></p>';
const ROLE_B =
  '<p data-cv-section="role"><strong>Java Developer</strong> 01.2017 – 02.2021</p>' +
  '<p data-cv-section="employer">Software House Przykład</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Usługi REST.</p></li></ul>";
const CV =
  "<h1>Senior Java Developer – Anna Przykładowa</h1><hr>" +
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad <strong>7 lat</strong> w Javie.</p></li><li><p>Mikroserwisy w <strong>Spring Boot</strong>.</p></li>" +
  "<li><p>Trzeci punkt.</p></li></ul>" +
  '<h2 data-cv-section="education">EDUKACJA</h2>' +
  "<p>2012 – 2017 <strong>Politechnika Przykładowa</strong> — Informatyka</p>" +
  '<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2>' +
  "<p><strong>Języki: </strong>Java, Kotlin</p><p><strong>Narzędzia: </strong>Docker</p>" +
  '<h2 data-cv-section="languages">JĘZYKI</h2><p>polski – ojczysty</p><p>angielski – B2</p>' +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  ROLE_A +
  ROLE_B +
  RODO;

const editors: Editor[] = [];

function open(content: string = CV): Editor {
  const editor = new Editor({ extensions: [StarterKit, CvEditorSection], content });
  editors.push(editor);
  return editor;
}

function run(editor: Editor, command: CvCommand): boolean {
  const tr = command(editor.state);
  if (!tr) return false;
  editor.view.dispatch(tr);
  return true;
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

// Listopad 2026 jako indeks miesiąca (rok * 12 + miesiąc - 1).
const NOW = 2026 * 12 + 10;

describe("„Dlaczego nasz kandydat” w formularzu", () => {
  it("czyta punkty sekcji w kolejności CV", () => {
    const editor = open();
    expect(whyPoints(editor.state.doc).map((point) => point.text)).toEqual([
      "Ponad 7 lat w Javie.",
      "Mikroserwisy w Spring Boot.",
      "Trzeci punkt.",
    ]);
  });

  it("zmienia tylko różniący się fragment — pogrubienie zostaje", () => {
    const editor = open();
    expect(run(editor, setWhyPoint(0, "Ponad 7 lat w Javie i Kotlinie."))).toBe(true);
    expect(editor.getHTML()).toContain("<li><p>Ponad <strong>7 lat</strong> w Javie i Kotlinie.</p></li>");
    expect(run(editor, setWhyPoint(1, "Mikroserwisy w Spring Boot 3."))).toBe(true);
    expect(editor.getHTML()).toContain("Mikroserwisy w <strong>Spring Boot</strong> 3.");
    // Cyfra doklejona do pogrubionej liczby zostaje w pogrubieniu.
    run(editor, setWhyPoint(0, "Ponad 17 lat w Javie i Kotlinie."));
    expect(editor.getHTML()).toContain("<li><p>Ponad <strong>17 lat</strong> w Javie i Kotlinie.</p></li>");
  });

  it("ta sama treść albo brak punktu = brak transakcji", () => {
    const editor = open();
    expect(setWhyPoint(0, "Ponad 7 lat w Javie.")(editor.state)).toBeNull();
    expect(setWhyPoint(5, "Nowy")(editor.state)).toBeNull();
  });

  it("nowa linia w polu staje się odstępem", () => {
    expect(fieldText("Ponad 7 lat\nw Javie")).toBe("Ponad 7 lat w Javie");
    const editor = open();
    run(editor, setWhyPoint(2, "Trzeci\npunkt."));
    expect(whyPoints(editor.state.doc)[2].text).toBe("Trzeci punkt.");
  });

  it("zmiana w formularzu cofa się jak pisanie (historia edytora)", () => {
    const editor = open();
    run(editor, setWhyPoint(0, "Inny punkt."));
    editor.commands.undo();
    expect(whyPoints(editor.state.doc)[0].text).toBe("Ponad 7 lat w Javie.");
  });

  it("podpowiedź lat liczy cały staż z dat stanowisk", () => {
    const editor = open();
    // 01.2017 – 06.2024 bez przerwy = 7 lat 6 mies.
    expect(tenureHint(editor.state.doc, NOW)).toBe("Z dat stanowisk: 7 lat 6 mies.");
    expect(tenureHint(open(`<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>${RODO}`).state.doc, NOW)).toBeNull();
  });
});

describe("Stanowisko w formularzu", () => {
  it("czyta okres, firmę, stanowisko, obowiązki i technologie", () => {
    const editor = open();
    expect(roleFields(editor.state.doc, 0)).toEqual({
      index: 0,
      title: "Senior Java Developer",
      period: "03.2021 – 06.2024",
      company: "Bank Przykładowy S.A. · Bankowość",
      duties: ["Mikroserwisy płatności w Java 17.", "Przeglądy kodu."],
      technologies: "Java 17, Kafka",
    });
    expect(roleFields(editor.state.doc, 1)?.technologies).toBeNull();
    expect(roleFields(editor.state.doc, 2)).toBeNull();
  });

  it("nazwa stanowiska zostaje pogrubiona, daty — zwykłym tekstem", () => {
    const editor = open();
    run(editor, setRoleTitle(0, "Lead Java Developer"));
    run(editor, setRolePeriod(0, "03.2021 – obecnie"));
    expect(editor.getHTML()).toContain(
      '<p data-cv-section="role"><strong>Lead Java Developer</strong> 03.2021 – obecnie</p>',
    );
  });

  it("wyczyszczona i wpisana od nowa nazwa wraca pogrubiona", () => {
    const editor = open();
    run(editor, setRoleTitle(1, ""));
    expect(roleFields(editor.state.doc, 1)?.title).toBe("");
    run(editor, setRoleTitle(1, "Programista"));
    expect(editor.getHTML()).toContain('<p data-cv-section="role"><strong>Programista</strong> 01.2017 – 02.2021</p>');
  });

  it("firma, punkt obowiązków i technologie piszą do akapitów stanowiska", () => {
    const editor = open();
    run(editor, setRoleCompany(1, "Software House Przykład sp. z o.o."));
    run(editor, setRoleDuty(0, 1, "Przeglądy kodu i mentoring."));
    run(editor, setRoleTechnologies(0, "Java 17, Kafka, Docker", "pl"));
    const html = editor.getHTML();
    expect(html).toContain('<p data-cv-section="employer">Software House Przykład sp. z o.o.</p>');
    expect(html).toContain("<li><p>Przeglądy kodu i mentoring.</p></li>");
    // Etykieta szablonu zostaje dokładnie ta sama, pogrubienie technologii też.
    expect(html).toContain('<p data-cv-section="technologies">Technologie: Java 17, <strong>Kafka</strong>, Docker</p>');
  });

  it("stanowisko bez technologii dostaje akapit z etykietą szablonu", () => {
    const editor = open();
    run(editor, setRoleTechnologies(1, "Java 11", "pl"));
    expect(roleFields(editor.state.doc, 1)?.technologies).toBe("Java 11");
    expect(editor.getHTML()).toContain('<p data-cv-section="technologies">Technologie: Java 11</p>');
    expect(setRoleTechnologies(1, "", "pl")(open().state)).toBeNull();
  });

  it("punkt obowiązków: dopisanie pustego i usunięcie; ostatni znika z listą i etykietą", () => {
    const editor = open();
    run(editor, addRoleDuty(1, "pl"));
    expect(roleFields(editor.state.doc, 1)?.duties).toEqual(["Usługi REST.", ""]);
    run(editor, removeRoleDuty(1, 0));
    run(editor, removeRoleDuty(1, 0));
    expect(roleFields(editor.state.doc, 1)?.duties).toEqual([]);
    expect(editor.getHTML()).not.toContain("Software House Przykład</p><p data-cv-section=\"duties_label\">");
    // Bez listy pierwszy punkt przywraca etykietę „Zakres zadań:”.
    run(editor, addRoleDuty(1, "pl"));
    expect(editor.getHTML()).toContain(
      '<p data-cv-section="employer">Software House Przykład</p><p data-cv-section="duties_label">Zakres zadań:</p><ul><li><p></p></li></ul>',
    );
  });

  it("przestawia stanowiska po numerze, bez kursora", () => {
    const editor = open();
    const outline = cvOutline(editor.state.doc);
    expect(canMoveRoleAt(outline, 0, -1)).toBe(false);
    expect(canMoveRoleAt(outline, 0, 1)).toBe(true);
    run(editor, moveRoleAt(0, 1));
    expect(allRoleFields(editor.state.doc).map((role) => role.title)).toEqual([
      "Java Developer",
      "Senior Java Developer",
    ]);
    run(editor, moveRoleAt(1, -1));
    expect(allRoleFields(editor.state.doc).map((role) => role.title)).toEqual([
      "Senior Java Developer",
      "Java Developer",
    ]);
    expect(moveRoleAt(1, 1)(editor.state)).toBeNull();
  });

  it("nowe stanowisko staje za wskazanym", () => {
    const editor = open();
    run(editor, insertRole("pl", 0));
    expect(allRoleFields(editor.state.doc).map((role) => role.title)).toEqual([
      "Senior Java Developer",
      "[Stanowisko]",
      "Java Developer",
    ]);
  });
});

describe("Daty i podsumowania", () => {
  it("okres z linii stanowiska", () => {
    expect(parsePeriod("03.2021 – 06.2024")).toEqual({ start: "2021-03", end: "2024-06" });
    expect(parsePeriod("12.2025 – obecnie")).toEqual({ start: "2025-12", end: null });
    expect(parsePeriod("2015 – 2016")).toEqual({ start: "2015", end: "2016" });
    expect(parsePeriod("bez dat")).toBeNull();
    expect(roleDuration("12.2025 – obecnie", NOW)).toBe("1 rok");
    expect(roleDuration("[MM.RRRR – MM.RRRR]", NOW)).toBeNull();
  });

  it("dwa pola okresu", () => {
    expect(splitPeriod("03.2021 – 06.2024")).toEqual({ start: "03.2021", end: "06.2024" });
    expect(splitPeriod("03.2021 - obecnie")).toEqual({ start: "03.2021", end: "obecnie" });
    expect(splitPeriod("2019")).toEqual({ start: "2019", end: "" });
    expect(joinPeriod("03.2021", "obecnie")).toBe("03.2021 – obecnie");
    expect(joinPeriod("03.2021", " ")).toBe("03.2021");
    // Samo „do” nie przeskakuje do pola „od”.
    expect(joinPeriod("", "06.2024")).toBe("– 06.2024");
    expect(splitPeriod("– 06.2024")).toEqual({ start: "", end: "06.2024" });
  });

  it("podsumowania zwiniętych wierszy", () => {
    const summaries = page1Summaries(open().state.doc);
    expect(summaries).toEqual({
      career: "2 firmy na osi",
      skills: "2 kategorie",
      education: "2012 – 2017 Politechnika Przykładowa — Informatyka",
      languages: "polski – ojczysty · angielski – B2",
    });
  });

  it("kursor na początku sekcji", () => {
    const editor = open();
    const at = sectionStart(editor.state.doc, "skills");
    expect(at).not.toBeNull();
    expect(editor.state.doc.resolve(at as number).parent.textContent).toBe("Języki: Java, Kotlin");
    expect(sectionStart(editor.state.doc, "certifications")).toBeNull();
  });
});
