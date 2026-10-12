import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { CvEditorSection } from "../cv-editor-section";
import {
  CV_PLACEHOLDERS,
  CV_TEMPLATE_LABELS,
  blockKindOf,
  cvContext,
  cvOutline,
  cvPlaceholders,
  deleteRole,
  duplicateRole,
  insertBullet,
  insertRole,
  insertRow,
  moveRole,
  runCvCommand,
  setBlockKind,
} from "../cv-editor-blocks";

const RODO = '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>';
const ROLE_A =
  '<p data-cv-section="role"><strong>Senior Java Developer</strong> 03.2021 – 06.2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy S.A.</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Mikroserwisy płatności.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 17</p>';
const ROLE_B =
  '<p data-cv-section="role"><strong>Java Developer</strong> 01.2017 – 02.2021</p>' +
  '<p data-cv-section="employer">Software House Przykład</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Usługi REST.</p></li></ul>";
/** Kształt CV z generatora po przejściu przez edytor. */
const CV =
  "<h1>Senior Java Developer – Anna Przykładowa</h1><hr>" +
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2><ul><li><p>Ponad 7 lat w Javie.</p></li></ul>' +
  '<h2 data-cv-section="education">EDUKACJA</h2>' +
  "<p>2012 – 2017 <strong>Politechnika Przykładowa</strong> — Informatyka</p>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  ROLE_A +
  ROLE_B +
  RODO;

const editors: Editor[] = [];

function open(content: string): Editor {
  const editor = new Editor({ extensions: [StarterKit, CvEditorSection], content });
  editors.push(editor);
  return editor;
}

/** Kursor w tekście `text` (pierwsze wystąpienie). */
function caretIn(editor: Editor, text: string): void {
  let at = -1;
  editor.state.doc.descendants((node, position) => {
    const offset = node.isText ? (node.text ?? "").indexOf(text) : -1;
    if (at < 0 && offset >= 0) at = position + offset + 1;
  });
  expect(at, `brak tekstu „${text}”`).toBeGreaterThan(0);
  editor.commands.setTextSelection(at);
}

function roleTitles(editor: Editor): string[] {
  return cvOutline(editor.state.doc).roles.map((role) => role.title);
}

function lastBlockIsRodo(editor: Editor): boolean {
  const { blocks, rodo } = cvOutline(editor.state.doc);
  return rodo !== null && rodo === blocks[blocks.length - 1];
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("odczyt struktury", () => {
  it("widzi sekcje, stanowiska i klauzulę zgody", () => {
    const outline = cvOutline(open(CV).state.doc);
    expect(outline.sections.map((section) => section.key)).toEqual([
      "why_points",
      "education",
      "experience",
    ]);
    expect(outline.roles.map((role) => role.title)).toEqual([
      "Senior Java Developer 03.2021 – 06.2024",
      "Java Developer 01.2017 – 02.2021",
    ]);
    // Stanowisko kończy się przed następnym, a ostatnie przed klauzulą.
    const [first, second] = outline.roles;
    expect(first.toIndex).toBe(second.fromIndex);
    expect(second.toIndex).toBe(outline.rodo?.index);
    expect(outline.sections[2].endIndex).toBe(outline.rodo?.index);
  });

  it("rozpoznaje sekcję po tytule szablonu, gdy nagłówek nie ma znacznika", () => {
    const outline = cvOutline(open("<h2>EXPERIENCE</h2><p>Acme</p><h2>Skills</h2>").state.doc);
    expect(outline.sections.map((section) => section.key)).toEqual(["experience", "skills"]);
  });

  it("opisuje miejsce kursora", () => {
    const editor = open(CV);
    caretIn(editor, "Usługi REST.");
    const inList = cvContext(editor.state);
    expect(inList.role?.title).toContain("Java Developer 01.2017");
    expect(inList).toMatchObject({ inList: true, section: "experience", canMoveUp: true, canMoveDown: false });
    caretIn(editor, "Wyrażam zgodę");
    expect(cvContext(editor.state)).toMatchObject({ locked: true, role: null });
    caretIn(editor, "Politechnika");
    expect(cvContext(editor.state)).toMatchObject({ section: "education", role: null, inList: false });
  });
});

describe("stanowiska", () => {
  it("przenosi stanowisko w górę i w dół razem z całą jego treścią", () => {
    const editor = open(CV);
    caretIn(editor, "Usługi REST.");
    expect(runCvCommand(editor, moveRole(-1))).toBe(true);
    expect(roleTitles(editor)).toEqual([
      "Java Developer 01.2017 – 02.2021",
      "Senior Java Developer 03.2021 – 06.2024",
    ]);
    // Kursor zostaje w przeniesionym stanowisku, więc można je cofnąć jednym kliknięciem.
    expect(cvContext(editor.state).role?.title).toContain("Java Developer 01.2017");
    expect(runCvCommand(editor, moveRole(1))).toBe(true);
    expect(editor.getHTML()).toBe(open(CV).getHTML());
  });

  it("nie przenosi poza pierwsze i ostatnie stanowisko", () => {
    const editor = open(CV);
    caretIn(editor, "Mikroserwisy płatności.");
    expect(moveRole(-1)(editor.state)).toBeNull();
    caretIn(editor, "Usługi REST.");
    expect(moveRole(1)(editor.state)).toBeNull();
    caretIn(editor, "Politechnika");
    expect(moveRole(1)(editor.state)).toBeNull();
    expect(duplicateRole(editor.state)).toBeNull();
    expect(deleteRole(editor.state)).toBeNull();
  });

  it("powiela stanowisko pod oryginałem", () => {
    const editor = open(CV);
    caretIn(editor, "Bank Przykładowy");
    expect(runCvCommand(editor, duplicateRole)).toBe(true);
    expect(roleTitles(editor)).toEqual([
      "Senior Java Developer 03.2021 – 06.2024",
      "Senior Java Developer 03.2021 – 06.2024",
      "Java Developer 01.2017 – 02.2021",
    ]);
    expect(editor.getHTML().match(/Mikroserwisy płatności\./g)).toHaveLength(2);
    expect(lastBlockIsRodo(editor)).toBe(true);
  });

  it("usuwa ostatnie stanowisko, a klauzula zgody zostaje", () => {
    const editor = open(CV);
    caretIn(editor, "Usługi REST.");
    expect(runCvCommand(editor, deleteRole)).toBe(true);
    expect(roleTitles(editor)).toEqual(["Senior Java Developer 03.2021 – 06.2024"]);
    expect(editor.getHTML()).not.toContain("Software House Przykład");
    expect(lastBlockIsRodo(editor)).toBe(true);
  });

  it("nie usuwa stanowiska, które jest całym dokumentem", () => {
    const editor = open('<p data-cv-section="role"><strong>Dev</strong> 2020</p>');
    caretIn(editor, "Dev");
    expect(deleteRole(editor.state)).toBeNull();
  });

  it("wstawia nowe stanowisko pod bieżącym, z etykietami szablonu i polami do wypełnienia", () => {
    const editor = open(CV);
    caretIn(editor, "Mikroserwisy płatności.");
    expect(runCvCommand(editor, insertRole("pl"))).toBe(true);
    const fields = CV_PLACEHOLDERS.pl;
    expect(roleTitles(editor)).toEqual([
      "Senior Java Developer 03.2021 – 06.2024",
      `${fields.position} ${fields.dates}`,
      "Java Developer 01.2017 – 02.2021",
    ]);
    const html = editor.getHTML();
    expect(html).toContain(
      `<p data-cv-section="role"><strong>${fields.position}</strong> ${fields.dates}</p>` +
        `<p data-cv-section="employer">${fields.company}</p>` +
        `<p data-cv-section="duties_label">${CV_TEMPLATE_LABELS.pl.responsibilities}</p>` +
        `<ul><li><p>${fields.duty}</p></li></ul>` +
        `<p data-cv-section="technologies">${CV_TEMPLATE_LABELS.pl.technologies} ${fields.technologies}</p>`,
    );
    // Pierwsze pole jest zaznaczone: pisanie od razu je zastępuje.
    const { from, to } = editor.state.selection;
    expect(editor.state.doc.textBetween(from, to)).toBe(fields.position);
    expect(cvPlaceholders(html)).toEqual(
      expect.arrayContaining([fields.position, fields.dates, fields.company, fields.duty]),
    );
  });

  it("poza stanowiskiem dopisuje je na końcu doświadczenia, a bez sekcji zakłada ją przed klauzulą", () => {
    const withSection = open(CV);
    caretIn(withSection, "Politechnika");
    runCvCommand(withSection, insertRole("pl"));
    expect(roleTitles(withSection)).toHaveLength(3);
    expect(roleTitles(withSection)[2]).toContain(CV_PLACEHOLDERS.pl.position);
    expect(lastBlockIsRodo(withSection)).toBe(true);

    const without = open(`<h1>Dev – Anna</h1><h2 data-cv-section="skills">SKILLS</h2><p>Java</p>${RODO}`);
    caretIn(without, "Java");
    runCvCommand(without, insertRole("en"));
    const outline = cvOutline(without.state.doc);
    expect(outline.sections.map((section) => section.key)).toEqual(["skills", "experience"]);
    expect(without.getHTML()).toContain('<h2 data-cv-section="experience">EXPERIENCE</h2>');
    expect(without.getHTML()).toContain(`<p data-cv-section="duties_label">Tasks:</p>`);
    expect(lastBlockIsRodo(without)).toBe(true);
    const { from, to } = without.state.selection;
    expect(without.state.doc.textBetween(from, to)).toBe(CV_PLACEHOLDERS.en.position);
  });
});

describe("punkty i wiersze", () => {
  it("w liście wstawia pusty punkt pod bieżącym", () => {
    const editor = open(CV);
    caretIn(editor, "Mikroserwisy płatności.");
    expect(runCvCommand(editor, insertBullet("pl"))).toBe(true);
    editor.commands.insertContent("Nowy obowiązek.");
    expect(editor.getHTML()).toContain(
      "<ul><li><p>Mikroserwisy płatności.</p></li><li><p>Nowy obowiązek.</p></li></ul>",
    );
  });

  it("z nagłówka stanowiska dopisuje punkt na końcu jego listy", () => {
    const editor = open(CV);
    caretIn(editor, "Bank Przykładowy");
    runCvCommand(editor, insertBullet("pl"));
    expect(editor.getHTML()).toContain(
      `<ul><li><p>Mikroserwisy płatności.</p></li><li><p>${CV_PLACEHOLDERS.pl.duty}</p></li></ul>`,
    );
    const { from, to } = editor.state.selection;
    expect(editor.state.doc.textBetween(from, to)).toBe(CV_PLACEHOLDERS.pl.duty);
  });

  it("stanowisku bez listy zakłada etykietę obowiązków i listę pod firmą", () => {
    const editor = open(
      '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
        '<p data-cv-section="role"><strong>Dev</strong> 2020 – 2022</p>' +
        `<p data-cv-section="employer">Acme</p>${RODO}`,
    );
    caretIn(editor, "Dev");
    runCvCommand(editor, insertBullet("pl"));
    expect(editor.getHTML()).toContain(
      '<p data-cv-section="employer">Acme</p><p data-cv-section="duties_label">Zakres zadań:</p>' +
        `<ul><li><p>${CV_PLACEHOLDERS.pl.duty}</p></li></ul>`,
    );
    const { from, to } = editor.state.selection;
    expect(editor.state.doc.textBetween(from, to)).toBe(CV_PLACEHOLDERS.pl.duty);
  });

  it("poza listą, stanowiskiem i sekcją-listą nie ma zastosowania", () => {
    const editor = open(CV);
    caretIn(editor, "Politechnika");
    expect(insertBullet("pl")(editor.state)).toBeNull();
    caretIn(editor, "DLACZEGO NASZ KANDYDAT?");
    expect(runCvCommand(editor, insertBullet("pl"))).toBe(true);
    expect(editor.getHTML()).toContain("<li><p>Ponad 7 lat w Javie.</p></li><li><p></p></li>");
  });

  it("dopisuje wiersz wykształcenia w kształcie tabeli Worda", () => {
    const editor = open(CV);
    caretIn(editor, "Usługi REST.");
    runCvCommand(editor, insertRow("education", "pl"));
    const fields = CV_PLACEHOLDERS.pl;
    expect(editor.getHTML()).toContain(
      "<p>2012 – 2017 <strong>Politechnika Przykładowa</strong> — Informatyka</p>" +
        `<p>${fields.educationDates} <strong>${fields.school}</strong> — ${fields.degree}</p>` +
        '<h2 data-cv-section="experience">',
    );
    const { from, to } = editor.state.selection;
    expect(editor.state.doc.textBetween(from, to)).toBe(fields.educationDates);
  });

  it("brakującą sekcję zakłada w kolejności szablonu", () => {
    const editor = open(CV);
    caretIn(editor, "Usługi REST.");
    runCvCommand(editor, insertRow("certifications", "pl"));
    runCvCommand(editor, insertRow("languages", "pl"));
    runCvCommand(editor, insertRow("skills", "pl"));
    expect(cvOutline(editor.state.doc).sections.map((section) => section.key)).toEqual([
      "why_points",
      "education",
      "skills",
      "certifications",
      "languages",
      "experience",
    ]);
    const html = editor.getHTML();
    expect(html).toContain(
      `<h2 data-cv-section="certifications">CERTYFIKATY</h2><ul><li><p>${CV_PLACEHOLDERS.pl.certificate}</p></li></ul>`,
    );
    expect(html).toContain(`<h2 data-cv-section="languages">JĘZYKI</h2><p>${CV_PLACEHOLDERS.pl.language}</p>`);
    expect(html).toContain(
      `<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2><p><strong>${CV_PLACEHOLDERS.pl.skillGroup}: </strong>${CV_PLACEHOLDERS.pl.skills}</p>`,
    );
    expect(lastBlockIsRodo(editor)).toBe(true);
  });
});

describe("typ akapitu", () => {
  it("oznacza zwykły akapit i zdejmuje znacznik", () => {
    const editor = open(`<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>${ROLE_A}<p>Dopisek</p>${RODO}`);
    caretIn(editor, "Dopisek");
    expect(blockKindOf(cvContext(editor.state).block)).toBe("text");
    expect(runCvCommand(editor, setBlockKind("employer", "pl"))).toBe(true);
    expect(editor.getHTML()).toContain('<p data-cv-section="employer">Dopisek</p>');
    expect(setBlockKind("employer", "pl")(editor.state)).toBeNull();
    runCvCommand(editor, setBlockKind("text", "pl"));
    expect(editor.getHTML()).toContain("<p>Dopisek</p>");
  });

  it("stanowisku bez pogrubienia pogrubia część przed datami", () => {
    const editor = open(
      `<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>${ROLE_A}<p>Tester manualny — 05.2015 – 12.2016</p>${RODO}`,
    );
    caretIn(editor, "Tester manualny");
    runCvCommand(editor, setBlockKind("role", "pl"));
    expect(editor.getHTML()).toContain(
      '<p data-cv-section="role"><strong>Tester manualny</strong> — 05.2015 – 12.2016</p>',
    );
    expect(roleTitles(editor)).toHaveLength(2);
  });

  it("zamienia akapit w nagłówek sekcji i z powrotem", () => {
    const editor = open(`<p>Doświadczenie</p><p></p>${RODO}`);
    caretIn(editor, "Doświadczenie");
    runCvCommand(editor, setBlockKind("experience", "pl"));
    expect(editor.getHTML()).toContain('<h2 data-cv-section="experience">Doświadczenie</h2>');
    expect(blockKindOf(cvContext(editor.state).block)).toBe("experience");
    runCvCommand(editor, setBlockKind("text", "pl"));
    expect(editor.getHTML()).toContain("<p>Doświadczenie</p>");
    // Pusty akapit dostaje tytuł z szablonu.
    editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize + 1);
    runCvCommand(editor, setBlockKind("skills", "en"));
    expect(editor.getHTML()).toContain('<h2 data-cv-section="skills">SKILLS</h2>');
  });

  it("nie działa w liście ani na klauzuli zgody", () => {
    const editor = open(CV);
    caretIn(editor, "Usługi REST.");
    expect(setBlockKind("role", "pl")(editor.state)).toBeNull();
    caretIn(editor, "Wyrażam zgodę");
    expect(setBlockKind("text", "pl")(editor.state)).toBeNull();
    expect(blockKindOf(cvContext(editor.state).block)).toBe("text");
  });

  it("w starym CV bez znaczników oznacza od razu wszystko, co serwer rozpoznałby po kształcie", () => {
    const editor = open(
      "<h2>DOŚWIADCZENIE</h2>" +
        "<p><strong>Senior Developer</strong> 2021 – obecnie</p><p>Acme Bank</p>" +
        "<p>Zakres zadań:</p><ul><li><p>Usługi płatnicze.</p></li></ul><p>Technologie: Java</p>" +
        "<p><strong>Projekt:</strong> nowy system płatności</p>" +
        "<p>Developer, 2018 – 2021</p><p>Globex</p>",
    );
    caretIn(editor, "Developer, 2018");
    runCvCommand(editor, setBlockKind("role", "pl"));
    const html = editor.getHTML();
    expect(html).toContain('<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – obecnie</p>');
    expect(html).toContain('<p data-cv-section="employer">Acme Bank</p>');
    expect(html).toContain('<p data-cv-section="duties_label">Zakres zadań:</p>');
    expect(html).toContain('<p data-cv-section="technologies">Technologie: Java</p>');
    expect(html).toContain('<p data-cv-section="role"><strong>Developer</strong>, 2018 – 2021</p>');
    // Pogrubiony początek zdania to nie stanowisko, a firma pod NOWYM stanowiskiem
    // nie była rozpoznawalna po kształcie — oznacza ją człowiek.
    expect(html).toContain("<p><strong>Projekt:</strong> nowy system płatności</p>");
    expect(html).toContain("<p>Globex</p>");
  });
});

it("znajduje niewypełnione pola w obu językach", () => {
  expect(cvPlaceholders("<p>Zwykła treść [C#] i [1]</p>")).toEqual([]);
  expect(cvPlaceholders(`${CV_PLACEHOLDERS.en.company} x ${CV_PLACEHOLDERS.pl.duty}`)).toEqual([
    CV_PLACEHOLDERS.pl.duty,
    CV_PLACEHOLDERS.en.company,
  ]);
});
