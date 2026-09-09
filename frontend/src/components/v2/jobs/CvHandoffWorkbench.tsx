"use client";

/**
 * CvHandoffWorkbench — stanowisko „CV do klienta" (krok 06 programu „flow
 * w języku C2", docs/c2-flow-program.md; układ z makiety — fala 3).
 *
 * Najbardziej rozproszony krok procesu: generator CV to osobna strona,
 * brandowane CV robi się z profilu kandydata, link dla klienta z innego
 * modalu, a stawka do klienta z modalu przy przeciąganiu karty na „CV
 * Wysłane". Ten ekran ustawia to w kolejności wysyłki — kolejka zweryfikowanych
 * i reguły klienta po lewej, przygotowanie CV w środku, wysyłka w doku —
 * **nie odbierając żadnego z dotychczasowych miejsc**: `/cv-generator`, modale
 * na profilu i ruch z tablicy działają dokładnie jak dotąd.
 *
 * Zero nowych endpointów: `client-rate`, `share-token` (create/list/revoke),
 * `pipeline/move`, `cv/original`, `cv/branded`, `screening/share-token`
 * i sam generator — wszystko istniejące.
 */

import { useEffect, useMemo, useRef, useState } from "react";
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
  Mail,
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
  screeningApi,
  type CVBrandedState,
  type CVOriginalSnapshot,
  type CVShareTokenListItem,
  type RateUnit,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { hasRole, useAuthStore } from "@/store/auth";
import { useCapability } from "@/hooks/useCapability";
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
import { RATE_UNIT_LABELS } from "@/lib/verified-rate-gate";
import {
  CV_SENT_STAGE,
  countAtClient,
  findStageColumn,
  formatExpectedRate,
  itemFullName,
  moveBlockedReason,
  selectVerifiedQueue,
} from "@/lib/pipeline-flow";
import {
  CvHandoffError,
  computeMarginPreview,
  describeCvHandoffFailure,
  describeCvHandoffSuccess,
  runCvHandoff,
  type CvHandoffPlan,
} from "@/lib/cv-handoff";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
import {
  ChromeBanner,
  DockActions,
  DockSection,
  KvList,
  RailRow,
  RailSection,
  ReadyItem,
  ReqRow,
  ToolPill,
  WorkbenchCard,
  WorkbenchDock,
  WorkbenchHeader,
  WorkbenchRail,
  type DockTabItem,
} from "@/components/v2/jobs/workbench-chrome";
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

const CONTENT_MODE_LABEL: Record<string, string> = {
  rewrite: "Przepisanie",
  redact: "Redakcja",
  tailor: "Pod rekrutację",
};

type DockTab = "send" | "links";

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

  // `PATCH …/client-rate` stoi za `CandidateFinanceAccess` = WYŁĄCZNIE admin
  // (`CANDIDATE_FINANCE_ROLES` w `candidate_access.py`). Rekruterowi nie
  // pokazujemy pola, które gwarantowanie kończy się 403 — tablica ma ten sam
  // problem (modal stawki dla każdego), tu naprawiamy go u źródła.
  const authUser = useAuthStore((s) => s.user);
  const canWriteClientRate = hasRole(authUser, "admin");
  // `/settings/cv-rules` jest bramkowane w middleware (admin / DL, sekcja
  // Delivery write) — link dla innych ról prowadziłby wprost w 403.
  const canManageCvRules = useCapability("cv_rule.manage");

  // ── Reguły klienta (te same, które generator pokazuje po wyborze klienta) ─
  const cvRuleQuery = useClientCvRule(clientId);
  const rule = cvRuleQuery.data ?? null;
  const ruleActive = Boolean(rule?.is_active);
  const playbookQuery = useClientPlaybook(clientId);
  const cvLimit = playbookQuery.data?.cv_limit_per_process ?? null;
  const clientLabel =
    rule?.client_name?.trim() ||
    playbookQuery.data?.client_name?.trim() ||
    (clientId != null ? `klient #${clientId}` : "");

  // ── Snapshoty tej rekrutacji ────────────────────────────────────────────
  const [openOriginal, setOpenOriginal] = useState(false);
  const [openBranded, setOpenBranded] = useState(false);
  const generatorRef = useRef<HTMLDivElement | null>(null);
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
  const [dockTab, setDockTab] = useState<DockTab>("send");
  const [clientRate, setClientRate] = useState("");
  const [clientRateUnit, setClientRateUnit] = useState<RateUnit>("monthly");
  const [shareDays, setShareDays] = useState(14);
  const [createLink, setCreateLink] = useState(true);
  const [handoffResults, setHandoffResults] = useState<Array<{
    stageId: number; candidateName: string; jobTitle: string; suffix: string;
  }>>([]);
  const resultsRef = useRef(handoffResults);
  const actionStageRef = useRef<number | null>(null);
  const lastShareSuffix = [...handoffResults].reverse().find((r) => r.stageId === selectedStageId)?.suffix ?? null;
  const rememberLink = (result: (typeof handoffResults)[number]) => {
    resultsRef.current = [...resultsRef.current, result];
    setHandoffResults(resultsRef.current);
  };
  useEffect(() => {
    setClientRate("");
    setClientRateUnit("monthly");
    setCreateLink(!resultsRef.current.some((r) => r.stageId === selectedStageId));
    setDockTab("send");
  }, [selectedStageId]);

  const numericClientRate = Number.parseFloat(clientRate.replace(",", "."));
  const clientRateValid =
    Number.isFinite(numericClientRate) && numericClientRate > 0;
  const margin = computeMarginPreview({
    clientRate,
    clientUnit: clientRateUnit,
    candidateRate: selected?.item.expected_rate_value,
    candidateUnit: selected?.item.expected_rate_unit,
    candidateCurrency: selected?.item.expected_rate_currency,
  });
  // Link tylko przy sfinalizowanym CV brandowanym — backend odbija 409, więc
  // bramka jest widoczna z powodem, a nie niespodzianką po kliknięciu.
  const linkBlockedReason = brandedFinalized
    ? null
    : "Link dla klienta wymaga sfinalizowanego CV brandowanego — utwórz je poniżej albo oznacz etap bez tworzenia linku.";
  const willCreateLink = createLink && brandedFinalized;

  // Linki tego etapu — lista i odwołanie. Zapytanie startuje dopiero na
  // zakładce „Linki": kolejka bywa długa, a to jest zapytanie per kandydat.
  const linksQuery = useQuery<CVShareTokenListItem[]>({
    queryKey: ["cv-share-tokens", stageId],
    queryFn: () => candidateStageCvApi.share.list(stageId!).then((r) => r.data),
    enabled: stageId != null && dockTab === "links",
  });
  const activeLinks = (linksQuery.data ?? []).filter((t) => !t.revoked);

  const revokeAllMut = useMutation({
    mutationFn: () =>
      candidateStageCvApi.share.revokeAll(
        stageId!,
        "Odwołane z warsztatu „CV do klienta”",
      ),
    onSuccess: () => {
      showSuccess("Wcześniejsze linki odwołane.");
      void linksQuery.refetch();
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się odwołać linków."),
  });

  const championLinkMut = useMutation({
    mutationFn: () => screeningApi.createShareToken(stageId!, 30),
    onSuccess: (res) => {
      const suffix = res?.data?.share_url_suffix;
      if (suffix && typeof window !== "undefined") {
        void navigator.clipboard
          ?.writeText(`${window.location.origin}${suffix}`)
          .catch(() => undefined);
      }
      showSuccess("Link do karty Championa skopiowany (ważny 30 dni).");
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się utworzyć linku."),
  });

  const moveBlocked = selected
    ? (moveBlockedReason({ item: selected.item, readOnly }) ??
      (!cvSentCol
        ? "Szablon tej rekrutacji nie ma kolumny „CV Wysłane”."
        : brandedQuery.isLoading
          ? // Bez tego w oknie ładowania `brandedStatus` = "none", więc klik
            // wysłałby BEZ linku i zaraportował to jako świadomą decyzję.
            "Sprawdzam stan CV brandowanego…"
          : null))
    : "Wybierz kandydata z kolejki.";

  const sendMut = useMutation({
    mutationFn: async () => {
      if (!selected || !cvSentCol || stageId == null) {
        throw new Error("Brak etapu docelowego.");
      }
      actionStageRef.current = stageId;
      const plan: CvHandoffPlan = {
        clientRate: canWriteClientRate && clientRateValid
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
          const suffix = res.data?.share_url_suffix ?? null;
          if (suffix) rememberLink({ stageId, candidateName: fullName, jobTitle: jobLabel, suffix });
          return { shareUrlSuffix: suffix };
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
      // The one-time link was retained as soon as it was created, before moving.
      const summary = describeCvHandoffSuccess(result, extractErrorMsg);
      // Stawka pada PO ruchu (jak na tablicy): ruch jest faktem, ale rekruter
      // musi wiedzieć, że stawki nie ma — stąd ton błędu, nie sukcesu.
      if (result.failedAfterMove.length > 0) showError(summary);
      else showSuccess(summary);
      onMoved();
    },
    onError: (e) => {
      if (e instanceof CvHandoffError) {
        if (e.shareUrlSuffix) {
          // Sekret tokenu v2 jest zwracany RAZ — pokazujemy go w doku
          // i odznaczamy „Utwórz link", żeby ponowienie nie wystawiło drugiego.
          if (selectedStageId === actionStageRef.current) setCreateLink(false);
        }
        showError(describeCvHandoffFailure(e, extractErrorMsg(e.reason)));
        return;
      }
      showError(extractErrorMsg(e) || "Nie udało się przygotować przekazania CV.");
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

  const mailtoHref = (() => {
    const link =
      lastShareSuffix && typeof window !== "undefined"
        ? `${window.location.origin}${lastShareSuffix}`
        : null;
    const subject = `CV kandydata: ${fullName} — ${jobLabel}`;
    const body = link
      ? `Dzień dobry,\n\nprzesyłam CV kandydata ${fullName} do rekrutacji „${jobLabel}”.\nLink: ${link}\n`
      : `Dzień dobry,\n\nprzesyłam CV kandydata ${fullName} do rekrutacji „${jobLabel}”.\n`;
    // Adresat świadomie PUSTY — kontakt hiring managera nie przychodzi
    // z kanbana, a zgadnięty adres to mail wysłany nie tam, gdzie trzeba.
    return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  })();

  const dockTabs: DockTabItem[] = [
    { value: "send", label: "Przekazanie" },
    { value: "links", label: "Linki i historia" },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {handoffResults.length > 0 && (
        <section className="space-y-3 rounded-xl border border-border bg-card p-4 lg:col-span-2 xl:col-span-3" aria-label="Utworzone linki do CV">
          <h3 className="text-sm font-semibold">Utworzone linki do CV</h3>
          <p className="text-xs text-muted-foreground">Linki pozostają tutaj po zmianie etapu i wyborze kolejnego kandydata. Ten ekran nie wysyła wiadomości do klienta. Skopiuj link przed opuszczeniem tej strony.</p>
          {handoffResults.map((result, index) => (
            <div key={index} className="space-y-2 rounded-lg border border-border p-3">
              <p className="text-sm font-medium">{result.candidateName} · {result.jobTitle}</p>
              <code className="block break-all text-xs">{typeof window !== "undefined" ? window.location.origin : ""}{result.suffix}</code>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={async () => {
                  try {
                    if (!navigator.clipboard) throw new Error("clipboard unavailable");
                    await navigator.clipboard.writeText(`${window.location.origin}${result.suffix}`);
                    showSuccess("Link skopiowany.");
                  } catch { showError("Nie udało się skopiować linku. Zaznacz widoczny adres ręcznie."); }
                }}>Kopiuj link: {result.candidateName}</Button>
                <a className="inline-flex items-center rounded-lg border border-border px-3 text-xs"
                  href={`mailto:?subject=${encodeURIComponent(`CV kandydata: ${result.candidateName} — ${result.jobTitle}`)}&body=${encodeURIComponent(`Dzień dobry,\n\nCV kandydata ${result.candidateName}: ${typeof window !== "undefined" ? window.location.origin : ""}${result.suffix}\n`)}`}>
                  Przygotuj wiadomość
                </a>
              </div>
            </div>
          ))}
        </section>
      )}
      {/* ── Szyna: kolejka + reguły klienta ─────────────────────────────── */}
      <WorkbenchRail
        icon={<Users className="h-4 w-4 text-primary" />}
        title="Zweryfikowani"
        count={queue.length}
        meta={queue.length > 0 ? `${queue.length} do wysłania` : null}
        footer={
          canManageCvRules && clientId != null ? (
            <Link
              href={`/settings/cv-rules?client=${clientId}`}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
            >
              <Settings2 className="h-3.5 w-3.5" /> Reguły CV (DL) →
            </Link>
          ) : undefined
        }
      >
        {queue.length > 0 ? (
          <div className="space-y-0.5" role="list" aria-label="Zweryfikowani kandydaci">
            {queue.map(({ item }) => (
              <div key={item.id} role="listitem">
                <RailRow
                  tone={
                    item.hm_veto
                      ? "bad"
                      : item.verification_status === "pending"
                        ? "warn"
                        : "ok"
                  }
                  label={itemFullName(item)}
                  meta={
                    item.verification_status === "pending"
                      ? `${formatExpectedRate(item) ?? "—"} · pending`
                      : (formatExpectedRate(item) ?? undefined)
                  }
                  metaTone={
                    item.verification_status === "pending" ? "warn" : "neutral"
                  }
                  active={item.id === selectedStageId}
                  onSelect={() => setSelectedStageId(item.id)}
                />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Nikt nie jest dziś zweryfikowany. Zamknij screening w kroku
            „Screening”, żeby kandydat trafił tutaj.
          </p>
        )}

        <RailSection
          label={
            clientLabel ? `Reguły CV klienta · ${clientLabel}` : "Reguły CV klienta"
          }
        >
          {clientId == null ? (
            <p className="text-xs text-muted-foreground">
              Ta rekrutacja nie ma przypiętego klienta — żadna reguła CV nie
              obowiązuje, a nazwa pliku będzie ogólna.
            </p>
          ) : (
            <div className="space-y-1.5">
              {cvRuleQuery.isLoading || cvRuleQuery.isError || !ruleActive ? (
                // Ładowanie, awarię i „klient nie ma zatwierdzonej reguły"
                // opisuje ten sam baner, którego używa generator — jedno zdanie
                // o braku reguł, nie cisza (bramki są fail-closed i same z
                // siebie nie dają żadnego objawu).
                <ClientCvRuleBanner
                  clientId={clientId}
                  rule={cvRuleQuery.data}
                  isLoading={cvRuleQuery.isLoading}
                  isError={cvRuleQuery.isError}
                />
              ) : (
                <>
                  <ReadyItem
                    tone={rule?.cv_language ? "y" : "z"}
                    title={`Język CV: ${rule?.cv_language ? rule.cv_language.toUpperCase() : "bez wymogu"}`}
                    detail={
                      rule?.cv_language
                        ? "wymuszony regułą klienta"
                        : "generator użyje domyślnego"
                    }
                  />
                  <ReadyItem
                    tone={rule?.content_mode_locked ? "y" : "z"}
                    title={`Tryb: ${
                      rule?.content_mode
                        ? (CONTENT_MODE_LABEL[rule.content_mode] ??
                          rule.content_mode)
                        : "do wyboru"
                    }`}
                    detail={
                      rule?.content_mode_locked
                        ? "zablokowany regułą — serwer nadpisze inny wybór"
                        : "rekruter wybiera w generatorze"
                    }
                  />
                  {rule?.requires_rodo_consent_block && (
                    <ReadyItem
                      tone="n"
                      title="Zrzut zgody RODO"
                      detail="wymagany na końcu CV — wgraj go w generatorze"
                      action={
                        <button
                          type="button"
                          onClick={() =>
                            generatorRef.current?.scrollIntoView({
                              block: "start",
                            })
                          }
                          className="text-[11px] font-medium text-primary hover:underline"
                        >
                          Wgraj
                        </button>
                      }
                    />
                  )}
                  {(rule?.filename_preview || rule?.filename_pattern) && (
                    <ReadyItem
                      tone="y"
                      title="Nazwa pliku"
                      detail={rule.filename_preview ?? rule.filename_pattern}
                    />
                  )}
                </>
              )}
              {/* Limit CV idzie z KARTY KLIENTA, nie z reguły CV — brak
                  zatwierdzonej reguły go nie unieważnia. */}
              <ReadyItem
                tone={
                  cvLimit != null && atClient >= cvLimit
                    ? "n"
                    : cvLimit != null
                      ? "y"
                      : "z"
                }
                title={
                  cvLimit != null
                    ? `Limit CV na proces: ${cvLimit}`
                    : "Limit CV na proces: brak w karcie klienta"
                }
                detail={`u klienta jest ${atClient}`}
              />
              {cvLimit != null && atClient >= cvLimit && (
                <p className="inline-flex items-start gap-1 text-[11px] text-warning-muted-foreground">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  Limit CV tego klienta jest wyczerpany — potwierdź z Delivery
                  Leadem przed kolejną wysyłką.
                </p>
              )}
            </div>
          )}
        </RailSection>
      </WorkbenchRail>

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
            <WorkbenchHeader
              title={`CV · ${fullName}`}
              subtitle={[
                "Zweryfikowany",
                formatExpectedRate(selected.item),
                originalQuery.data?.original_cv_language
                  ? `CV źródłowe: ${originalQuery.data.original_cv_language.toUpperCase()}`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
              badges={
                <>
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
                </>
              }
              actions={
                <Link
                  href={`/candidates/${selected.item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
                >
                  <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
                </Link>
              }
              tools={
                <>
                  <ToolPill tone={brandedFinalized ? "ok" : "neutral"}>
                    Brandowane:{" "}
                    {brandedFinalized
                      ? "zfinalizowane"
                      : brandedStatus === "draft"
                        ? "draft"
                        : "brak"}
                  </ToolPill>
                  <ToolPill
                    tone={originalQuery.data?.has_snapshot ? "info" : "warn"}
                    title={
                      originalQuery.data?.original_snapshot_source ?? undefined
                    }
                  >
                    CV źródłowe:{" "}
                    {originalQuery.isLoading
                      ? "…"
                      : (originalQuery.data?.original_cv_filename ??
                        "brak snapshotu")}
                  </ToolPill>
                  {cvLimit != null && (
                    <ToolPill tone={atClient >= cvLimit ? "warn" : "neutral"}>
                      {`Limit CV: ${atClient} z ${cvLimit}`}
                    </ToolPill>
                  )}
                </>
              }
            />

            {/* Generator CV — ten sam komponent co `/cv-generator`, osadzony
                z wypełnionym krokiem 1 (kandydat) i rekrutacją. */}
            <div ref={generatorRef}>
              <WorkbenchCard
                title="Obróbka treści"
                status={
                  rule?.content_mode_locked
                    ? "tryb zablokowany regułą klienta"
                    : undefined
                }
                statusTone="warn"
              >
                <CVGeneratorStandaloneV2
                  embedded
                  prefillCandidateId={selected.item.candidate_id}
                  prefillCandidateName={fullName}
                  prefillJobId={jobId}
                />
              </WorkbenchCard>
            </div>

            {/* Snapshoty tej rekrutacji — te same modale, co na profilu. */}
            <WorkbenchCard title="Snapshoty tej rekrutacji">
              {originalQuery.isLoading ? (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
                </div>
              ) : (
                <ReqRow
                  tone={originalQuery.data?.has_snapshot ? "y" : "w"}
                  label={
                    originalQuery.data?.has_snapshot
                      ? `CV oryginalne${
                          originalQuery.data.original_snapshot_at
                            ? ` · snapshot z ${formatDate(originalQuery.data.original_snapshot_at)}`
                            : ""
                        }`
                      : "Brak CV w momencie zgłoszenia"
                  }
                  tag={
                    <button
                      type="button"
                      className="text-primary hover:underline"
                      onClick={() => setOpenOriginal(true)}
                    >
                      Pokaż
                    </button>
                  }
                />
              )}
              <ReqRow
                tone={brandedFinalized ? "y" : brandedStatus === "draft" ? "w" : "n"}
                label={
                  brandedFinalized
                    ? `Brandowane · zfinalizowane${
                        brandedQuery.data?.finalized_at
                          ? ` ${formatDate(brandedQuery.data.finalized_at)}`
                          : ""
                      }`
                    : brandedStatus === "draft"
                      ? "Brandowane · draft (niesfinalizowane)"
                      : "Brandowane · brak"
                }
                tag={
                  readOnly ? undefined : (
                    <button
                      type="button"
                      className="text-primary hover:underline"
                      onClick={() => setOpenBranded(true)}
                    >
                      {brandedStatus === "none" ? "Stwórz" : "Edytuj"}
                    </button>
                  )
                }
              />
            </WorkbenchCard>
          </>
        )}
      </div>

      {/* ── Dok: wysyłka do klienta ─────────────────────────────────────── */}
      <aside className="lg:col-span-2 xl:sticky xl:top-4 xl:col-span-1 xl:self-start">
        <WorkbenchDock
          name="Wysyłka do klienta"
          who={selected ? fullName : null}
          whoSub={
            selected
              ? `→ CV Wysłane${clientLabel ? ` · ${clientLabel}` : ""}`
              : undefined
          }
          tabs={selected ? dockTabs : undefined}
          activeTab={dockTab}
          onTabChange={(v) => setDockTab(v as DockTab)}
          footer={
            rule?.requires_rodo_consent_block ? (
              <>
                <AlertTriangle className="h-3 w-3 shrink-0" />
                Bez zrzutu zgody RODO generacja dla klienta{" "}
                {clientLabel || "tego klienta"} odmawia (422), zanim naliczy
                kwotę.
              </>
            ) : (
              <>
                <Link2 className="h-3 w-3 shrink-0" />
                Zarządzanie linkami zostaje też w doku „Karta w procesie” na
                tablicy i na profilu kandydata.
              </>
            )
          }
        >
          {!selected ? (
            <p className="text-xs text-muted-foreground">
              Wybierz kandydata z kolejki, żeby przygotować wysyłkę.
            </p>
          ) : dockTab === "links" ? (
            <>
              {linksQuery.isLoading ? (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie
                  linków…
                </div>
              ) : linksQuery.isError ? (
                <QueryStateNotice
                  state={
                    resolveViewState({
                      isLoading: false,
                      isError: true,
                      error: linksQuery.error,
                      isSuccess: false,
                    }) as "forbidden" | "not_found" | "error"
                  }
                  description="Nie udało się wczytać linków tego etapu. Linki nie zniknęły — to nieudane pobranie."
                  onRetry={() => void linksQuery.refetch()}
                />
              ) : (linksQuery.data ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Ten etap nie ma jeszcze żadnego linku dla klienta.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {(linksQuery.data ?? []).map((token) => (
                    <div
                      key={token.revoke_key}
                      className="rounded-lg border border-border bg-muted/20 p-2 text-[11px]"
                    >
                      <div className="flex items-center gap-2">
                        <Badge
                          size="sm"
                          variant={token.revoked ? "neutral" : "success"}
                        >
                          {token.revoked ? "odwołany" : "aktywny"}
                        </Badge>
                        <code className="min-w-0 flex-1 truncate text-muted-foreground">
                          {token.token_preview}
                        </code>
                        <span className="shrink-0 tabular-nums text-muted-foreground">
                          {token.view_count} wyświetleń
                        </span>
                      </div>
                      <div className="mt-1 text-muted-foreground">
                        {[
                          token.created_at
                            ? `utworzony ${formatDate(token.created_at)}`
                            : null,
                          token.created_by_name,
                          token.expires_at
                            ? `wygasa ${formatDate(token.expires_at)}`
                            : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {!readOnly && activeLinks.length > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full justify-start"
                  loading={revokeAllMut.isPending}
                  onClick={() => revokeAllMut.mutate()}
                >
                  <Link2 className="h-3.5 w-3.5" /> Odwołaj wcześniejsze linki (
                  {activeLinks.length})
                </Button>
              )}
            </>
          ) : (
            <>
              <ChromeBanner
                tone={moveBlocked ? "warn" : "ok"}
                icon={
                  moveBlocked ? (
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  ) : (
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  )
                }
              >
                {moveBlocked ??
                  `Bramka: brak przeciwwskazań · weto HM: brak${
                    cvLimit != null ? ` · limit CV: ${atClient} z ${cvLimit}` : ""
                  }`}
              </ChromeBanner>

              {canWriteClientRate ? (
                <DockSection title="Stawka do klienta" right="z ClientRateModal">
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
                        className="h-9 w-full rounded-md border border-border bg-card px-3 text-xs focus:outline-hidden focus:ring-2 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
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
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-muted-foreground">
                      Marża (podgląd)
                    </span>
                    <span
                      title={margin.reason ?? undefined}
                      className={cn(
                        "font-medium tabular-nums",
                        margin.value != null && margin.value > 0
                          ? "text-success-muted-foreground"
                          : margin.value != null
                            ? "text-destructive-muted-foreground"
                            : "text-muted-foreground",
                      )}
                    >
                      {margin.label}
                    </span>
                  </div>
                  <p className="text-[10.5px] text-muted-foreground">
                    „Pomiń” zostaje — puste pole wysyła bez stawki, można ją
                    uzupełnić później na karcie rekrutacji w profilu. Stawka
                    zapisuje się PO ruchu, na nowym etapie — jak na tablicy.
                  </p>
                </DockSection>
              ) : (
                <p className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
                  Stawkę do klienta zapisuje admin (uprawnienie finansowe) —
                  wysyłka idzie bez stawki, uzupełni ją później z profilu
                  kandydata.
                </p>
              )}

              <DockSection title="Link dla klienta">
                <KvList
                  rows={[
                    {
                      k: "Dokument",
                      v: brandedFinalized ? (
                        "Brandowane (zfinalizowane)"
                      ) : (
                        <span className="text-warning-muted-foreground">
                          brak — sfinalizuj brandowane
                        </span>
                      ),
                    },
                    {
                      k: "Ważność",
                      v: brandedFinalized ? (
                        <Select
                          value={String(shareDays)}
                          onValueChange={(v) => setShareDays(Number(v))}
                          disabled={readOnly || !createLink}
                        >
                          <SelectTrigger
                            id="cv-share-days"
                            className="h-8 w-full"
                            aria-label="Ważność linku"
                          >
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
                      ) : (
                        "14 dni (max 90)"
                      ),
                    },
                    {
                      k: "Limit wyświetleń",
                      v: "— (ustawia się przy linku interaktywnego CV)",
                    },
                    {
                      k: "Karta Championa",
                      v:
                        readOnly || stageId == null ? (
                          "—"
                        ) : (
                          <button
                            type="button"
                            className="text-primary hover:underline disabled:opacity-60"
                            disabled={championLinkMut.isPending}
                            onClick={() => championLinkMut.mutate()}
                          >
                            Utwórz link (30 dni)
                          </button>
                        ),
                    },
                  ]}
                />
                <label className="flex cursor-pointer items-start gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={createLink}
                    disabled={readOnly || !brandedFinalized}
                    onChange={(e) => setCreateLink(e.target.checked)}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-border accent-primary disabled:cursor-not-allowed"
                  />
                  <span className={cn(!brandedFinalized && "text-muted-foreground")}>
                    Utwórz link do brandowanego CV
                  </span>
                </label>
                {linkBlockedReason && (
                  <p className="text-[11px] text-muted-foreground">
                    {linkBlockedReason}
                  </p>
                )}
              </DockSection>

              {!readOnly && (
                <>
                  <DockActions>
                    <Button
                      className="col-span-2 w-full justify-start"
                      size="sm"
                      disabled={Boolean(moveBlocked) || sendMut.isPending}
                      loading={sendMut.isPending}
                      title={moveBlocked ?? undefined}
                      onClick={() => sendMut.mutate()}
                    >
                      <Send className="h-3.5 w-3.5" />
                      {willCreateLink ? "Utwórz link i oznacz „CV Wysłane”" : "Oznacz „CV Wysłane” bez tworzenia linku"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="w-full justify-start"
                      disabled={!lastShareSuffix}
                      title={
                        lastShareSuffix
                          ? "Kopiuje pełny adres linku do schowka"
                          : "Link powstaje po kliknięciu „Utwórz link” — wtedy da się go skopiować"
                      }
                      onClick={() => {
                        if (!lastShareSuffix || typeof window === "undefined")
                          return;
                        void navigator.clipboard
                          ?.writeText(
                            `${window.location.origin}${lastShareSuffix}`,
                          )
                          .then(() => showSuccess("Link skopiowany."))
                          .catch(() =>
                            showError("Nie udało się skopiować linku."),
                          );
                      }}
                    >
                      <Link2 className="h-3.5 w-3.5" /> Kopiuj link
                    </Button>
                    <a
                      href={mailtoHref}
                      className="inline-flex h-8 items-center justify-start gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
                      title="Otwiera klienta pocztowego z gotową treścią — adresata wpisujesz sam"
                    >
                      <Mail className="h-3.5 w-3.5" /> Mail do klienta
                    </a>
                  </DockActions>
                  <p className="text-[11px] text-muted-foreground">
                    Ta akcja zmienia status w pipeline. Wiadomość wyślij osobno,
                    korzystając z przygotowanego linku. Przycisk „Mail do klienta”
                    otwiera szkic wiadomości w Twoim programie pocztowym.
                  </p>
                </>
              )}
            </>
          )}
        </WorkbenchDock>
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
