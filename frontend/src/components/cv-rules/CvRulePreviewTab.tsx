"use client";

/**
 * Zakładka „Podgląd": dokładny blok promptu + CV próbne.
 *
 * CV próbne = ten sam kandydat i ta sama rekrutacja u tego klienta,
 * wygenerowane z regułą i bez, obok siebie, z zaznaczonymi różnicami. Dwie
 * generacje kosztują dwa obciążenia kwoty i trwają 2-3 minuty, więc lecą
 * w tle — interfejs odpytuje wiersz podglądu co kilka sekund.
 *
 * Kandydat i rekrutacja pochodzą z tych samych endpointów, których używa
 * generator; lista rekrutacji jest zawężona do TEGO klienta, bo reguła
 * innego klienta na cudzej rekrutacji niczego by nie pokazała.
 */

import { CvSourcePicker, useCvSourceSelection } from "@/components/v2/cv-generator/CvSourcePicker";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { downloadBlob } from "@/lib/cv-generator";
import type { RecruitmentOption } from "@/lib/cv-generator";
import {
  cvRulesApi,
  type CvRuleLanguage,
  type PreviewVariant,
  type RulePreview,
} from "@/lib/cv-rules";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface CandidateOption {
  id: number;
  full_name: string;
  position?: string | null;
  email?: string | null;
}

interface Props {
  clientId: number;
  /** Reguła po zapisie — podgląd promptu czyta stan ZAPISANY, więc po
   * edycji bez zapisu pokazuje poprzednią treść; mówimy o tym wprost. */
  dirty: boolean;
  /** Id ostatniego CV próbnego — trzymane w edytorze, żeby przeżyło
   * przełączenie zakładki. */
  previewId: number | null;
  onPreviewId: (id: number | null) => void;
}


type Payload = Record<string, unknown>;

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((v) => String(v)) : [];
}

function roles(payload: Payload | null): Array<Record<string, unknown>> {
  const list = payload?.experience;
  return Array.isArray(list)
    ? list.filter((r): r is Record<string, unknown> => !!r && typeof r === "object")
    : [];
}

function sectionCounts(payload: Payload | null): Record<string, number> {
  return {
    education: strings(payload?.education).length || (Array.isArray(payload?.education) ? payload!.education.length : 0),
    certifications: strings(payload?.certifications).length,
    languages: strings(payload?.languages).length,
    skills: Array.isArray(payload?.skills) ? payload!.skills.length : 0,
  };
}

function VariantColumn({
  title,
  variant,
  other,
  onDownload,
}: {
  title: string;
  variant: PreviewVariant | null;
  other: PreviewVariant | null;
  onDownload: () => void;
}) {
  const payload = (variant?.payload ?? null) as Payload | null;
  const otherPayload = (other?.payload ?? null) as Payload | null;
  const otherWhy = new Set(strings(otherPayload?.why_points));
  const otherBullets = new Set(
    roles(otherPayload).flatMap((r) => strings(r.responsibilities)),
  );
  const counts = sectionCounts(payload);
  const otherCounts = sectionCounts(otherPayload);
  const mark = (present: boolean) =>
    present ? "" : "rounded bg-warning-muted px-1 text-warning-muted-foreground";

  if (!payload) {
    return (
      <div className="rounded-md border p-3 text-sm text-muted-foreground">
        {title}: brak danych.
      </div>
    );
  }
  return (
    <div className="space-y-3 rounded-md border p-3 text-sm">
      <h4 className="font-semibold">{title}</h4>
      {!!variant?.rule_feedback?.length && <ul className="space-y-1 text-xs" aria-label="Kontrola reguł prezentacji">
        {variant.rule_feedback.map((item, index) => <li key={`${item.field}-${index}`}>
          {item.label}: {{satisfied: "zgodne", not_applicable: "brak treści do zastosowania", conflict: "niezgodność — sprawdź", needs_review: "ocena ręczna"}[item.status]}
        </li>)}
      </ul>}
      {variant?.can_download && <Button type="button" variant="outline" size="sm" onClick={onDownload}>Pobierz DOCX — {title.toLowerCase()}</Button>}
      <p>
        <span className="text-xs text-muted-foreground">Stanowisko: </span>
        {String(payload.position ?? "—")}
      </p>
      <div>
        <p className="text-xs font-medium text-muted-foreground">
          Dlaczego ten kandydat ({strings(payload.why_points).length})
        </p>
        <ul className="list-disc space-y-0.5 pl-4">
          {strings(payload.why_points).map((p, i) => (
            <li key={i} className={mark(otherWhy.has(p))}>
              {p}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">
          Doświadczenie ({roles(payload).length} stanowisk)
        </p>
        <ul className="space-y-2">
          {roles(payload).map((r, i) => (
            <li key={i}>
              <p className="font-medium">
                {String(r.position ?? "")}{" "}
                <span className="font-normal text-muted-foreground">
                  · {String(r.company ?? "")} · {String(r.dates ?? "")}
                </span>
              </p>
              <ul className="list-disc space-y-0.5 pl-4">
                {strings(r.responsibilities).map((b, j) => (
                  <li key={j} className={mark(otherBullets.has(b))}>
                    {b}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-xs text-muted-foreground">
        Sekcje:{" "}
        {(["education", "certifications", "languages", "skills"] as const)
          .map(
            (k) =>
              `${k} ${counts[k]}${counts[k] !== otherCounts[k] ? " ≠" : ""}`,
          )
          .join(" · ")}
      </p>
      {variant?.warnings?.length ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            {variant.warnings.length} uwag
          </summary>
          <ul className="mt-1 list-disc pl-4">
            {variant.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export function CvRulePreviewTab({ clientId, dirty, previewId, onPreviewId }: Props) {
  const [language, setLanguage] = useState<CvRuleLanguage>("pl");
  const promptQuery = useQuery({
    queryKey: ["cv-rule-prompt-preview", clientId, language],
    queryFn: () => cvRulesApi.promptPreview(clientId, language),
  });

  const [candidateQuery, setCandidateQuery] = useState("");
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [stageId, setStageId] = useState<string>("");
  const sourceSelection = useCvSourceSelection(candidate?.id, true);
  const [enqueueError, setEnqueueError] = useState("");
  const [enqueuing, setEnqueuing] = useState(false);

  const candidatesQuery = useQuery({
    queryKey: ["cv-rule-preview-candidates", candidateQuery],
    enabled: candidateQuery.trim().length >= 2,
    queryFn: async () =>
      (
        await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
          params: { q: candidateQuery.trim(), limit: 10 },
        })
      ).data,
    staleTime: 30_000,
  });

  const recruitmentsQuery = useQuery({
    queryKey: ["cv-rule-preview-recruitments", candidate?.id],
    enabled: !!candidate,
    queryFn: async () =>
      (
        await api.get<RecruitmentOption[]>(
          `/api/cv-generator/candidates/${candidate!.id}/recruitments`,
        )
      ).data,
  });
  const recruitments = useMemo(
    () => (recruitmentsQuery.data ?? []).filter((r) => r.client_id === clientId),
    [recruitmentsQuery.data, clientId],
  );

  useEffect(() => {
    setStageId("");
  }, [candidate?.id]);

  const previewQuery = useQuery({
    queryKey: ["cv-rule-preview", clientId, previewId],
    enabled: previewId !== null,
    queryFn: () => cvRulesApi.getPreview(clientId, previewId!),
    refetchInterval: (q) => {
      const data = q.state.data;
      if (data?.status !== "processing") return false;
      return 4000;
    },
  });
  const preview: RulePreview | undefined = previewQuery.data;

  const selected = recruitments.find((r) => String(r.stage_id) === stageId) ?? null;

  const enqueue = async () => {
    if (!candidate || !selected || !sourceSelection.selected) return;
    setEnqueuing(true);
    setEnqueueError("");
    try {
      const row = await cvRulesApi.enqueuePreview(clientId, {
        candidate_id: candidate.id,
        cv_document_id: sourceSelection.selected.id,
        stage_id: selected.stage_id,
        language,
      });
      onPreviewId(row.id);
    } catch (err) {
      setEnqueueError(extractErrorMsg(err) || "Nie udało się uruchomić CV próbnego.");
    } finally {
      setEnqueuing(false);
    }
  };

  const downloadPreview = async (variant: "with_rule" | "without_rule") => {
    if (!preview) return;
    try {
      const response = await api.get(`/api/clients/${clientId}/cv-rule/preview/${preview.id}/docx/${variant}`, {responseType: "blob"});
      downloadBlob(response.data as Blob, preview[variant]?.filename || "cv-probne.docx");
    } catch (error) {
      setEnqueueError(extractErrorMsg(error) || "Nie udało się pobrać DOCX podglądu.");
    }
  };

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-medium">Blok promptu, który dostanie model</h4>
          <div className="flex gap-1" role="group" aria-label="Język podglądu">
            {(["pl", "en"] as const).map((l) => (
              <button
                key={l}
                type="button"
                aria-pressed={language === l}
                onClick={() => setLanguage(l)}
                className={
                  language === l
                    ? "rounded px-2 py-0.5 text-xs font-medium bg-primary text-primary-foreground"
                    : "rounded border px-2 py-0.5 text-xs text-muted-foreground"
                }
              >
                {l.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        {dirty ? (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Masz niezapisane zmiany — podgląd pokazuje stan zapisany.
          </p>
        ) : null}
        {promptQuery.isError ? (
          <p className="text-xs text-destructive">Nie udało się pobrać podglądu promptu.</p>
        ) : promptQuery.isLoading ? (
          <p className="text-xs text-muted-foreground">Ładowanie…</p>
        ) : promptQuery.data?.block ? (
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-3 font-mono text-xs">
            {promptQuery.data.block}
          </pre>
        ) : (
          <p className="text-xs text-muted-foreground">
            Reguła nie wysyła jeszcze do modelu nic poza nazwą pliku i językiem.
          </p>
        )}
        {promptQuery.data && !promptQuery.data.is_active ? (
          <p className="text-xs text-muted-foreground">
            Reguła nie jest zatwierdzona — generator jej dziś nie stosuje.
          </p>
        ) : null}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-medium">CV próbne — z regułą i bez, obok siebie</h4>
        <p className="text-xs text-muted-foreground">
          Dwie generacje (jedna rezerwacja dwóch jednostek limitu). Wynik nie
          trafia na listę „Wygenerowane CV”. Podgląd używa reguły ZAPISANEJ,
          także niezatwierdzonej.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Input
              aria-label="Szukaj kandydata"
              value={candidateQuery}
              onChange={(e) => setCandidateQuery(e.target.value)}
              placeholder="Kandydat: imię, nazwisko lub e-mail…"
            />
            {candidatesQuery.data?.length ? (
              <ul className="mt-1 max-h-40 overflow-auto rounded-md border text-sm">
                {candidatesQuery.data.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className={
                        candidate?.id === c.id
                          ? "w-full bg-primary/10 px-2 py-1 text-left"
                          : "w-full px-2 py-1 text-left hover:bg-muted"
                      }
                      onClick={() => setCandidate(c)}
                    >
                      {c.full_name}
                      {c.position ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          {c.position}
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {candidate ? (
              <p className="mt-1 text-xs">
                Wybrano: <span className="font-medium">{candidate.full_name}</span>
              </p>
            ) : null}
          </div>
          <div>
            <select
              aria-label="Rekrutacja u tego klienta"
              value={stageId}
              onChange={(e) => setStageId(e.target.value)}
              disabled={!candidate}
              className="w-full rounded-md border px-3 py-2 text-sm"
            >
              <option value="">
                {!candidate
                  ? "Najpierw wybierz kandydata"
                  : recruitmentsQuery.isLoading
                    ? "Ładowanie rekrutacji…"
                    : recruitments.length === 0
                      ? "Kandydat nie ma rekrutacji u tego klienta"
                      : "Wybierz rekrutację u tego klienta"}
              </option>
              {recruitments.map((r) => (
                <option key={r.stage_id} value={String(r.stage_id)}>
                  {r.job_title} · {r.stage}
                  {r.ready ? "" : " (niegotowa)"}
                </option>
              ))}
            </select>
            {selected && !selected.ready ? (
              <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                Ta rekrutacja nie ma kompletu: CV, profil Championa albo notatki.
              </p>
            ) : null}
          </div>
        </div>
        {candidate && <CvSourcePicker selection={sourceSelection} />}
        <div className="flex items-center gap-3">
          <Button
            type="button"
            size="sm"
            loading={enqueuing}
            disabled={!candidate || !selected || !sourceSelection.selected || enqueuing || preview?.status === "processing"}
            onClick={enqueue}
          >
            Wygeneruj CV próbne
          </Button>
          {preview?.status === "processing" ? (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Generuję obie wersje…
            </span>
          ) : null}
        </div>
        {enqueueError ? <p className="text-xs text-destructive">{enqueueError}</p> : null}
        {preview?.status === "failed" ? (
          <p className="text-xs text-destructive">
            CV próbne nie powstało: {preview.error_message ?? "nieznany błąd"}
          </p>
        ) : null}
        {preview?.status === "ready" ? (
          <div className="grid gap-3 md:grid-cols-2">
            <VariantColumn
              onDownload={() => void downloadPreview("with_rule")}
              title="Z regułą"
              variant={preview.with_rule}
              other={preview.without_rule}
            />
            <VariantColumn
              onDownload={() => void downloadPreview("without_rule")}
              title="Bez reguły"
              variant={preview.without_rule}
              other={preview.with_rule}
            />
          </div>
        ) : null}
        {preview?.status === "ready" ? (
          <p className="text-xs text-muted-foreground">
            Podświetlone punkty występują tylko w jednej z wersji.
          </p>
        ) : null}
      </section>
    </div>
  );
}
