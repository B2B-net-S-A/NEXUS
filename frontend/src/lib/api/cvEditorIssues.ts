// Dane panelu „Do poprawy” w edytorze CV (Edytor CV 2, PR 2).
//
// Trzy źródła tego, co system już wie o CV: QC CV pary (`lib/api/cvQc.ts`),
// uwagi generatora i wynik kontroli AI ostatniej zatwierdzonej wersji
// (`GET …/cv/branded/issues`). Edytor bierze je przez `CvEditorIssuesApi` —
// harness `/preview/cv-editor` podaje wersję z pamięci, bo podgląd nie ma sieci.

import api from "@/lib/api";
import type {
  QcConfirmBody,
  QcDismissal,
  QcDismissBody,
  QcDismissReason,
  QcFixesResponse,
  QcResult,
  QcTransformBody,
  QcTransformResult,
} from "@/lib/api/cvQc";

/** Uwaga kontroli AI z tekstem linii CV, której dotyczy. */
export interface CvReviewFinding {
  text: string;
  /** `unsupported` | `contradicted` | `private` | `invalid_evidence`. */
  status: string;
}

/** Uwaga generatora albo kontroli AI oznaczona „To nieprawda” (D5, 13.10.2026). */
export interface CvDismissedIssue {
  source: "generator" | "review";
  text: string;
  /** Status kontroli AI; `null` przy uwadze generatora. */
  status: string | null;
  dismissal: QcDismissal;
}

export interface CvEditorIssuesData {
  generated_document_id: number | null;
  generator_warnings: string[];
  content_review: {
    status: "verified" | "reviewed" | "unverified" | null;
    /** Zatwierdzona wersja, której dotyczy kontrola (biegnie po „Zapisz”). */
    version: number | null;
    findings: CvReviewFinding[];
  };
  /** Pominięte uwagi — serwer zdejmuje je z list wyżej. Starsza odpowiedź ich nie ma. */
  dismissed?: CvDismissedIssue[];
}

/** „To nieprawda” przy uwadze generatora albo kontroli AI — tekst jak na liście. */
export interface CvIssueDismissBody {
  source: "generator" | "review";
  text: string;
  status?: string | null;
  reason: QcDismissReason;
  note?: string;
}

export interface CvEditorIssuesApi {
  /** QC zapisanego szkicu BEZ zapisu przebiegu — panel odświeża go po każdym autozapisie. */
  qc: (stageId: number) => Promise<QcResult>;
  /** QC z zapisem przebiegu — raz, przy zamknięciu edytora (czyta go Tablica). */
  persistQc: (stageId: number) => Promise<QcResult>;
  issues: (stageId: number) => Promise<CvEditorIssuesData>;
  fixes: (stageId: number) => Promise<QcFixesResponse>;
  transform: (stageId: number, body: QcTransformBody) => Promise<QcTransformResult>;
  confirm: (stageId: number, body: QcConfirmBody) => Promise<QcResult>;
  /** „To nieprawda” przy uwadze QC — świeży wynik QC. */
  dismiss: (stageId: number, body: QcDismissBody) => Promise<QcResult>;
  restore: (stageId: number, dismissalId: number) => Promise<QcResult>;
  /** „To nieprawda” przy uwadze generatora albo kontroli AI — świeża lista uwag. */
  dismissIssue: (stageId: number, body: CvIssueDismissBody) => Promise<CvEditorIssuesData>;
  restoreIssue: (stageId: number, dismissalId: number) => Promise<CvEditorIssuesData>;
}

const qcPath = (stageId: number) => `/api/pipeline/stages/${stageId}/qc`;
const issuesPath = (stageId: number) => `/api/candidates/stages/${stageId}/cv/branded/issues`;

export const networkIssuesApi: CvEditorIssuesApi = {
  qc: (stageId) => api.get<QcResult>(qcPath(stageId), { params: { transient: true } }).then((r) => r.data),
  persistQc: (stageId) => api.get<QcResult>(qcPath(stageId)).then((r) => r.data),
  issues: (stageId) => api.get<CvEditorIssuesData>(issuesPath(stageId)).then((r) => r.data),
  fixes: (stageId) => api.post<QcFixesResponse>(`${qcPath(stageId)}/fixes`).then((r) => r.data),
  transform: (stageId, body) =>
    api.post<QcTransformResult>(`${qcPath(stageId)}/transform`, body).then((r) => r.data),
  confirm: (stageId, body) => api.post<QcResult>(`${qcPath(stageId)}/confirm`, body).then((r) => r.data),
  dismiss: (stageId, body) => api.post<QcResult>(`${qcPath(stageId)}/dismiss`, body).then((r) => r.data),
  restore: (stageId, dismissalId) =>
    api.post<QcResult>(`${qcPath(stageId)}/dismissals/${dismissalId}/restore`).then((r) => r.data),
  dismissIssue: (stageId, body) =>
    api.post<CvEditorIssuesData>(`${issuesPath(stageId)}/dismiss`, body).then((r) => r.data),
  restoreIssue: (stageId, dismissalId) =>
    api.post<CvEditorIssuesData>(`${issuesPath(stageId)}/dismissals/${dismissalId}/restore`).then((r) => r.data),
};

export const cvEditorQcQueryKey = (stageId: number) => ["cv-editor-qc", stageId] as const;
export const cvEditorIssuesQueryKey = (stageId: number) => ["cv-editor-issues", stageId] as const;
