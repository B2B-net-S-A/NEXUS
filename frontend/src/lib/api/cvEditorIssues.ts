// Dane panelu „Do poprawy” w edytorze CV (Edytor CV 2, PR 2).
//
// Trzy źródła tego, co system już wie o CV: QC CV pary (`lib/api/cvQc.ts`),
// uwagi generatora i wynik kontroli AI ostatniej zatwierdzonej wersji
// (`GET …/cv/branded/issues`). Edytor bierze je przez `CvEditorIssuesApi` —
// harness `/preview/cv-editor` podaje wersję z pamięci, bo podgląd nie ma sieci.

import api from "@/lib/api";
import type {
  QcConfirmBody,
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

export interface CvEditorIssuesData {
  generated_document_id: number | null;
  generator_warnings: string[];
  content_review: {
    status: "verified" | "reviewed" | "unverified" | null;
    /** Zatwierdzona wersja, której dotyczy kontrola (biegnie po „Zapisz”). */
    version: number | null;
    findings: CvReviewFinding[];
  };
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
}

const qcPath = (stageId: number) => `/api/pipeline/stages/${stageId}/qc`;

export const networkIssuesApi: CvEditorIssuesApi = {
  qc: (stageId) => api.get<QcResult>(qcPath(stageId), { params: { transient: true } }).then((r) => r.data),
  persistQc: (stageId) => api.get<QcResult>(qcPath(stageId)).then((r) => r.data),
  issues: (stageId) =>
    api.get<CvEditorIssuesData>(`/api/candidates/stages/${stageId}/cv/branded/issues`).then((r) => r.data),
  fixes: (stageId) => api.post<QcFixesResponse>(`${qcPath(stageId)}/fixes`).then((r) => r.data),
  transform: (stageId, body) =>
    api.post<QcTransformResult>(`${qcPath(stageId)}/transform`, body).then((r) => r.data),
  confirm: (stageId, body) => api.post<QcResult>(`${qcPath(stageId)}/confirm`, body).then((r) => r.data),
};

export const cvEditorQcQueryKey = (stageId: number) => ["cv-editor-qc", stageId] as const;
export const cvEditorIssuesQueryKey = (stageId: number) => ["cv-editor-issues", stageId] as const;
