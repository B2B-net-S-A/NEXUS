// Fikcyjne dane panelu „Do poprawy” dla harnessu `/preview/cv-editor`.
//
// Zero sieci: „QC” liczy się z OSTATNIO ZAPISANEJ treści edytora, a poprawki to
// proste zamiany tekstu — tyle, żeby przeklikać cały obieg: poprawka → autozapis
// → świeża lista. Prawdziwe reguły są na serwerze (`services/cv_qc.py`).
// „To nieprawda” zdejmuje pozycję z listy do „Pominięte” w pamięci — jak
// `cv_finding_dismissals.apply_dismissals` i `cv_editor_issues._split_dismissed`.

import type { CvDismissedIssue, CvEditorIssuesApi, CvEditorIssuesData } from "@/lib/api/cvEditorIssues";
import type {
  QcCheck,
  QcConfirmation,
  QcDismissal,
  QcDismissReason,
  QcFix,
  QcResult,
  QcTransformApplied,
  QcTransformSkipped,
} from "@/lib/api/cvQc";
import { QC_DISMISS_REASONS } from "@/lib/cv-qc";

export type IssuesVariant = "issues" | "clean" | "down";

const UNSUPPORTED = "Jenkins";
const UNBOLDED = "PostgreSQL";
const MISSPELLED = "Github";
const KAFKA_LINE = "Integracje z systemami zewnętrznymi przez kolejki komunikatów.";

const KAFKA_FIX: QcFix = {
  id: "f1-0a1b2c3d4e5f",
  check_key: "critical_skills",
  requirement: "Kafka",
  role: "Software House Przykład — Java Developer",
  role_index: 1,
  cv_role_label: "Java Developer 01.2017 – 02.2021 · Software House Przykład",
  current_text: KAFKA_LINE,
  proposed_text: "Integracje z systemami zewnętrznymi przez kolejki **Kafka** (zdarzenia płatności).",
  source: "notes",
  source_quote: "Kafka w projekcie płatności przez około 3 lata",
};

function plain(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

function unbolded(html: string, term: string): number {
  return html.split(term).length - 1 - (html.split(`<strong>${term}</strong>`).length - 1);
}

function check(key: string, label: string, severity: QcCheck["severity"], items: QcCheck["items"]): QcCheck {
  return { key, label, severity, status: items.length ? "fail" : "pass", summary: items.length ? null : "OK", items };
}

function checksFor(html: string, confirmed: ReadonlySet<string>): QcCheck[] {
  const text = plain(html);
  return [
    check(
      "critical_skills",
      "Umiejętności krytyczne opisane w rolach",
      "blocking",
      text.includes("kolejki Kafka")
        ? []
        : [
            {
              key: "critical_skills|kafka|software house przyklad — java developer",
              requirement: "Kafka",
              role: "Software House Przykład — Java Developer",
              role_index: 1,
              fix: "ai",
              detail: "W tej roli nie ma zdania o tym, co kandydatka robiła z Kafką.",
              evidence: "Integracje przez Kafkę: zdarzenia płatności i rozliczeń.",
              evidence_kind: "description",
            },
          ],
    ),
    check(
      "no_unsupported",
      "Zgodność z oryginałem",
      "blocking",
      text.includes(UNSUPPORTED) && !confirmed.has(UNSUPPORTED)
        ? [
            {
              key: "no_unsupported|jenkins|cv",
              term: UNSUPPORTED,
              fix: "remove_term",
              detail: "Nie ma tego w oryginalnym CV ani w notatkach.",
            },
          ]
        : [],
    ),
    check(
      "must_bolded",
      "Must-have pogrubione",
      "warning",
      unbolded(html, UNBOLDED) > 0
        ? [{ key: "must_bolded|postgresql|cv", requirement: UNBOLDED, term: UNBOLDED, fix: "bold_all" }]
        : [],
    ),
    check(
      "spelling",
      "Pisownia technologii",
      "warning",
      text.includes(MISSPELLED)
        ? [{ key: "spelling|github|cv", term: MISSPELLED, fix: "spelling", detail: "„Github” → „GitHub”" }]
        : [],
    ),
    check("dates", "Daty w rolach", "warning", []),
    check("client_rules", "Reguły klienta", "blocking", []),
  ];
}

const ISSUES: CvEditorIssuesData = {
  generated_document_id: 77,
  generator_warnings: [
    "MUST-HAVE: wymaganie „Kafka” ma pokrycie tylko w notatce ze screeningu — potwierdź przed wysyłką.",
    "WERYFIKUJ: rola „Java Developer” nie ma w oryginale miesiąca zakończenia — przyjęto 02.2021.",
    "Wyróżnienia: pogrubiono 6 wystąpień wymagań must-have.",
  ],
  content_review: {
    status: "reviewed",
    version: 2,
    findings: [{ text: "Przeglądy kodu i wdrażanie młodszych programistów.", status: "unsupported" }],
  },
};

const NO_ISSUES: CvEditorIssuesData = {
  generated_document_id: 77,
  generator_warnings: [],
  content_review: { status: "verified", version: 2, findings: [] },
};

/** Uwagi generatora dla wyniku generatora bez rekrutacji (`?state=nosources`). */
export const GENERATOR_ONLY_WARNINGS: readonly string[] = ISSUES.generator_warnings;

function bold(text: string): string {
  return text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

/** Treść po wszystkich poprawkach z listy — stan „Bez uwag”. */
export function withoutIssues(html: string): string {
  return html
    .replaceAll(`, ${UNSUPPORTED}`, "")
    .replaceAll(MISSPELLED, "GitHub")
    .replaceAll(UNBOLDED, `<strong>${UNBOLDED}</strong>`)
    .replace(KAFKA_LINE, bold(KAFKA_FIX.proposed_text));
}

/** Pominięcie z pamięci harnessu — autor fikcyjny, data z chwili kliknięcia. */
function memoryDismissal(id: number, reason: QcDismissReason, note: string | undefined): QcDismissal {
  return {
    id,
    reason,
    reason_label: QC_DISMISS_REASONS.find((option) => option.code === reason)?.label ?? reason,
    note: note ?? null,
    by_name: "Marta Testowa",
    at: new Date().toISOString(),
  };
}

/** Pozycje z pominiętym kluczem przechodzą do `dismissed_items`; sprawdzenie bez pozycji przechodzi. */
function withDismissals(checks: QcCheck[], dismissed: ReadonlyMap<string, QcDismissal>): QcCheck[] {
  return checks.map((item) => {
    const hidden = item.items.filter((entry) => entry.key && dismissed.has(entry.key));
    if (hidden.length === 0) return item;
    const kept = item.items.filter((entry) => !hidden.includes(entry));
    return {
      ...item,
      items: kept,
      status: kept.length === 0 && item.status === "fail" ? "pass" : item.status,
      summary: kept.length === 0 ? `OK · pominięte: ${hidden.length}` : item.summary,
      dismissed_items: hidden.map((entry) => ({ ...entry, dismissal: dismissed.get(entry.key ?? "") ?? null })),
    };
  });
}

export function memoryIssuesApi(savedHtml: () => string, variant: IssuesVariant): CvEditorIssuesApi {
  const confirmed = new Set<string>();
  const confirmations: QcConfirmation[] = [];
  let nextId = 1;
  const dismissedQc = new Map<string, QcDismissal>();
  const dismissedIssues: CvDismissedIssue[] = [];

  const issues = (): CvEditorIssuesData => {
    const base = variant === "clean" ? NO_ISSUES : ISSUES;
    const hidden = (source: CvDismissedIssue["source"], text: string, status: string | null) =>
      dismissedIssues.some((d) => d.source === source && d.text === text && d.status === status);
    return {
      ...base,
      generator_warnings: base.generator_warnings.filter((text) => !hidden("generator", text, null)),
      content_review: {
        ...base.content_review,
        findings: base.content_review.findings.filter((f) => !hidden("review", f.text, f.status)),
      },
      dismissed: [...dismissedIssues],
    };
  };

  const result = (): QcResult => {
    const checks = withDismissals(checksFor(savedHtml(), confirmed), dismissedQc);
    const blocking = checks.filter((item) => item.status === "fail" && item.severity === "blocking").length;
    return {
      stage_id: 901,
      candidate_id: 101,
      candidate_name: "Anna Przykładowa",
      job_id: 201,
      job_title: "Senior Java Developer",
      client_name: "Bank Przykładowy",
      passed: blocking === 0,
      blocking_failed: blocking,
      warnings_count: checks.filter((item) => item.status === "fail" && item.severity === "warning").length,
      override: null,
      advisory: true,
      can_override: true,
      confirmations,
      run_id: null,
      computed_at: new Date().toISOString(),
      cv: {
        source: "branded_draft",
        editable: true,
        stage_id: 901,
        generated_document_id: 77,
        document_id: null,
        filename: null,
        bold_known: true,
        updated_at: null,
        edit_revision: 0,
        blocks: [],
      },
      original_cv: { source: "snapshot", filename: "Anna Przykładowa — CV.pdf", text: null },
      client_request: { must: ["Java 17", "Spring Boot", "Kafka", UNBOLDED], nice: [], critical: ["Kafka"], critical_source: "dl" },
      checks,
    };
  };
  const qc = async (): Promise<QcResult> => {
    if (variant === "down") throw Object.assign(new Error("preview: QC niedostępne"), { response: { status: 500 } });
    return result();
  };

  return {
    qc,
    persistQc: qc,
    issues: async () => issues(),
    dismiss: async (_stageId, body) => {
      dismissedQc.set(body.key, memoryDismissal(nextId++, body.reason, body.note));
      return result();
    },
    restore: async (_stageId, dismissalId) => {
      for (const [key, dismissal] of dismissedQc) if (dismissal.id === dismissalId) dismissedQc.delete(key);
      return result();
    },
    dismissIssue: async (_stageId, body) => {
      dismissedIssues.unshift({
        source: body.source,
        text: body.text,
        status: body.source === "review" ? (body.status ?? null) : null,
        dismissal: memoryDismissal(nextId++, body.reason, body.note),
      });
      return issues();
    },
    restoreIssue: async (_stageId, dismissalId) => {
      const index = dismissedIssues.findIndex((d) => d.dismissal.id === dismissalId);
      if (index >= 0) dismissedIssues.splice(index, 1);
      return issues();
    },
    fixes: async () => ({ status: "ok", cached: false, fixes: [KAFKA_FIX] }),
    confirm: async (_stageId, body) => {
      confirmed.add(body.term);
      confirmations.unshift({
        text: body.text ? `${body.term}: ${body.text}` : `${body.term} — potwierdzone z kandydatem`,
        by_name: "Marta Testowa",
        at: new Date().toISOString(),
      });
      return result();
    },
    transform: async (_stageId, body) => {
      let html = body.content_html;
      const applied: QcTransformApplied[] = [];
      const skipped: QcTransformSkipped[] = [];
      for (const action of body.actions) {
        let next = html;
        if (action.action === "spelling") next = html.replaceAll(MISSPELLED, "GitHub");
        else if (action.action === "bold_all") {
          next = html.replace(new RegExp(`(?<!<strong>)${UNBOLDED}(?!</strong>)`, "g"), `<strong>${UNBOLDED}</strong>`);
        } else if (action.action === "remove_term" || (action.action === "ai_fix" && action.text)) {
          if (body.bulk) {
            skipped.push({ action: action.action, code: "not_in_bulk", message: "Tę poprawkę zatwierdza się pojedynczo." });
            continue;
          }
          next =
            action.action === "remove_term"
              ? html.replaceAll(`, ${action.term}`, "")
              : html.replace(KAFKA_LINE, bold(action.text ?? ""));
        } else next = html.replace(KAFKA_LINE, bold(KAFKA_FIX.proposed_text));
        if (next === html) {
          skipped.push({ action: action.action, code: "nothing_to_do", message: "Tej poprawki nie ma już na czym nałożyć." });
          continue;
        }
        html = next;
        applied.push({ action: action.action });
      }
      return { content_html: html, changed: applied.length > 0, applied, skipped };
    },
  };
}
