/**
 * Panel „Do poprawy” w edytorze CV (Edytor CV 2, PR 2) — czysta logika.
 *
 * QC, uwagi generatora i kontrola AI opisują ZAPISANĄ treść blokami tekstu,
 * a edytor trzyma dokument ProseMirror, który rekruter właśnie zmienia. Nie
 * mają wspólnego indeksu bloków, więc miejsce uwagi szuka się po tym, co
 * widać: po numerze stanowiska w sekcji doświadczenia (lustro `cv_qc.cv_roles`),
 * po etykiecie roli, po terminie w tekście albo po treści całej linii. Uwaga,
 * której miejsca już nie ma, po prostu nie ma znacznika — nic nie zgaduje.
 *
 * Poprawki liczy serwer na treści z edytora (`POST …/qc/transform`), a tutaj
 * wynik zamienia się w JEDNĄ transakcję obejmującą tylko zmieniony zakres:
 * jedno „Cofnij” wraca do stanu sprzed poprawki, kursor zostaje na miejscu.
 *
 * Od 13.10.2026 (PR 4 „CV w procesie”) panel ma JEDNĄ listę: QC, uwagi
 * generatora i kontrola AI razem, pogrupowane po sekcjach CV, z małą etykietą
 * źródła przy każdej pozycji (`buildIssueList`). Uwaga generatora „MUST-HAVE:
 * X” znika, gdy QC ma pozycję X — ta sama rzecz nie liczy się dwa razy.
 *
 * Moduł nie importuje `@tiptap/react`.
 */

import { createDocument } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";
import { Fragment, Slice, type Node as PMNode } from "@tiptap/pm/model";
import { TextSelection, type EditorState, type Transaction } from "@tiptap/pm/state";

import type { CvReviewFinding } from "@/lib/api/cvEditorIssues";
import type { QcCheck, QcFix, QcFixAction, QcItem, QcTransformApplied } from "@/lib/api/cvQc";
import { cvOutline, type CvOutline, type CvRole, type CvSectionKey } from "@/lib/cv-editor-blocks";
import { classifyCvWarnings, type ClassifiedCvWarning } from "@/lib/cv-generator";
import {
  countForm,
  itemTarget,
  normalizeQcText,
  originalDescribesSkill,
  roleGaps,
  roleLabelParts,
  splitChecks,
  termRegExp,
  warningsBeyondQc,
  type IssueTarget,
  type QcTask,
} from "@/lib/cv-qc";

export interface IssueRange {
  from: number;
  to: number;
  /** Całe bloki tekstu (akapit, punkt) zamiast fragmentu linii. */
  block: boolean;
}

/** `blocking` zatrzymuje wysyłkę CV, `note` to podpowiedź. */
export type IssueTone = "blocking" | "note";

export interface IssueMark extends IssueRange {
  tone: IssueTone;
}

// ── Tekst dokumentu ──────────────────────────────────────────────────────────

/** Znak w miejscu węzła bez tekstu (twarda spacja wiersza) — pozycje zostają zgodne z dokumentem. */
const LEAF = "￼";

interface TextBlock {
  node: PMNode;
  /** Pozycja PRZED blokiem; tekst zaczyna się na `position + 1`. */
  position: number;
  text: string;
}

/** Bloki tekstu dokumentu bez klauzuli zgody (jest stała — uwagi jej nie dotyczą). */
function textBlocks(doc: PMNode, outline: CvOutline, within?: { from: number; to: number }): TextBlock[] {
  const blocks: TextBlock[] = [];
  doc.descendants((node, position) => {
    if (outline.rodo && position === outline.rodo.from) return false;
    if (within && (position + node.nodeSize <= within.from || position >= within.to)) return false;
    if (!node.isTextblock) return true;
    blocks.push({ node, position, text: node.textBetween(0, node.content.size, undefined, LEAF) });
    return false;
  });
  return blocks;
}

// ── Miejsce uwagi w dokumencie ───────────────────────────────────────────────

/** Stanowiska w sekcji doświadczenia — w tej kolejności serwer nadaje `role_index`. */
function experienceRoles(outline: CvOutline): CvRole[] {
  return outline.roles.filter((role) => outline.blocks[role.fromIndex]?.section === "experience");
}

function findRole(doc: PMNode, outline: CvOutline, roleIndex: number | null, label: string | null): CvRole | null {
  const numbered = roleIndex != null ? experienceRoles(outline)[roleIndex] : undefined;
  if (numbered) return numbered;
  const parts = label ? roleLabelParts(label) : [];
  if (parts.length === 0) return null;
  return (
    outline.roles.find((role) => {
      const text = normalizeQcText(doc.textBetween(role.from, role.to, " "));
      return parts.every((part) => text.includes(part));
    }) ?? null
  );
}

interface TermSearch {
  within?: { from: number; to: number };
  /** Pomiń wystąpienia z pogrubieniem (sprawdzenia „pogrubione w CV”). */
  unboldedOnly?: boolean;
  limit?: number;
}

/** Wystąpienia terminu w tekście CV (granice słowa jak w QC), w kolejności dokumentu. */
export function termRanges(doc: PMNode, term: string, search: TermSearch = {}, outline = cvOutline(doc)): IssueRange[] {
  const pattern = termRegExp(term);
  if (!pattern) return [];
  const bold = doc.type.schema.marks.bold;
  const ranges: IssueRange[] = [];
  for (const block of textBlocks(doc, outline, search.within)) {
    for (const match of block.text.matchAll(pattern)) {
      if (!match[0]) continue;
      const from = block.position + 1 + (match.index ?? 0);
      const to = from + match[0].length;
      if (search.unboldedOnly && bold && doc.rangeHasMark(from, to, bold)) continue;
      ranges.push({ from, to, block: false });
      if (search.limit && ranges.length >= search.limit) return ranges;
    }
  }
  return ranges;
}

/** Blok, którego cały tekst to podana linia (odstępy i wielkość liter bez znaczenia). */
function lineRange(doc: PMNode, outline: CvOutline, text: string): IssueRange | null {
  const wanted = normalizeQcText(text);
  if (!wanted) return null;
  const block = textBlocks(doc, outline).find((candidate) => normalizeQcText(candidate.text) === wanted);
  return block ? { from: block.position, to: block.position + block.node.nodeSize, block: true } : null;
}

/** Tytuł stanowiska — pierwszy blok roli. */
function roleTitleRange(outline: CvOutline, role: CvRole): IssueRange {
  return { from: role.from, to: outline.blocks[role.fromIndex].to, block: true };
}

/**
 * Pozycja w dokumencie dla miejsca z uwagi; `null`, gdy tego miejsca już nie
 * ma (tekst zmieniono po zapisie, na którym policzono listę).
 */
export function locateTarget(doc: PMNode, target: IssueTarget, outline = cvOutline(doc)): IssueRange | null {
  if (target.kind === "line") return lineRange(doc, outline, target.text);
  const role = findRole(doc, outline, target.roleIndex, target.label);
  if (target.kind === "role") return role ? roleTitleRange(outline, role) : null;
  const inRole = role ? termRanges(doc, target.term, { within: role, limit: 1 }, outline)[0] : undefined;
  return inRole ?? termRanges(doc, target.term, { limit: 1 }, outline)[0] ?? (role ? roleTitleRange(outline, role) : null);
}

// ── Znaczniki przy tekście ───────────────────────────────────────────────────

const BOLD_CHECKS = new Set(["must_bolded", "nice_bolded"]);
/** Górny limit znaczników — długie CV z częstym terminem nie zamula widoku. */
const MAX_MARKS = 300;

/**
 * Znaczniki uwag w bieżącym dokumencie: stanowiska z brakiem opisu, terminy
 * z niezaliczonych sprawdzeń i linie wskazane przez kontrolę AI. Liczone od
 * zera po każdej zmianie treści — uwaga, której miejsce zniknęło, znika.
 */
export function issueMarks(doc: PMNode, checks: readonly QcCheck[], findings: readonly CvReviewFinding[]): IssueMark[] {
  const outline = cvOutline(doc);
  const marks: IssueMark[] = [];
  for (const gap of roleGaps([...checks])) {
    const role = findRole(doc, outline, gap.roleIndex, gap.role);
    if (role) marks.push({ ...roleTitleRange(outline, role), tone: gap.blocking.length > 0 ? "blocking" : "note" });
  }
  const seen = new Set<string>();
  for (const check of checks) {
    if (check.status !== "fail" && check.status !== "manual") continue;
    const tone: IssueTone = check.status === "fail" && check.severity === "blocking" ? "blocking" : "note";
    for (const item of check.items) {
      const target = itemTarget(item);
      if (target?.kind !== "term") continue;
      const key = `${tone}:${normalizeQcText(target.term)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const search = { unboldedOnly: BOLD_CHECKS.has(check.key), limit: MAX_MARKS - marks.length };
      if (search.limit <= 0) return marks;
      for (const range of termRanges(doc, target.term, search, outline)) marks.push({ ...range, tone });
    }
  }
  for (const finding of findings) {
    const range = lineRange(doc, outline, finding.text);
    if (range) marks.push({ ...range, tone: "note" });
  }
  return marks.slice(0, MAX_MARKS);
}

/** Uwagi kontroli AI, których linia nadal stoi w CV — poprawiona linia nie wraca na listę. */
export function findingsInCv(doc: PMNode, findings: readonly CvReviewFinding[]): CvReviewFinding[] {
  const outline = cvOutline(doc);
  return findings.filter((finding) => lineRange(doc, outline, finding.text) != null);
}

/**
 * Czy zdanie z propozycji AI już stoi w CV. Liczone z treści, nie z pamięci
 * panelu: po „Cofnij” propozycja wraca na listę sama.
 */
export function fixAlreadyInCv(doc: PMNode, fix: QcFix): boolean {
  return lineRange(doc, cvOutline(doc), fix.proposed_text.replace(/\*\*/g, "")) != null;
}

export const REVIEW_FINDING_LABEL: Record<string, string> = {
  unsupported: "bez pokrycia w źródłach",
  contradicted: "sprzeczne ze źródłem",
  private: "dane prywatne",
  invalid_evidence: "kontrola nie wskazała źródła",
};

// ── Jedna lista „Do poprawy” (PR 4, 13.10.2026) ──────────────────────────────

/** Skąd jest pozycja — mała etykieta przy każdej rzeczy na liście. */
export type IssueSource = "qc" | "generator" | "review";

export const ISSUE_SOURCE_LABEL: Record<IssueSource, string> = {
  qc: "QC",
  generator: "generator",
  review: "kontrola AI",
};

export type IssueEntry =
  /** Pozycja QC zatrzymująca wysyłkę (jedno wymaganie albo jedna rzecz bez nazwy). */
  | { kind: "task"; id: string; source: "qc"; task: QcTask }
  /** Uwaga QC — całe sprawdzenie (ma przyciski poziomu sprawdzenia, np. „Pogrub wszystkie”). */
  | { kind: "check"; id: string; source: "qc"; check: QcCheck }
  | { kind: "warning"; id: string; source: "generator"; warning: ClassifiedCvWarning }
  | { kind: "finding"; id: string; source: "review"; finding: CvReviewFinding };

/** Grupa sekcji CV: „Całe CV” (bez miejsca albo w kilku sekcjach), nagłówek, sekcje szablonu, pozostałe. */
export type IssueGroupKey = "whole" | "header" | "other" | CvSectionKey;

export const ISSUE_GROUP_LABEL: Record<IssueGroupKey, string> = {
  whole: "Całe CV",
  header: "Nagłówek",
  why_points: "Dlaczego nasz kandydat",
  education: "Edukacja",
  skills: "Umiejętności",
  certifications: "Certyfikaty",
  languages: "Języki",
  experience: "Doświadczenie",
  other: "Pozostałe sekcje",
};

export interface IssueGroup {
  key: IssueGroupKey;
  label: string;
  entries: IssueEntry[];
}

export interface IssueList {
  /** Grupy sekcji CV w kolejności kartki; „Całe CV” pierwsze. */
  sections: IssueGroup[];
  /** Rzeczy, których nie da się poprawić bez kandydata (pytanie, potwierdzenie). */
  ask: IssueEntry[];
  /** Uwagi wyciszone w „Jakość QC” (D6) — informacja, nie liczą się. */
  muted: QcCheck[];
  /** Co generator zrobił i dlaczego — informacja, nie liczy się. */
  info: ClassifiedCvWarning[];
  /** Uwagi generatora „MUST-HAVE: X” schowane, bo QC ma pozycję X. */
  covered: ClassifiedCvWarning[];
  passed: QcCheck[];
  skipped: QcCheck[];
  /** Ile rzeczy do sprawdzenia (grupy sekcji + „Zapytaj kandydata”) — licznik w pasku i na karcie. */
  total: number;
}

export interface IssueListInput {
  /** Bieżący dokument edytora; `null` = bez miejsc (wszystko w „Całe CV”). */
  doc: PMNode | null;
  checks: readonly QcCheck[];
  /** Uwagi generatora z serwera (bez pominiętych). */
  warnings: readonly string[];
  /** Uwagi kontroli AI, których linia nadal stoi w CV (`findingsInCv`). */
  findings: readonly CvReviewFinding[];
}

/** Sekcja CV, w której stoi pozycja dokumentu. Klauzula zgody nie jest sekcją uwag. */
function groupAt(outline: CvOutline, position: number): IssueGroupKey {
  const block = outline.blocks.find((candidate) => position >= candidate.from && position < candidate.to);
  if (!block || (outline.rodo && block.index === outline.rodo.index)) return "whole";
  if (block.section) return block.section;
  const firstSection = outline.sections[0]?.headingIndex ?? Infinity;
  return block.index < firstSection ? "header" : "other";
}

interface Placement {
  group: IssueGroupKey;
  /** Pierwsze miejsce w dokumencie — kolejność w grupie. */
  position: number | null;
}

const NOWHERE: Placement = { group: "whole", position: null };

/** Miejsce pozycji: jedna sekcja, gdy wszystkie jej miejsca w niej stoją; kilka sekcji albo brak miejsca = „Całe CV”. */
function placeTargets(doc: PMNode | null, outline: CvOutline | null, targets: ReadonlyArray<IssueTarget | null>): Placement {
  if (!doc || !outline) return NOWHERE;
  const ranges = targets.flatMap((target) => {
    const range = target ? locateTarget(doc, target, outline) : null;
    return range ? [range] : [];
  });
  if (ranges.length === 0) return NOWHERE;
  const position = Math.min(...ranges.map((range) => range.from));
  const groups = new Set(ranges.map((range) => groupAt(outline, range.from)));
  return groups.size === 1 ? { group: [...groups][0], position } : { group: "whole", position };
}

/**
 * Pozycja do wyjaśnienia z kandydatem: umiejętność krytyczna, której oryginał
 * nie opisuje w rolach (karta daje pytanie, nie AI), albo same pozycje
 * „zapytaj kandydata”.
 */
function asksCandidate(checkKey: string, items: readonly QcItem[]): boolean {
  if (items.length === 0) return false;
  if (checkKey === "critical_skills") {
    const inRoles = items.filter((item) => item.role);
    if (inRoles.length > 0) return !originalDescribesSkill(inRoles);
  }
  return items.every((item) => item.fix === "ask_candidate");
}

/**
 * Jedna lista panelu „Do poprawy”: pozycje QC (blokujące i uwagi), uwagi
 * generatora „Do sprawdzenia” i kontrola AI, pogrupowane po sekcjach CV
 * (`cvOutline`) w kolejności kartki. „Całe CV” zbiera to, co nie ma miejsca
 * w tekście albo stoi w kilku sekcjach. W grupie najpierw to, co zatrzymuje
 * wysyłkę, potem w kolejności tekstu. Rzeczy do wyjaśnienia z kandydatem idą
 * osobno, informacje i zaliczone sprawdzenia — na koniec.
 */
export function buildIssueList({ doc, checks, warnings, findings }: IssueListInput): IssueList {
  const outline = doc ? cvOutline(doc) : null;
  const split = splitChecks([...checks]);
  const classified = classifyCvWarnings(warnings);
  const { kept, covered } = warningsBeyondQc(classified.review, checks);

  type Placed = { entry: IssueEntry; blocking: boolean; place: Placement; order: number };
  const placed: Placed[] = [];
  const ask: IssueEntry[] = [];
  const add = (entry: IssueEntry, blocking: boolean, place: Placement, toAsk = false) => {
    if (toAsk) ask.push(entry);
    else placed.push({ entry, blocking, place, order: placed.length });
  };

  for (const task of split.tasks) {
    add(
      { kind: "task", id: `qc:${task.id}`, source: "qc", task },
      true,
      placeTargets(doc, outline, task.items.map(itemTarget)),
      asksCandidate(task.check.key, task.items),
    );
  }
  for (const check of split.notes) {
    add(
      { kind: "check", id: `qc:${check.key}`, source: "qc", check },
      false,
      placeTargets(doc, outline, check.items.map(itemTarget)),
      asksCandidate(check.key, check.items),
    );
  }
  for (const warning of kept) {
    add({ kind: "warning", id: `generator:${warning.text}`, source: "generator", warning }, false, NOWHERE);
  }
  findings.forEach((finding, index) => {
    add(
      { kind: "finding", id: `review:${index}:${finding.status}:${finding.text}`, source: "review", finding },
      false,
      placeTargets(doc, outline, [{ kind: "line", text: finding.text }]),
    );
  });

  // Kolejność grup: „Całe CV”, nagłówek, sekcje w kolejności kartki, pozostałe.
  const sectionOrder: IssueGroupKey[] = ["whole", "header"];
  for (const section of outline?.sections ?? []) {
    if (!sectionOrder.includes(section.key)) sectionOrder.push(section.key);
  }
  sectionOrder.push("other");
  const rank = (key: IssueGroupKey) => {
    const index = sectionOrder.indexOf(key);
    return index === -1 ? sectionOrder.length : index;
  };

  const byGroup = new Map<IssueGroupKey, Placed[]>();
  for (const item of placed) {
    const list = byGroup.get(item.place.group) ?? [];
    list.push(item);
    byGroup.set(item.place.group, list);
  }
  const sections: IssueGroup[] = [...byGroup.entries()]
    .sort(([first], [second]) => rank(first) - rank(second))
    .map(([key, items]) => ({
      key,
      label: ISSUE_GROUP_LABEL[key],
      entries: [...items]
        .sort(
          (first, second) =>
            Number(second.blocking) - Number(first.blocking) ||
            (first.place.position ?? Infinity) - (second.place.position ?? Infinity) ||
            first.order - second.order,
        )
        .map((item) => item.entry),
    }));

  return {
    sections,
    ask,
    muted: split.muted,
    info: classified.info,
    covered,
    passed: split.passed,
    skipped: split.skipped,
    total: placed.length + ask.length,
  };
}

// ── Wiersze panelu po wadze (wariant A, 17.10.2026) ─────────────────────────
//
// Rekruter: „panel mówi, co jest nie tak, a jednym guzikiem wprowadza zmianę”.
// Lista nie idzie już po sekcjach CV, tylko po tym, co rekruter ma zrobić:
// „Blokuje wysyłkę”, „Do poprawy” (jest przycisk, który poprawia) i „Do decyzji
// · nie blokuje” (uwagi bez gotowej poprawki, generator, kontrola AI). Jeden
// wiersz = problem, podgląd zmiany i jeden przycisk; zdanie AI stoi w wierszu
// swojej uwagi, nie w osobnej sekcji pod listą.

/** Poprawki jednym przyciskiem dla całego sprawdzenia. */
export type CheckFixKind = "bold_all" | "spelling";

export type IssueRow =
  /** Rzecz zatrzymująca wysyłkę (jedno wymaganie albo pozycja bez nazwy) i propozycje AI do niej. */
  | { kind: "task"; id: string; task: QcTask; fixes: QcFix[] }
  /** Pogrubienie albo pisownia — jeden przycisk dla wszystkich pozycji sprawdzenia. */
  | { kind: "check-fix"; id: string; check: QcCheck; fix: CheckFixKind; items: QcItem[] }
  /** Jedna pozycja uwagi QC: kolejność stanowisk, usunięcie terminu, zdanie AI albo bez poprawki. */
  | { kind: "item"; id: string; check: QcCheck; item: QcItem; fixes: QcFix[] }
  /** Uwaga QC do obejrzenia ręcznie albo bez pozycji. */
  | { kind: "check"; id: string; check: QcCheck }
  /** Propozycja AI, której nie da się przypiąć do żadnej pozycji listy. */
  | { kind: "proposal"; id: string; fix: QcFix }
  | { kind: "warning"; id: string; warning: ClassifiedCvWarning }
  | { kind: "finding"; id: string; finding: CvReviewFinding };

export interface IssueRows {
  blocking: IssueRow[];
  fixable: IssueRow[];
  decide: IssueRow[];
}

const CHECK_FIXES: readonly CheckFixKind[] = ["bold_all", "spelling"];

/** Zdanie uwagi QC (`QcItem.detail` — tekst z kontraktu QC, nie `detail` błędu API). */
export function itemSentence(item: QcItem): string {
  return typeof item.detail === "string" ? item.detail : "";
}

/**
 * Poprawka jednym przyciskiem dla pozycji bez `fix` z serwera (PR 2,
 * 17.10.2026). QC nie dostał nowego pola — zmieniłoby skrót zapisanego
 * przebiegu i wyzerowało czas oczekiwania w kolejce DL — więc rodzaj poprawki
 * wynika z klucza sprawdzenia: lata według historii, tytuł z rekrutacji
 * (serwer bierze go sam), stawka albo kontakt kandydata w CV.
 */
export function itemQuickFix(check: QcCheck, item: QcItem): QcFixAction | null {
  if (check.status !== "fail" || item.fix) return null;
  if (check.key === "years_header") return { action: "years" };
  if (check.key === "title_matches_role" && item.term?.trim()) return { action: "title" };
  if (check.key === "client_rules" && /^(Stawka w CV|CV zawiera)/.test(itemSentence(item))) {
    return { action: "strip_client_rules" };
  }
  return null;
}

const YEARS_NUMBER = /(?<![\d.,])(\d{1,2})(\s*\+?\s*)(lata|lat|roku|years?|yrs)\b/i;

/** „lat” / „lata” po liczbie (lustro `cv_qc._years_word`). */
function yearsWord(word: string, n: number): string {
  const low = word.toLowerCase();
  if (low === "lat" || low === "lata") {
    const few = [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100);
    return few ? "lata" : "lat";
  }
  if (low === "year" || low === "years") return n === 1 ? "year" : "years";
  return word;
}

/**
 * Podgląd poprawki lat: (cytat z CV, cytat po poprawce). Liczba z historii stoi
 * w zdaniu uwagi QC („… wychodzi 7.”); bez niej — `null` (sam przycisk).
 */
export function yearsPreview(item: QcItem): { before: string; after: string } | null {
  const quote = item.term?.trim();
  const actual = /wychodzi (\d+)/.exec(itemSentence(item));
  if (!quote || !actual) return null;
  const n = Number(actual[1]);
  if (!Number.isFinite(n) || n < 1) return null;
  const match = YEARS_NUMBER.exec(quote);
  if (!match) return null;
  const after = quote.replace(YEARS_NUMBER, `${n}${match[2]}${yearsWord(match[3], n)}`);
  return after === quote ? null : { before: quote, after };
}

/** Ta sama nazwa wymagania albo terminu (po normalizacji). */
function sameName(left: string | null | undefined, right: string | null | undefined): boolean {
  const a = normalizeQcText(left ?? "");
  return a !== "" && a === normalizeQcText(right ?? "");
}

/** Propozycja AI dotyczy tej pozycji QC: to samo sprawdzenie, wymaganie i — gdy obie znają — rola. */
function fixMatchesItem(fix: QcFix, checkKey: string, item: QcItem): boolean {
  if (fix.check_key !== checkKey) return false;
  if (!sameName(fix.requirement, item.requirement ?? item.term)) return false;
  if (typeof fix.role_index === "number" && typeof item.role_index === "number") {
    return fix.role_index === item.role_index;
  }
  if (fix.role && item.role) return sameName(fix.role, item.role);
  return true;
}

/**
 * Wiersze panelu w trzech grupach. `fixes` to propozycje AI widoczne na liście
 * (bez odrzuconych i już stojących w CV); `fixesPending` = jeszcze się ładują —
 * pozycja z poprawką AI zostaje wtedy w „Do poprawy” z „Przygotowuję zdanie…”.
 * Propozycja bez pozycji (np. QC przeliczone po zapisie) nie ginie: dostaje
 * własny wiersz w „Do poprawy”.
 */
export function issueRows(list: IssueList, fixes: readonly QcFix[], fixesPending: boolean): IssueRows {
  const rows: IssueRows = { blocking: [], fixable: [], decide: [] };
  const used = new Set<string>();
  const take = (checkKey: string, items: readonly QcItem[]) => {
    const found = fixes.filter((fix) => !used.has(fix.id) && items.some((item) => fixMatchesItem(fix, checkKey, item)));
    found.forEach((fix) => used.add(fix.id));
    return found;
  };

  const entries = [...list.sections.flatMap((group) => group.entries), ...list.ask];
  for (const entry of entries) {
    switch (entry.kind) {
      case "task":
        rows.blocking.push({ kind: "task", id: entry.id, task: entry.task, fixes: take(entry.task.check.key, entry.task.items) });
        break;
      case "warning":
        rows.decide.push({ kind: "warning", id: entry.id, warning: entry.warning });
        break;
      case "finding":
        rows.decide.push({ kind: "finding", id: entry.id, finding: entry.finding });
        break;
      case "check": {
        const { check } = entry;
        if (check.status !== "fail" || check.items.length === 0) {
          rows.decide.push({ kind: "check", id: entry.id, check });
          break;
        }
        for (const fix of CHECK_FIXES) {
          const items = check.items.filter((item) => item.fix === fix);
          if (items.length > 0) rows.fixable.push({ kind: "check-fix", id: `${entry.id}:${fix}`, check, fix, items });
        }
        check.items.forEach((item, index) => {
          if (item.fix && (CHECK_FIXES as readonly string[]).includes(item.fix)) return;
          const own = item.fix === "ai" ? take(check.key, [item]) : [];
          const row: IssueRow = { kind: "item", id: `${entry.id}:${item.key ?? index}`, check, item, fixes: own };
          const term = (item.term ?? item.requirement ?? "").trim();
          const fixable =
            item.fix === "role_order" ||
            (item.fix === "remove_term" && term !== "") ||
            (item.fix === "ai" && (own.length > 0 || fixesPending)) ||
            itemQuickFix(check, item) !== null;
          (fixable ? rows.fixable : rows.decide).push(row);
        });
        break;
      }
    }
  }
  for (const fix of fixes) {
    if (!used.has(fix.id)) rows.fixable.push({ kind: "proposal", id: `fix:${fix.id}`, fix });
  }
  return rows;
}

/** Czy wiersz ma poprawkę, którą bierze „Popraw wszystkie” (lustro `bulkPlan`). */
export function rowInBulk(row: IssueRow): boolean {
  switch (row.kind) {
    case "check-fix":
    case "proposal":
      return true;
    case "task":
      return row.fixes.length > 0;
    case "item": {
      const quick = itemQuickFix(row.check, row.item)?.action;
      return row.fixes.length > 0 || quick === "years" || quick === "title";
    }
    default:
      return false;
  }
}

/** Nazwy pozycji do jednej linii („Kafka, Docker i 2 inne”). */
function namesLine(items: readonly QcItem[]): string {
  const names: string[] = [];
  for (const item of items) {
    const name = (item.requirement ?? item.term ?? "").trim();
    if (name && !names.includes(name)) names.push(name);
  }
  const head = names.slice(0, 3).join(", ");
  return names.length > 3 ? `${head} i ${countForm(names.length - 3, ["inne", "inne", "innych"])}` : head;
}

/**
 * Co zrobiła nałożona poprawka — wiersz grupy „Poprawione” (z „Cofnij”).
 * Liczone z tego, o co panel prosił, i z wyniku QC sprzed poprawki.
 */
export function appliedLabel(action: QcFixAction, checks: readonly QcCheck[], fixes: readonly QcFix[]): string {
  switch (action.action) {
    case "bold_all": {
      const key = action.scope === "nice" ? "nice_bolded" : "must_bolded";
      const items = checks
        .filter((check) => check.key === key)
        .flatMap((check) => [...check.items, ...(check.info ?? [])])
        .filter((item) => item.fix === "bold_all");
      const names = namesLine(items);
      return names ? `Pogrubiono: ${names}` : "Pogrubiono wymagania klienta";
    }
    case "spelling":
      return "Poprawiono pisownię technologii";
    case "role_order":
      return "Ułożono stanowiska od najnowszego";
    case "years":
      return "Lata doświadczenia według historii";
    case "title": {
      const title = checks.find((check) => check.key === "title_matches_role")?.items[0]?.term?.trim();
      return title ? `Tytuł CV: „${title}”` : "Tytuł CV z rekrutacji";
    }
    case "strip_client_rules":
      return "Usunięto stawkę i kontakt kandydata z CV";
    case "remove_line":
      return `Usunięto: „${action.text}”`;
    case "remove_term":
      return `Usunięto „${action.term}” z CV`;
    case "ai_fix": {
      const fix = fixes.find((candidate) => candidate.id === action.fix_id);
      const where = [fix?.requirement, fix?.cv_role_label || fix?.role].filter(Boolean).join(" · ");
      return where ? `Dopisano zdanie: ${where}` : "Dopisano zdanie z oryginału";
    }
  }
}

/**
 * Poprawki z żądania, które serwer naprawdę nałożył. Wynik niesie nazwę akcji
 * i to, czym się różnią poprawki tej samej akcji: id zdania AI, zakres
 * pogrubienia (must / nice), termin — pole, którego wynik nie podał, nie
 * rozstrzyga (harness i starsze odpowiedzi).
 */
export function appliedActions(
  requested: readonly QcFixAction[],
  applied: readonly QcTransformApplied[],
): QcFixAction[] {
  const same = (wanted: string | undefined, got: string | null | undefined) => !got || got === wanted;
  return requested.filter((action) =>
    applied.some((done) => {
      if (done.action !== action.action) return false;
      if (action.action === "ai_fix") return same(action.fix_id, done.fix_id);
      if (action.action === "bold_all") return same(action.scope, done.scope);
      if (action.action === "remove_term") return same(action.term.slice(0, 120), done.term);
      return true;
    }),
  );
}

// ── „Popraw wszystko” ────────────────────────────────────────────────────────

export interface BulkPlan {
  actions: QcFixAction[];
  /** Co zostanie zrobione — do zdania pod przyciskiem i do potwierdzenia. */
  parts: string[];
}

/**
 * Poprawki, które wolno nałożyć hurtem (decyzja Artura D2, 12.10.2026):
 * formalne (pogrubienie wymagań, pisownia technologii), zdania AI
 * w brzmieniu z serwera, czyli z cytatem sprawdzonym w źródle, a od
 * 17.10.2026 (D4) lata według historii i tytuł z rekrutacji. Usunięcie
 * terminu i zdanie AI po edycji zatwierdza się pojedynczo — serwer i tak
 * odrzuca je w trybie `bulk` (`cv_qc.BULK_ACTIONS`). Zdania AI idą pierwsze:
 * szukają swojej linii po tekście, który pisownia by zmieniła (serwer ustawia
 * tę kolejność także sam).
 */
export function bulkPlan(checks: readonly QcCheck[], fixes: readonly QcFix[]): BulkPlan {
  const actions: QcFixAction[] = fixes.map((fix) => ({ action: "ai_fix", fix_id: fix.id }));
  const parts: string[] = [];
  let spelling = 0;
  for (const check of checks) {
    if (check.status !== "fail") continue;
    const terms = check.items.filter((item) => item.fix === "bold_all").length;
    if (terms > 0) {
      const scope = check.key === "nice_bolded" ? "nice" : "must";
      if (!actions.some((action) => action.action === "bold_all" && action.scope === scope)) {
        actions.push({ action: "bold_all", scope });
        parts.push(
          `pogrubienie ${countForm(terms, ["wymagania", "wymagań", "wymagań"])} ${scope === "nice" ? "mile widzianych" : "must-have"}`,
        );
      }
    }
    spelling += check.items.filter((item) => item.fix === "spelling").length;
    // D4 (17.10.2026): lata i tytuł liczy kod z danych QC — wchodzą do hurtu.
    for (const item of check.items) {
      const quick = itemQuickFix(check, item);
      if (quick?.action === "years" && !actions.some((action) => action.action === "years")) {
        actions.push(quick);
        parts.push("lata doświadczenia według historii");
      }
      if (quick?.action === "title" && !actions.some((action) => action.action === "title")) {
        actions.push(quick);
        parts.push("tytuł CV z rekrutacji");
      }
    }
  }
  if (spelling > 0) {
    actions.push({ action: "spelling" });
    parts.push(`pisownia ${countForm(spelling, ["technologii", "technologii", "technologii"])}`);
  }
  if (fixes.length > 0) {
    parts.push(`${countForm(fixes.length, ["zdanie", "zdania", "zdań"])} AI z cytatem ze źródła`);
  }
  return { actions, parts };
}

// ── „Pogrub wymagania (N)” w nagłówku edytora (Edytor CV 3, PR 3) ────────────

/**
 * Wymagania klienta, których QC nie widzi pogrubionych (must-have i — przy
 * polityce must + nice — mile widziane), i poprawki, które je pogrubiają.
 * Ta sama droga co „Pogrub wszystkie” w panelu: `qc/transform` na treści
 * z edytora, jeden cofalny krok. `count: null` = QC nie ma wyniku (liczy się,
 * nie odpowiada) — przycisk bez liczby i wyłączony. W CV, które z założenia nie
 * pogrubia (Redakcja), QC mówi „nie dotyczy” i podaje te wymagania jako
 * informacje — przycisk liczy i pogrubia także je (16.10.2026).
 */
export function boldRequirements(checks: readonly QcCheck[] | null): {
  count: number | null;
  actions: QcFixAction[];
} {
  if (checks === null) return { count: null, actions: [] };
  const actions: QcFixAction[] = [];
  let count = 0;
  for (const check of checks) {
    const items = [...(check.status === "fail" ? check.items : []), ...(check.info ?? [])];
    const terms = items.filter((item) => item.fix === "bold_all").length;
    if (terms === 0) continue;
    count += terms;
    const scope = check.key === "nice_bolded" ? "nice" : "must";
    if (!actions.some((action) => action.action === "bold_all" && action.scope === scope)) {
      actions.push({ action: "bold_all", scope });
    }
  }
  return { count, actions };
}

// ── Nałożenie wyniku serwera ─────────────────────────────────────────────────

interface Change {
  /** Zakres w bieżącym dokumencie i to, co go zastępuje. */
  from: number;
  to: number;
  slice: Slice;
  /** Ten sam fragment w nowym dokumencie — do wyróżnienia po poprawce. */
  placed: IssueRange;
}

/** Zamiana różniącego się zakresu treści węzła (początek i koniec wspólne zostają). */
function contentChange(current: PMNode, next: PMNode, currentAt: number, nextAt: number): Change | null {
  const start = current.content.findDiffStart(next.content);
  if (start == null) return null;
  const end = current.content.findDiffEnd(next.content);
  if (!end) return null;
  let { a: endCurrent, b: endNext } = end;
  // Powtórzony fragment (np. dopisany taki sam punkt) daje koniec przed początkiem.
  const overlap = start - Math.min(endCurrent, endNext);
  if (overlap > 0) {
    endCurrent += overlap;
    endNext += overlap;
  }
  return {
    from: currentAt + start,
    to: currentAt + endCurrent,
    slice: next.slice(start, endNext),
    placed: { from: nextAt + start, to: nextAt + endNext, block: true },
  };
}

/**
 * Najmniejsze zamiany prowadzące od `current` do `next`. Węzły o tej samej
 * budowie porównuje dziecko po dziecku — pogrubienie w jednym punkcie i literówka
 * trzy sekcje wyżej to dwie małe zamiany, a nie jedna na pół dokumentu.
 * `currentAt` / `nextAt` to pozycje początku TREŚCI węzła.
 */
function collectChanges(current: PMNode, next: PMNode, currentAt: number, nextAt: number, out: Change[]): void {
  if (current.content.eq(next.content)) return;
  if (current.isTextblock || current.childCount !== next.childCount) {
    const change = contentChange(current, next, currentAt, nextAt);
    if (change) out.push(change);
    return;
  }
  let a = currentAt;
  let b = nextAt;
  for (let index = 0; index < current.childCount; index += 1) {
    const mine = current.child(index);
    const theirs = next.child(index);
    if (!mine.eq(theirs)) {
      if (!mine.isLeaf && !mine.isTextblock && mine.sameMarkup(theirs)) {
        collectChanges(mine, theirs, a + 1, b + 1, out);
      } else {
        out.push({
          from: a,
          to: a + mine.nodeSize,
          slice: new Slice(Fragment.from(theirs), 0, 0),
          placed: { from: b, to: b + theirs.nodeSize, block: true },
        });
      }
    }
    a += mine.nodeSize;
    b += theirs.nodeSize;
  }
}

export interface FixStep {
  transaction: Transaction;
  /** Zmienione miejsca w nowym dokumencie, w kolejności czytania. */
  changed: IssueRange[];
}

/**
 * Transakcja zamieniająca TYLKO to, czym nowa treść różni się od bieżącej;
 * `null`, gdy po wczytaniu do schematu edytora nic się nie zmienia. Wszystkie
 * zamiany są jednym krokiem historii, zaczętym od nowa: „Cofnij” zdejmuje samą
 * poprawkę, a nie poprawkę razem z tym, co rekruter wpisał chwilę wcześniej.
 */
export function fixStep(state: EditorState, html: string): FixStep | null {
  return docStep(state, createDocument(html, state.schema));
}

/**
 * Czy wtyczki przyjmą zmianę ORAZ jej cofnięcie.
 *
 * Wtyczka struktury odrzuca transakcję, która rozcina klauzulę zgody. Klauzula
 * bez znacznika (starsze CV) ma tę samą budowę co zwykły akapit, więc
 * najmniejsza zamiana sąsiedniego akapitu zaczynającego się tą samą literą
 * („W…” jak „Wyrażam…”) wchodziła w jej środek. Dopisany akapit wtyczka
 * odrzucała po cichu; usunięty wchodził, ale jego odwrotność już nie —
 * „Cofnij” nic nie robiło i blokowało cały stos cofania (przegląd 13.10.2026).
 * Historia cofa, odwracając kroki — sprawdzamy to samo.
 */
export function acceptedBothWays(state: EditorState, transaction: Transaction): boolean {
  // Odrzucona transakcja nie trafia na listę zastosowanych.
  const applied = state.applyTransaction(transaction);
  if (!applied.transactions.includes(transaction)) return false;
  try {
    const back = applied.state.tr;
    for (let index = transaction.steps.length - 1; index >= 0; index -= 1) {
      back.step(transaction.steps[index].invert(transaction.docs[index]));
    }
    return applied.state.applyTransaction(back).transactions.includes(back);
  } catch {
    // Wtyczka coś dopisała po zmianie i odwrotność już nie pasuje do dokumentu.
    return false;
  }
}

/** Całe bloki dokumentu, którymi nowa treść różni się od bieżącej (od początku i od końca). */
function blockChange(current: PMNode, next: PMNode): Change {
  const shared = Math.min(current.childCount, next.childCount);
  let head = 0;
  while (head < shared && current.child(head).eq(next.child(head))) head += 1;
  let tail = 0;
  while (
    tail < shared - head &&
    current.child(current.childCount - 1 - tail).eq(next.child(next.childCount - 1 - tail))
  ) {
    tail += 1;
  }
  const span = (doc: PMNode) => {
    let from = 0;
    for (let index = 0; index < head; index += 1) from += doc.child(index).nodeSize;
    let to = doc.content.size;
    for (let index = 0; index < tail; index += 1) to -= doc.child(doc.childCount - 1 - index).nodeSize;
    return { from, to };
  };
  const mine = span(current);
  const theirs = span(next);
  return { from: mine.from, to: mine.to, slice: next.slice(theirs.from, theirs.to), placed: { ...theirs, block: true } };
}

/**
 * To samo dla gotowego dokumentu — bez przejścia przez HTML (`lib/cv-editor-diff.ts`).
 *
 * Trzy próby, każda musi przejść w obie strony (`acceptedBothWays`): najmniejsze
 * zamiany, potem całe różniące się bloki, na końcu cała treść jednym krokiem.
 * `null` = nie ma czego zmieniać albo edytor nie przyjąłby żadnej z nich.
 */
export function docStep(state: EditorState, next: PMNode): FixStep | null {
  const changes: Change[] = [];
  collectChanges(state.doc, next, 0, 0, changes);
  if (changes.length === 0) return null;
  let transaction = state.tr;
  // Od końca: wcześniejsze pozycje zostają ważne.
  for (const change of [...changes].sort((first, second) => second.from - first.from)) {
    transaction.replace(change.from, change.to, change.slice);
  }
  let changed = changes.map((change) => change.placed).sort((first, second) => first.from - second.from);
  if (!transaction.doc.eq(next)) {
    // Zamiany po kawałku nie złożyły się w nową treść — jedna zamiana całego różniącego się zakresu.
    const whole = contentChange(state.doc, next, 0, 0);
    if (!whole) return null;
    transaction = state.tr.replace(whole.from, whole.to, whole.slice);
    changed = [whole.placed];
  }
  const minimal = closeHistory(transaction);
  if (acceptedBothWays(state, minimal)) return { transaction: minimal, changed };

  // Całe bloki: zamiana kończy się na granicy bloku, więc nie wchodzi w klauzulę.
  const blocks = blockChange(state.doc, next);
  const placed = blocks.placed.to > blocks.placed.from ? [blocks.placed] : [];
  const byBlocks = closeHistory(state.tr.replace(blocks.from, blocks.to, blocks.slice));
  if (byBlocks.doc.eq(next) && acceptedBothWays(state, byBlocks)) return { transaction: byBlocks, changed: placed };

  // Cała treść jednym krokiem: klauzula znika i wraca w całości, w obie strony.
  const everything = closeHistory(state.tr.replaceWith(0, state.doc.content.size, next.content));
  // Kursor na początek treści — domyślnie lądował w zablokowanej klauzuli na końcu.
  everything.setSelection(TextSelection.atStart(everything.doc));
  return acceptedBothWays(state, everything) ? { transaction: everything, changed: placed } : null;
}
