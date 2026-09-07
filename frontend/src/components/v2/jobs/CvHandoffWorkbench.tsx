"use client";

/**
 * CvHandoffWorkbench — stanowisko „CV do klienta" (krok 06 programu „flow
 * w języku C2", docs/c2-flow-program.md, PR 6/7).
 *
 * Najbardziej rozproszony krok procesu: generator CV to osobna strona,
 * brandowane CV robi się z profilu kandydata, link dla klienta z innego
 * modalu, a stawka do klienta z modalu przy przeciąganiu karty na „CV
 * Wysłane". Ten ekran ustawia to w kolejności wysyłki — kolejka zweryfikowanych
 * i reguły klienta po lewej, przygotowanie CV w środku, wysyłka w doku —
 * **nie odbierając żadnego z dotychczasowych miejsc**: `/cv-generator`, modale
 * na profilu i ruch z tablicy działają dokładnie jak dotąd.
 *
 * Zero nowych endpointów: `client-rate`, `share-token`, `pipeline/move`,
 * `cv/original`, `cv/branded` i sam generator — wszystko istniejące.
 */

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileText,
  HelpCircle,
  Link2,
  Loader2,
  Send,
  Settings2,
  UserX,
  Users,
} from "lucide-react";

import {
  candidateStageCvApi,
  candidatesApi,
  extractErrorMsg,
  pipelineApi,
  type CVBrandedState,
  type CVOriginalSnapshot,
  type RateUnit,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ClientCvRuleBanner,
  useClientCvRule,
} from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { useClientPlaybook } from "@/lib/client-playbooks";
import { CVGeneratorStandaloneV2 } from "@/components/v2/pages/CVGeneratorStandaloneV2";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { RATE_UNIT_LABELS, RATE_UNIT_SHORT } from "@/lib/verified-rate-gate";
import {
  CV_SENT_STAGE,
  countAtClient,
  findStageColumn,
  itemFullName,
  moveBlockedReason,
  selectVerifiedQueue,
} from "@/lib/pipeline-flow";
import {
  CvHandoffError,
  describeCvHandoffFailure,
  describeCvHandoffSuccess,
  runCvHandoff,
  type CvHandoffPlan,
} from "@/lib/cv-handoff";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";

// Edytor brandowanego CV jest ciężki (rich text) — leniwy import, ten sam
// wzorzec co w `PipelineCandidateDock`.
const CVBrandedEditModal = dynamic(
  () =>
    import("@/components/v2/modals/CVBrandedEditModal").then(
      (m) => m.CVBrandedEditModal,
    ),
  { ssr: false },
);

export interface CvHandoffWorkbenchProps {
  jobId: number;
  jobTitle?: string;
  clientId: number | null;
  columns: KanbanColumn[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  onRetry: () => void;
  /** Odśwież kanban po udanym ruchu (strona trzyma klucz zapytania). */
  onMoved: () => void;
  readOnly: boolean;
}

const SHARE_DAYS_OPTIONS = [7, 14, 30, 60, 90];

export function CvHandoffWorkbench({
  jobId,
  jobTitle,
  clientId,
  columns,
  isLoading,
  isError,
  error,
  isSuccess,
  onRetry,
  onMoved,
  readOnly,
}: CvHandoffWorkbenchProps) {
  const { showSuccess, showError } = useToast();

  const queue = useMemo(() => selectVerifiedQueue(columns), [columns]);
  const cvSentCol = useMemo(
    () => findStageColumn(columns, CV_SENT_STAGE),
    [columns],
  );
  const atClient = useMemo(() => countAtClient(columns), [columns]);

  const [selectedStageId, setSelectedStageId] = useState<number | null>(null);
  useEffect(() => {
    if (queue.length === 0) {
      setSelectedStageId(null);
      return;
    }
    setSelectedStageId((prev) =>
      prev != null && queue.some((e) => e.item.id === prev)
        ? prev
        : queue[0].item.id,
    );
  }, [queue]);
  const selected = queue.find((e) => e.item.id === selectedStageId) ?? null;
  const stageId = selected?.item.id ?? null;
  const fullName = selected ? itemFullName(selected.item) : "";
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;

  // ── Reguły klienta (te same, które generator pokazuje po wyborze klienta) ─
  const cvRuleQuery = useClientCvRule(clientId);
  const playbookQuery = useClientPlaybook(clientId);
  const cvLimit = playbookQuery.data?.cv_limit_per_process ?? null;

  // ── Snapshoty tej rekrutacji ────────────────────────────────────────────
  const [openOriginal, setOpenOriginal] = useState(false);
  const [openBranded, setOpenBranded] = useState(false);
  const originalQuery = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () => candidateStageCvApi.original.get(stageId!).then((r) => r.data),
    enabled: stageId != null,
  });
  const brandedQuery = useQuery<CVBrandedState>({
    queryKey: ["cv-branded", stageId],
    queryFn: () => candidateStageCvApi.branded.get(stageId!).then((r) => r.data),
    enabled: stageId != null,
  });
  const brandedStatus = brandedQuery.data?.status ?? "none";
  const brandedFinalized = brandedStatus === "finalized";

  // ── Dok: stawka do klienta + link ───────────────────────────────────────
  const [clientRate, setClientRate] = useState("");
  const [clientRateUnit, setClientRateUnit] = useState<RateUnit>("monthly");
  const [shareDays, setShareDays] = useState(14);
  const [createLink, setCreateLink] = useState(true);
  const [lastShareSuffix, setLastShareSuffix] = useState<string | null>(null);
  useEffect(() => {
    setClientRate("");
    setClientRateUnit("monthly");
    setLastShareSuffix(null);
  }, [selectedStageId]);

  const numericClientRate = Number.parseFloat(clientRate.replace(",", "."));
  const clientRateValid =
    Number.isFinite(numericClientRate) && numericClientRate > 0;
  // Link tylko przy sfinalizowanym CV brandowanym — backend odbija 409, więc
  // bramka jest widoczna z powodem, a nie niespodzianką po kliknięciu.
  const linkBlockedReason = brandedFinalized
    ? null
    : "Link dla klienta wymaga sfinalizowanego CV brandowanego — utwórz je poniżej albo wyślij bez linku.";
  const willCreateLink = createLink && brandedFinalized;

  const moveBlocked = selected
    ? (moveBlockedReason({ item: selected.item, readOnly }) ??
      (!cvSentCol
        ? "Szablon tej rekrutacji nie ma kolumny „CV Wysłane”."
        : selected.item.verification_status === "pending"
          ? "Stawka kandydata czeka na akceptację — ruch po zatwierdzeniu weryfikacji."
          : null))
    : "Wybierz kandydata z kolejki.";

  const sendMut = useMutation({
    mutationFn: async () => {
      if (!selected || !cvSentCol || stageId == null) {
        throw new Error("Brak etapu docelowego.");
      }
      const plan: CvHandoffPlan = {
        clientRate: clientRateValid
          ? {
              value: numericClientRate,
              unit: clientRateUnit,
              currency: "PLN",
            }
          : null,
        shareLink: willCreateLink ? { expiresInDays: shareDays } : null,
      };
      return runCvHandoff(plan, {
        saveClientRate: async (r) => {
          await candidatesApi.setRecruitmentClientRate(
            selected.item.candidate_id,
            jobId,
            {
              rate_value: r.value,
              rate_unit: r.unit,
              rate_currency: r.currency,
            },
          );
        },
        createShareLink: async ({ expiresInDays }) => {
          const res = await candidateStageCvApi.share.create(
            stageId,
            expiresInDays,
          );
          return { shareUrlSuffix: res.data?.share_url_suffix ?? null };
        },
        move: async () => {
          await pipelineApi.move({
            candidate_id: selected.item.candidate_id,
            job_id: jobId,
            stage: CV_SENT_STAGE,
            stage_def_id: cvSentCol.stage_def_id ?? undefined,
          });
        },
      });
    },
    onSuccess: (result) => {
      setLastShareSuffix(result.shareUrlSuffix);
      showSuccess(describeCvHandoffSuccess(result));
      onMoved();
    },
    onError: (e) => {
      if (e instanceof CvHandoffError) {
        showError(describeCvHandoffFailure(e, extractErrorMsg(e.reason)));
        return;
      }
      showError(extractErrorMsg(e) || "Nie udało się wysłać CV do klienta.");
    },
  });

  const viewState = resolveViewState({ isLoading, isError, error, isSuccess });

  if (viewState === "loading") {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (
    viewState === "forbidden" ||
    viewState === "not_found" ||
    viewState === "error"
  ) {
    return (
      <QueryStateNotice
        state={viewState}
        className="rounded-xl"
        description={
          viewState === "forbidden"
            ? "Twoja rola nie ma dostępu do pipeline'u tej rekrutacji — to nie znaczy, że nikt nie czeka na wysyłkę CV."
            : undefined
        }
        onRetry={onRetry}
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {/* ── Lewa kolumna: kolejka + warunki klienta ─────────────────────── */}
      <aside className="space-y-4 self-start rounded-xl border border-border bg-card p-4">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <Users className="h-4 w-4 text-primary" />
          Zweryfikowani
          <Badge variant="outline" size="sm" className="ml-auto tabular-nums">
            {queue.length}
          </Badge>
        </div>

        {queue.length > 0 ? (
          <div className="space-y-0.5" role="list" aria-label="Zweryfikowani kandydaci">
            {queue.map(({ item }) => {
              const active = item.id === selectedStageId;
              return (
                <div key={item.id} role="listitem">
                  <button
                    type="button"
                    onClick={() => setSelectedStageId(item.id)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                      active
                        ? "bg-primary/10 font-medium text-primary"
                        : "text-foreground hover:bg-accent",
                    )}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        item.hm_veto
                          ? "bg-destructive"
                          : item.verification_status === "pending"
                            ? "bg-warning"
                            : "bg-success",
                      )}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {itemFullName(item)}
                    </span>
                    {item.expected_rate_value != null && (
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {item.expected_rate_value}
                        {item.expected_rate_unit
                          ? ` ${RATE_UNIT_SHORT[item.expected_rate_unit]}`
                          : ""}
                      </span>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Nikt nie jest dziś zweryfikowany. Zamknij screening w kroku
            „Screening”, żeby kandydat trafił tutaj.
          </p>
        )}

        <div className="space-y-2 border-t border-border pt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Warunki klienta
          </div>
          {clientId == null ? (
            <p className="text-xs text-muted-foreground">
              Ta rekrutacja nie ma przypiętego klienta — żadna reguła CV nie
              obowiązuje, a nazwa pliku będzie ogólna.
            </p>
          ) : (
            <>
              <ClientCvRuleBanner
                clientId={clientId}
                rule={cvRuleQuery.data}
                isLoading={cvRuleQuery.isLoading}
                isError={cvRuleQuery.isError}
              />
              <div className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-xs">
                <span className="text-muted-foreground">Limit CV na proces</span>
                <span className="tabular-nums text-foreground">
                  {playbookQuery.isLoading
                    ? "…"
                    : cvLimit != null
                      ? `${atClient} z ${cvLimit}`
                      : `${atClient} u klienta`}
                </span>
              </div>
              {cvLimit != null && atClient >= cvLimit && (
                <p className="inline-flex items-start gap-1 text-xs text-warning-muted-foreground">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  Limit CV tego klienta jest wyczerpany — potwierdź z Delivery
                  Leadem przed kolejną wysyłką.
                </p>
              )}
              <Link
                href={`/settings/cv-rules?client=${clientId}`}
                className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
              >
                <Settings2 className="h-3 w-3" /> Reguły CV klienta (DL)
              </Link>
            </>
          )}
        </div>
      </aside>

      {/* ── Środek: przygotowanie CV ────────────────────────────────────── */}
      <div className="min-w-0 space-y-4">
        {!selected ? (
          <div className="rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center text-sm text-muted-foreground">
            <FileText className="mx-auto mb-2 h-6 w-6 opacity-40" />
            {queue.length === 0
              ? "Nikt nie czeka na wysyłkę CV — kolejka zweryfikowanych jest pusta."
              : "Wybierz kandydata z kolejki po lewej."}
          </div>
        ) : (
          <>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground">
                  CV · {fullName}
                </h2>
                {selected.item.verification_status === "pending" && (
                  <Badge variant="warning" size="sm">
                    <HelpCircle className="h-2.5 w-2.5" /> Stawka czeka na
                    akceptację
                  </Badge>
                )}
                {selected.item.hm_veto && (
                  <Badge
                    variant="danger"
                    size="sm"
                    title={`Powód: ${selected.item.hm_veto.rejection_reason_name}`}
                  >
                    <UserX className="h-2.5 w-2.5" /> Weto HM
                  </Badge>
                )}
                <Link
                  href={`/candidates/${selected.item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
                  className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <ExternalLink className="h-3 w-3" /> Pełny profil
                </Link>
              </div>
            </div>

            {/* Snapshoty tej rekrutacji — te same modale, co na profilu. */}
            <div className="space-y-2 rounded-xl border border-border bg-card p-4">
              <div className="text-xs font-semibold text-foreground">
                Snapshoty tej rekrutacji
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {originalQuery.isLoading ? (
                  <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                ) : originalQuery.data?.has_snapshot ? (
                  <Badge size="sm" variant="success">
                    CV oryginalne
                  </Badge>
                ) : (
                  <Badge size="sm" variant="warning">
                    Brak CV w momencie zgłoszenia
                  </Badge>
                )}
                {brandedFinalized ? (
                  <Badge size="sm" variant="success">
                    Brandowane: zfinalizowane
                  </Badge>
                ) : brandedStatus === "draft" ? (
                  <Badge size="sm" variant="info">
                    Brandowane: draft
                  </Badge>
                ) : (
                  <Badge size="sm" variant="neutral">
                    Brandowane: brak
                  </Badge>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setOpenOriginal(true)}
                >
                  <FileText className="h-3.5 w-3.5" /> Pokaż CV oryginalne
                </Button>
                {!readOnly && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setOpenBranded(true)}
                  >
                    <FileText className="h-3.5 w-3.5" />{" "}
                    {brandedStatus === "none"
                      ? "Stwórz brandowane"
                      : "Edytuj brandowane"}
                  </Button>
                )}
              </div>
            </div>

            {/* Generator CV — ten sam komponent co `/cv-generator`, osadzony
                z wypełnionym krokiem 1 (kandydat) i rekrutacją. */}
            <div className="rounded-xl border border-border bg-card p-4">
              <CVGeneratorStandaloneV2
                embedded
                prefillCandidateId={selected.item.candidate_id}
                prefillCandidateName={fullName}
                prefillJobId={jobId}
              />
            </div>
          </>
        )}
      </div>

      {/* ── Dok: wysyłka do klienta ─────────────────────────────────────── */}
      <aside className="lg:col-span-2 xl:sticky xl:top-4 xl:col-span-1 xl:self-start">
        <div className="space-y-4 rounded-xl border border-border bg-card p-4">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-primary">
              Wysyłka do klienta
            </div>
            <div className="truncate text-sm font-semibold text-foreground">
              {selected ? fullName : "Nikt nie wybrany"}
            </div>
          </div>

          {selected ? (
            <>
              <div
                className={cn(
                  "flex items-start gap-2 rounded-md border px-3 py-2 text-xs",
                  moveBlocked
                    ? "border-warning/30 bg-warning-muted text-warning-muted-foreground"
                    : "border-success/30 bg-success-muted text-success-muted-foreground",
                )}
                role="status"
              >
                {moveBlocked ? (
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                ) : (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                )}
                <span>
                  {moveBlocked ?? "Bramka: brak przeciwwskazań — ruch przejdzie."}
                </span>
              </div>

              <div className="space-y-2">
                <div className="text-xs font-semibold text-foreground">
                  Stawka do klienta
                </div>
                <div className="grid grid-cols-[1.2fr_minmax(0,1fr)] gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="cv-client-rate">Kwota</Label>
                    <input
                      id="cv-client-rate"
                      type="number"
                      inputMode="decimal"
                      step="0.01"
                      min="0"
                      value={clientRate}
                      disabled={readOnly}
                      onChange={(e) => setClientRate(e.target.value)}
                      placeholder="np. 25000"
                      className="h-10 w-full rounded-md border border-border bg-card px-3 focus:outline-hidden focus:ring-2 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="cv-client-rate-unit">Jednostka</Label>
                    <Select
                      value={clientRateUnit}
                      onValueChange={(v) => setClientRateUnit(v as RateUnit)}
                      disabled={readOnly}
                    >
                      <SelectTrigger id="cv-client-rate-unit" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(Object.keys(RATE_UNIT_LABELS) as RateUnit[]).map(
                          (u) => (
                            <SelectItem key={u} value={u}>
                              {RATE_UNIT_LABELS[u]}
                            </SelectItem>
                          ),
                        )}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Puste pole = wysyłka bez stawki (dawne „Pomiń”). Uzupełnisz ją
                  później na karcie rekrutacji w profilu kandydata.
                </p>
              </div>

              <div className="space-y-2 border-t border-border pt-3">
                <div className="text-xs font-semibold text-foreground">
                  Link dla klienta
                </div>
                <label className="flex cursor-pointer items-start gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={createLink}
                    disabled={readOnly || !brandedFinalized}
                    onChange={(e) => setCreateLink(e.target.checked)}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-border accent-primary disabled:cursor-not-allowed"
                  />
                  <span
                    className={cn(
                      !brandedFinalized && "text-muted-foreground",
                    )}
                  >
                    Utwórz link do brandowanego CV
                  </span>
                </label>
                {linkBlockedReason ? (
                  <p className="text-[11px] text-muted-foreground">
                    {linkBlockedReason}
                  </p>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="cv-share-days">Ważność linku</Label>
                    <Select
                      value={String(shareDays)}
                      onValueChange={(v) => setShareDays(Number(v))}
                      disabled={readOnly || !createLink}
                    >
                      <SelectTrigger id="cv-share-days" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SHARE_DAYS_OPTIONS.map((d) => (
                          <SelectItem key={d} value={String(d)}>
                            {d} dni
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                {lastShareSuffix && (
                  <p className="break-all text-[11px] text-muted-foreground">
                    Ostatni link: <code>{lastShareSuffix}</code>
                  </p>
                )}
              </div>

              {!readOnly && (
                <div className="space-y-1.5 border-t border-border pt-3">
                  <Button
                    className="w-full justify-center"
                    disabled={Boolean(moveBlocked) || sendMut.isPending}
                    loading={sendMut.isPending}
                    title={moveBlocked ?? undefined}
                    onClick={() => sendMut.mutate()}
                  >
                    <Send className="h-4 w-4" />
                    Wyślij klientowi i przenieś na „CV Wysłane”
                  </Button>
                  <p className="text-[11px] text-muted-foreground">
                    Kolejność: stawka do klienta → link → zmiana etapu. Gdy któryś
                    krok padnie, sekwencja zatrzymuje się i mówi, co zdążyło się
                    wykonać.
                  </p>
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              Wybierz kandydata z kolejki, żeby przygotować wysyłkę.
            </p>
          )}

          <p className="border-t border-border pt-3 text-[11px] text-muted-foreground">
            <Link2 className="mr-1 inline h-3 w-3" />
            Zarządzanie istniejącymi linkami (podgląd, odwołanie) zostaje w doku
            „Karta w procesie” na tablicy Pipeline i na profilu kandydata.
          </p>
        </div>
      </aside>

      {selected && openOriginal && (
        <CVOriginalPreviewModal
          open
          onOpenChange={setOpenOriginal}
          stageId={selected.item.id}
          jobTitle={jobLabel}
          candidateName={fullName}
        />
      )}
      {selected && !readOnly && openBranded && (
        <CVBrandedEditModal
          open
          onOpenChange={setOpenBranded}
          stageId={selected.item.id}
          jobTitle={jobLabel}
          candidateName={fullName}
        />
      )}
    </div>
  );
}
