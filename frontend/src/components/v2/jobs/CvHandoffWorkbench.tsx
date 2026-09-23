"use client";

/**
 * CvHandoffWorkbench — sekcja „CV do klienta” panelu osoby (rekrutacja v3).
 *
 * Od generatora CV v3 przygotowanie CV żyje w karcie `CvToClientCard`
 * (gotowe / generuje się / brak / stary szablon), a ten warsztat dokłada do
 * niej WYSYŁKĘ: stawkę do klienta, „Oznacz CV Wysłane”, link dla klienta
 * (gdy włączony) i reguły CV klienta. Osadzony generator, wybór wersji
 * „Zastąp szkic i otwórz edytor” oraz pełnoekranowy układ z kolejką
 * zweryfikowanych zniknęły — kolejka nie była nigdzie montowana od wersji 3,
 * a generator otwiera się teraz w oknie z karty.
 *
 * Karta niczego nie blokuje („Kanban bez bramek”): brak CV czy zgody RODO nie
 * wyłącza „Oznacz CV Wysłane”. Ruch idzie przez `pipeline/move` ze stawką
 * (Pipeline v4), link — na etap SPRZED ruchu, gdzie leży CV.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  HelpCircle,
  Link2,
  Loader2,
  Mail,
  Send,
  Settings2,
  UserX,
} from "lucide-react";

import {
  candidateStageCvApi,
  extractErrorMsg,
  pipelineApi,
  screeningApi,
  type CVBrandedState,
  type CVShareTokenListItem,
  type RateUnit,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
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
import { useCentralPolicy } from "@/components/cv-rules/CentralPolicyView";
import { CV_CLIENT_LINKS_UI_ENABLED } from "@/lib/cv-generator";
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
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import {
  CvHandoffError,
  describeCvHandoffFailure,
  describeCvHandoffSuccess,
  runCvHandoff,
  type CvHandoffPlan,
} from "@/lib/cv-handoff";
import {
  PIPELINE_VERSION_CONFLICT_MESSAGE,
  expectedStateVersionOf,
  invalidateAfterPipelineVersionConflict,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
import { copyTextToClipboard } from "@/lib/clipboard";
import { OneTimeLinkField } from "@/components/v2/jobs/OneTimeLinkField";
import {
  ChromeBanner,
  DockActions,
  DockSection,
  KvList,
  ReadyItem,
  type DockTabItem,
} from "@/components/v2/jobs/workbench-chrome";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { useEligibilityWarning } from "@/components/v2/jobs/useEligibilityWarning";
import { TabbedNav } from "@/components/ds";
import { CvToClientCard } from "@/components/v2/recruitment/CvToClientCard";
import type { WorkbenchPanelProps } from "@/components/v2/recruitment/types";

/**
 * CV i wysyłka JEDNEJ osoby (`focusCandidateId`) w kolumnie panelu. `layout`
 * zostaje w typie dla zgodności z innymi warsztatami — układu „full” (kolejka
 * z szyną) już nie ma.
 */
export interface CvHandoffWorkbenchProps extends WorkbenchPanelProps {
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
  /**
   * `JobResponse.can_write_client_rate` — liczone przez serwer tą samą funkcją
   * co `PATCH …/client-rate` (admin, DL, TAC, TCM, HoR, Finanse albo
   * właściciel/twórca rekrutacji). Brak pola = pole stawki ukryte.
   */
  canWriteClientRate?: boolean;
  /** Nordea (DZ → Cpro) — tam „CV wysłane" wysyła wytypowana osoba bez
   *  stawki; poza Nordeą wysyła wyłącznie DL ze stawką (Pipeline v4). */
  cproEnabled?: boolean;
  /**
   * Aktualny budżet PLN/h rekrutacji (`effective_budget_hourly`) — odznaka
   * „ponad budżet" (informacja, nie blokada). `null` = brak budżetu.
   */
  budgetHourly?: number | null;
}

const SHARE_DAYS_OPTIONS = [7, 14, 30, 60, 90];

/**
 * Wynik przekazania w panelu „Utworzone linki do CV". `suffix === null` znaczy
 * „ruch się wykonał, link NIE powstał" — wiersz niesie wtedy wszystko, czego
 * potrzeba do ponowienia (etap sprzed ruchu i ważność).
 */
interface HandoffLinkResult {
  stageId: number;
  candidateName: string;
  jobTitle: string;
  suffix: string | null;
  expiresInDays: number;
}

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
  canWriteClientRate = false,
  cproEnabled = false,
  budgetHourly = null,
  focusCandidateId = null,
  panelFallback,
}: CvHandoffWorkbenchProps) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();

  const queue = useMemo(() => selectVerifiedQueue(columns), [columns]);
  const cvSentCol = useMemo(
    () => findStageColumn(columns, CV_SENT_STAGE),
    [columns],
  );
  const atClient = useMemo(() => countAtClient(columns), [columns]);

  // Wybór jest STEROWANY z zewnątrz (`focusCandidateId`) — panel pokazuje
  // jedną osobę.
  const activeStageId =
    queue.find((e) => e.item.candidate_id === focusCandidateId)?.item.id ?? null;
  const selected = queue.find((e) => e.item.id === activeStageId) ?? null;
  const stageId = selected?.item.id ?? null;
  const fullName = selected ? itemFullName(selected.item) : "";
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;

  // `canWriteClientRate` przychodzi z odpowiedzi `GET /api/jobs/{id}` — ta
  // sama reguła co zapis `PATCH …/client-rate` i modal na tablicy. Do 09.2026
  // warsztat zgadywał ją po roli admina, a tablica pytała każdego.
  // `/settings/cv-rules` jest bramkowane w middleware (admin / DL, sekcja
  // Delivery write) — link dla innych ról prowadziłby wprost w 403.
  const canManageCvRules = useCapability("cv_rule.manage");

  // ── Reguły klienta (te same, które generator pokazuje po wyborze klienta) ─
  const cvRuleQuery = useClientCvRule(clientId);
  const centralPolicy = useCentralPolicy(clientId, stageId);
  const centrallyManaged = !!centralPolicy.data?.managed;
  const rule = cvRuleQuery.data ?? null;
  const ruleActive = Boolean(rule?.is_active);
  const playbookQuery = useClientPlaybook(clientId);
  const cvLimit = playbookQuery.data?.cv_limit_per_process ?? null;
  const clientLabel =
    rule?.client_name?.trim() ||
    playbookQuery.data?.client_name?.trim() ||
    (clientId != null ? `klient #${clientId}` : "");

  // ── CV etapu — ten sam klucz co karta „CV do klienta” i edytor ──────────
  // Warsztat potrzebuje stanu tylko do linku dla klienta (link wymaga
  // zatwierdzonej wersji). Samo CV — podgląd, edycja, generacja — żyje w karcie.
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
  const [handoffResults, setHandoffResults] = useState<HandoffLinkResult[]>([]);
  const resultsRef = useRef(handoffResults);
  const lastShareSuffix =
    [...handoffResults]
      .reverse()
      .find((r) => r.stageId === activeStageId && r.suffix != null)?.suffix ?? null;
  const rememberLink = (result: HandoffLinkResult) => {
    resultsRef.current = [...resultsRef.current, result];
    setHandoffResults(resultsRef.current);
  };
  useEffect(() => {
    setClientRate("");
    setClientRateUnit("monthly");
    setCreateLink(
      !resultsRef.current.some((r) => r.stageId === activeStageId && r.suffix != null),
    );
    setDockTab("send");
  }, [activeStageId]);

  // Link, który padł PO udanym ruchu: kandydat stoi już na „CV Wysłane", a CV
  // brandowane zostało na etapie sprzed ruchu — profil i dok celują w etap
  // najnowszy, więc bez tego przycisku nie byłoby jak utworzyć linku do tego
  // dokumentu. Ponowienie idzie na ZAPAMIĘTANY identyfikator etapu.
  const retryLinkMut = useMutation({
    mutationFn: (entry: HandoffLinkResult) =>
      candidateStageCvApi.share.create(entry.stageId, entry.expiresInDays),
    onSuccess: (res, entry) => {
      const suffix = res.data?.share_url_suffix ?? null;
      if (!suffix) {
        showError("Serwer nie zwrócił adresu linku — sprawdź zakładkę „Linki i historia”.");
        return;
      }
      resultsRef.current = resultsRef.current.map((r) =>
        r === entry ? { ...r, suffix } : r,
      );
      setHandoffResults(resultsRef.current);
      showSuccess("Link dla klienta utworzony.");
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się utworzyć linku dla klienta."),
  });

  const numericClientRate = Number.parseFloat(clientRate.replace(",", "."));
  const clientRateValid =
    Number.isFinite(numericClientRate) && numericClientRate > 0;
  // Link tylko przy zatwierdzonym CV do klienta — backend odbija 409, więc
  // powód jest widoczny, a nie niespodzianką po kliknięciu.
  const linkBlockedReason = brandedFinalized
    ? null
    : "Link dla klienta wymaga zatwierdzonego CV do klienta — zapisz je w edytorze albo oznacz etap bez tworzenia linku.";
  // Linki dla klienta wyłączone (CV_CLIENT_LINKS_UI_ENABLED): akcja tylko
  // przesuwa kandydata na „CV Wysłane" i zapisuje stawkę — bez linku.
  const willCreateLink = CV_CLIENT_LINKS_UI_ENABLED && createLink && brandedFinalized;

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

  // Link do karty Championa niesie sekret zwracany JEDEN raz — adres zostaje
  // na ekranie (`OneTimeLinkField`), a toast „skopiowany" pada wyłącznie po
  // UDANYM zapisie do schowka. Do 09.2026 toast szedł zawsze, a adres nigdzie
  // się nie pokazywał: nieudany zapis zostawiał żywy, 30-dniowy link, którego
  // nikt nie znał.
  const [championLink, setChampionLink] = useState<{
    stageId: number;
    url: string;
  } | null>(null);
  const championLinkMut = useMutation({
    mutationFn: (forStageId: number) => screeningApi.createShareToken(forStageId, 30),
    onSuccess: async (res, forStageId) => {
      const suffix = res?.data?.share_url_suffix;
      if (!suffix) {
        showError("Serwer nie zwrócił adresu linku do karty Championa.");
        return;
      }
      const url = `${window.location.origin}${suffix}`;
      setChampionLink({ stageId: forStageId, url });
      if (await copyTextToClipboard(url)) {
        showSuccess("Link do karty Championa skopiowany (ważny 30 dni).");
      } else {
        showError(
          "Link do karty Championa utworzony (ważny 30 dni), ale nie udało się go skopiować — skopiuj go z pola w doku.",
        );
      }
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się utworzyć linku."),
  });

  const moveBlocked = selected
    ? (moveBlockedReason({
        item: selected.item,
        readOnly,
        targetStage: CV_SENT_STAGE,
      }) ??
      (!cvSentCol
        ? "Szablon tej rekrutacji nie ma kolumny „CV Wysłane”."
        : !cproEnabled && !canWriteClientRate
          ? "Do klienta wysyła Delivery Lead — osoba czeka w jego przeglądzie."
        : CV_CLIENT_LINKS_UI_ENABLED && brandedQuery.isLoading
          ? // Bez tego w oknie ładowania `brandedStatus` = "none", więc klik
            // wysłałby BEZ linku i zaraportował to jako świadomą decyzję.
            "Sprawdzam stan CV brandowanego…"
          : null))
    : "Wybierz kandydata z kolejki.";

  // 17.09.2026: weto HM / czarna lista / NDA na „CV Wysłane" to ostrzeżenie
  // serwera — okno „Przenieś mimo to" zamiast toastu błędu.
  const eligibilityWarning = useEligibilityWarning();
  const sendMut = useMutation({
    mutationFn: async (acknowledgeEligibility: boolean) => {
      if (!selected || !cvSentCol || stageId == null) {
        throw new Error("Brak etapu docelowego.");
      }
      // Etap SPRZED ruchu: na nim leży sfinalizowane CV brandowane, więc link
      // tworzony po ruchu celuje właśnie tutaj, a nie w świeży „CV Wysłane".
      const sourceStageId = stageId;
      const expiresInDays = shareDays;
      const plan: CvHandoffPlan = {
        clientRate: canWriteClientRate && clientRateValid
          ? {
              value: numericClientRate,
              unit: clientRateUnit,
              currency: "PLN",
            }
          : null,
        shareLink: willCreateLink ? { expiresInDays } : null,
      };
      return runCvHandoff(plan, {
        createShareLink: async ({ expiresInDays: days }) => {
          const base = {
            stageId: sourceStageId,
            candidateName: fullName,
            jobTitle: jobLabel,
            expiresInDays: days,
          };
          try {
            const res = await candidateStageCvApi.share.create(sourceStageId, days);
            const suffix = res.data?.share_url_suffix ?? null;
            if (!suffix) throw new Error("Serwer nie zwrócił adresu linku.");
            // Sekret wraca RAZ — zapamiętany natychmiast, zanim cokolwiek
            // odświeży kolejkę i kandydat z niej zniknie.
            rememberLink({ ...base, suffix });
            return { shareUrlSuffix: suffix };
          } catch (e) {
            // Ruch już się wykonał — zostaw w panelu wiersz z ponowieniem,
            // bo nigdzie indziej nie da się już utworzyć linku do tego etapu.
            rememberLink({ ...base, suffix: null });
            throw e;
          }
        },
        move: async (rate) => {
          await pipelineApi.move({
            candidate_id: selected.item.candidate_id,
            job_id: jobId,
            stage: CV_SENT_STAGE,
            stage_def_id: cvSentCol.stage_def_id ?? undefined,
            expected_state_version: expectedStateVersionOf(selected.item),
            acknowledge_eligibility: acknowledgeEligibility ? true : undefined,
            client_rate_value: rate?.value,
            client_rate_unit: rate?.unit,
            client_rate_currency: rate?.currency,
          });
        },
      });
    },
    onSuccess: (result) => {
      // Link (jeśli powstał) jest już zapamiętany w panelu wyników — wiersz
      // przeżywa odświeżenie kolejki, w którym kandydat z niej znika.
      const summary = describeCvHandoffSuccess(result, extractErrorMsg);
      // Link albo stawka padły PO ruchu (jak na tablicy): ruch jest faktem, ale
      // rekruter musi wiedzieć, czego brakuje — stąd ton błędu, nie sukcesu.
      if (result.failedAfterMove.length > 0) showError(summary);
      else showSuccess(summary);
      onMoved();
    },
    onError: (e, acknowledged) => {
      if (
        !acknowledged &&
        e instanceof CvHandoffError &&
        e.step === "move" &&
        eligibilityWarning.intercept(e.reason, () => sendMut.mutate(true))
      ) {
        // Ruch nie przeszedł (409 przed zapisem) — link i stawka nie powstały.
        return;
      }
      // Ruch idzie pierwszy, więc przy tej porażce nie powstał ani link dla
      // klienta, ani stawka. Sam ruch: odmowa serwera (4xx) = nic się nie
      // zmieniło; brak odpowiedzi / 5xx = nie wiadomo (ruch mógł się zapisać),
      // więc komunikat każe odświeżyć kartę przed ponowieniem.
      if (
        e instanceof CvHandoffError &&
        e.step === "move" &&
        isPipelineVersionConflict(e.reason)
      ) {
        // F05: odmowa ruchu (4xx) — link i stawka nie powstały; bez
        // ponowienia, kolejka pokaże etap zapisany przez kolegę.
        showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
        invalidateAfterPipelineVersionConflict(
          queryClient,
          jobId,
          selected?.item.candidate_id,
        );
        onMoved();
        return;
      }
      if (e instanceof CvHandoffError) {
        showError(describeCvHandoffFailure(e, extractErrorMsg(e.reason)));
        return;
      }
      showError(extractErrorMsg(e) || "Nie udało się przygotować przekazania CV.");
    },
  });

  const viewState = resolveViewState({ isLoading, isError, error, isSuccess });

  if (viewState === "loading") {
    return <Skeleton className="h-64 w-full rounded-xl" />;
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

  // ── Fragmenty panelu ───────────────────────────────────────────────────
  const resultsSection = (
    <>
      {handoffResults.length > 0 && (
        <section className="space-y-3 rounded-xl border border-border bg-card p-4 " aria-label="Utworzone linki do CV">
          <h3 className="text-sm font-semibold">Utworzone linki do CV</h3>
          <p className="text-xs text-muted-foreground">Linki pozostają tutaj po zmianie etapu i wyborze kolejnego kandydata. Ten ekran nie wysyła wiadomości do klienta. Skopiuj link przed opuszczeniem tej strony.</p>
          {handoffResults.map((result, index) =>
            result.suffix == null ? (
              <div key={index} className="space-y-2 rounded-lg border border-warning/30 bg-warning-muted p-3">
                <p className="text-sm font-medium">{result.candidateName} · {result.jobTitle}</p>
                <p className="text-xs text-warning-muted-foreground">
                  Kandydat jest już na „CV Wysłane”, ale link dla klienta nie powstał. CV brandowane zostało na etapie sprzed ruchu — utwórz link tutaj.
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  loading={retryLinkMut.isPending && retryLinkMut.variables === result}
                  disabled={retryLinkMut.isPending}
                  onClick={() => retryLinkMut.mutate(result)}
                >
                  <Link2 className="h-3.5 w-3.5" /> Utwórz link ponownie: {result.candidateName}
                </Button>
              </div>
            ) : (
              <div key={index} className="space-y-2 rounded-lg border border-border p-3">
                <p className="text-sm font-medium">{result.candidateName} · {result.jobTitle}</p>
                <code className="block break-all text-xs">{typeof window !== "undefined" ? window.location.origin : ""}{result.suffix}</code>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={async () => {
                    if (await copyTextToClipboard(`${window.location.origin}${result.suffix}`)) {
                      showSuccess("Link skopiowany.");
                    } else {
                      showError("Nie udało się skopiować linku. Zaznacz widoczny adres ręcznie.");
                    }
                  }}>Kopiuj link: {result.candidateName}</Button>
                  <a className="inline-flex items-center rounded-lg border border-border px-3 text-xs"
                    href={`mailto:?subject=${encodeURIComponent(`CV kandydata: ${result.candidateName} — ${result.jobTitle}`)}&body=${encodeURIComponent(`Dzień dobry,\n\nCV kandydata ${result.candidateName}: ${typeof window !== "undefined" ? window.location.origin : ""}${result.suffix}\n`)}`}>
                    Przygotuj wiadomość
                  </a>
                </div>
              </div>
            ),
          )}
        </section>
      )}
    </>
  );
  const rulesBody = (
    <>
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
                      centrallyManaged ? "domyślnie „Pod rekrutację”" : rule?.content_mode
                        ? (CONTENT_MODE_LABEL[rule.content_mode] ??
                          rule.content_mode)
                        : "do wyboru"
                    }`}
                    detail={
                      centrallyManaged ? "można zmienić w generatorze; bez Profilu Championa powstanie Redakcja" : rule?.content_mode_locked
                        ? "zablokowany regułą — serwer nadpisze inny wybór"
                        : "rekruter wybiera w generatorze"
                    }
                  />
                  {rule?.requires_rodo_consent_block && (
                    <ReadyItem
                      tone="n"
                      title="Zrzut zgody RODO"
                      detail="wymagany do pobrania CV — dołączysz go w karcie „CV do klienta”"
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
    </>
  );
  const headBadges = selected ? (
                <>
                  {isOverHourlyBudget(selected.item, budgetHourly) && (
                    <Badge
                      variant="warning"
                      size="sm"
                      title="Stawka kandydata przekracza budżet rekrutacji — informacja, nic nie blokuje."
                    >
                      <HelpCircle className="h-2.5 w-2.5" /> Ponad budżet
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
  ) : null;
  const dockFooter =
            rule?.requires_rodo_consent_block ? (
              <>
                <AlertTriangle className="h-3 w-3 shrink-0" />
                {`Bez zrzutu zgody RODO CV dla klienta ${clientLabel || "tego klienta"} nie da się pobrać — dołącz go w karcie „CV do klienta”. Wysyłki to nie blokuje.`}
              </>
            ) : CV_CLIENT_LINKS_UI_ENABLED ? (
              <>
                <Link2 className="h-3 w-3 shrink-0" />
                Zarządzanie linkami zostaje też w doku „Karta w procesie” na
                tablicy i na profilu kandydata.
              </>
            ) : null;
  const dockBody = !selected ? (
            <p className="text-xs text-muted-foreground">
              Wybierz kandydata z kolejki, żeby przygotować wysyłkę.
            </p>
          ) : CV_CLIENT_LINKS_UI_ENABLED && dockTab === "links" ? (
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
                <DockSection title="Stawka do klienta">
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
                    <span className="text-muted-foreground">Stawka kandydata</span>
                    <span className="font-medium tabular-nums text-foreground">
                      {selected ? (formatExpectedRate(selected.item) ?? "nie podano") : "—"}
                    </span>
                  </div>
                  <p className="text-[10.5px] text-muted-foreground">
                    {cproEnabled
                      ? "Puste pole wysyła bez stawki — DL uzupełni ją później na karcie rekrutacji."
                      : "Bez stawki do klienta nie wyślesz — trafi do umowy i zamówienia."}
                  </p>
                </DockSection>
              ) : (
                <p className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
                  {cproEnabled
                    ? "Stawkę do klienta ustala Delivery Lead — wysyłka idzie bez stawki, DL ją uzupełni."
                    : "Do klienta wysyła Delivery Lead i to on ustala stawkę — osoba czeka w jego przeglądzie."}
                </p>
              )}

              {CV_CLIENT_LINKS_UI_ENABLED && (
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
                            onClick={() => championLinkMut.mutate(stageId)}
                          >
                            Utwórz link (30 dni)
                          </button>
                        ),
                    },
                  ]}
                />
                {championLink && championLink.stageId === stageId && (
                  <OneTimeLinkField
                    url={championLink.url}
                    label="Link do karty Championa"
                    note="Ważny 30 dni. Adres pokazujemy tylko teraz — serwer nie przechowuje sekretu, więc skopiuj go przed opuszczeniem strony."
                  />
                )}
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
              )}

              {!readOnly && (
                <>
                  <DockActions>
                    <Button
                      className="col-span-2 w-full justify-start"
                      size="sm"
                      disabled={Boolean(moveBlocked) || sendMut.isPending}
                      loading={sendMut.isPending}
                      title={moveBlocked ?? undefined}
                      onClick={() => sendMut.mutate(false)}
                    >
                      <Send className="h-3.5 w-3.5" />
                      {!CV_CLIENT_LINKS_UI_ENABLED
                        ? "Oznacz „CV Wysłane”"
                        : willCreateLink ? "Utwórz link i oznacz „CV Wysłane”" : "Oznacz „CV Wysłane” bez tworzenia linku"}
                    </Button>
                    {CV_CLIENT_LINKS_UI_ENABLED && (
                    <>
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
                    </>
                    )}
                  </DockActions>
                  <p className="text-[11px] text-muted-foreground">
                    {CV_CLIENT_LINKS_UI_ENABLED
                      ? "Ta akcja zmienia status w pipeline. Wiadomość wyślij osobno, korzystając z przygotowanego linku. Przycisk „Mail do klienta” otwiera szkic wiadomości w Twoim programie pocztowym."
                      : "Ta akcja zmienia status w pipeline (i zapisuje stawkę do klienta, jeśli ją podano). CV wysyłasz klientowi poza NEXUSem."}
                  </p>
                </>
              )}
            </>
          );
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {eligibilityWarning.dialog}
      {/* Link jednorazowy przeżywa ruch: po „CV Wysłane” osoba wypada
          z kolejki tego warsztatu, a adres musi zostać na ekranie. */}
      {resultsSection}
      {!selected && panelFallback != null ? (
        panelFallback
      ) : !selected ? (
        <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
          Przekazanie CV klientowi jest dostępne na etapie „Zweryfikowany”.
          Ta osoba jest dziś na innym etapie tej rekrutacji.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            {headBadges}
            {cvLimit != null && (
              <Badge size="sm" variant={atClient >= cvLimit ? "warning" : "neutral"}>
                {`Limit CV: ${atClient} z ${cvLimit}`}
              </Badge>
            )}
            <Link
              href={`/candidates/${selected.item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
              className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="h-3 w-3" /> Pełny profil
            </Link>
          </div>

          <CvToClientCard
            stageId={selected.item.id}
            candidateId={selected.item.candidate_id}
            candidateName={fullName}
            jobId={jobId}
            jobTitle={jobTitle}
            readOnly={readOnly}
          />

          <section
            aria-label="Wysyłka do klienta"
            className="space-y-3 rounded-xl border border-border bg-card p-3"
          >
            {CV_CLIENT_LINKS_UI_ENABLED && (
              <TabbedNav
                ariaLabel="Zakładki: Wysyłka do klienta"
                value={dockTab}
                onValueChange={(v) => setDockTab(v as DockTab)}
                tabs={dockTabs}
                overflow="scroll"
              />
            )}
            {dockBody}
            {dockFooter ? (
              <p className="flex items-start gap-1.5 border-t border-border pt-2 text-[11px] text-muted-foreground">
                {dockFooter}
              </p>
            ) : null}
          </section>

          <details className="rounded-xl border border-border bg-card px-3 py-2 text-xs">
            <summary className="cursor-pointer font-medium text-foreground">
              {clientLabel
                ? `Reguły CV klienta · ${clientLabel}`
                : "Reguły CV klienta"}
            </summary>
            <div className="mt-2 space-y-2">
              {rulesBody}
              {canManageCvRules && clientId != null && (
                <Link
                  href={`/settings/cv-rules?client=${clientId}`}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
                >
                  <Settings2 className="h-3.5 w-3.5" /> {centrallyManaged ? "Centralne reguły CV →" : "Reguły CV (DL) →"}
                </Link>
              )}
            </div>
          </details>
        </>
      )}
    </div>
  );
}
