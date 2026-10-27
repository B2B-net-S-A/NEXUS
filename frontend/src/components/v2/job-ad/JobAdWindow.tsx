"use client";

/**
 * Okno „Ogłoszenie” (12.10.2026, od 21.10.2026 także strona kariery) — jedna
 * treść rekrutacji: strona kariery jednym kliknięciem oraz dwa formaty do
 * wklejenia, pola formularza Pracuj.pl i opis JustJoin.IT. Rekruter układa
 * ją jednym kliknięciem z Profilu Championa, poprawia i publikuje.
 *
 * Do schowka idą WYŁĄCZNIE teksty policzone przez serwer dla zapisanego
 * stanu (`rendered`), po kontroli: znalezisko blokujące (nazwa klienta,
 * kwota, kontakt, nazwisko) wyłącza kopiowanie w całym oknie.
 *
 * Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenie-na-portale-kopiuj-wklej.md`.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, RefreshCcw } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  advisoryFindings,
  blockingFindings,
  isAdChangedError,
  jobAdApi,
  jobAdQueryKey,
  type AdContent,
  type AdFinding,
  type AdLang,
  type AdTechItem,
  type JobAdState,
} from "@/lib/api/jobAd";
import { copyHtmlToClipboard, copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

import { AdChannels, type AdFocusChannel } from "./AdChannels";
import { AdFactsRail, TERM_KEYS, type AdTerms } from "./AdFactsRail";
import { JOBS_LIST_QUERY_ROOT } from "./AdPublications";
import { JustJoinTab } from "./JustJoinTab";
import { PracujTab } from "./PracujTab";
import {
  withDraft,
  withEdited,
  withoutExcerpt,
  type AdDrafts,
  type AdEditKey,
} from "./job-ad-edit";

export type JobAdTab = "pracuj" | "jjit";

/** Wywołania okna — harness `/preview/job-ad` podaje je z pamięci. */
export type JobAdWindowApi = Pick<
  typeof jobAdApi,
  "get" | "generate" | "save" | "markPublished" | "markRemoved" | "publishCareer"
>;

export interface JobAdWindowProps {
  jobId: number;
  jobTitle: string;
  /** Zamknięta rekrutacja z wiszącym ogłoszeniem = przypomnienie o zdjęciu. */
  jobClosed?: boolean;
  open: boolean;
  onClose: () => void;
  api?: JobAdWindowApi;
  initialTab?: JobAdTab;
  /** Wejście z maila przypomnienia: kanał z krokami, zakładka portalu. */
  focusChannel?: AdFocusChannel | null;
  /** Z maila: okno „Nie publikujemy” od razu. */
  openSkip?: boolean;
  /** Z maila: pytanie „Przypomnieć rekruterowi?” od razu. */
  askRemind?: boolean;
  /** Z maila: mail do opiekuna Pracuj.pl od razu (`&wyslij=opiekun`). */
  openSend?: boolean;
}

const LANG_OPTIONS: ReadonlyArray<{ value: AdLang; label: string }> = [
  { value: "pl", label: "PL" },
  { value: "en", label: "EN" },
];

/** Pola spoza zakładki Pracuj.pl: wstęp i technologie żyją w JustJoin.IT. */
const JJIT_ONLY_FIELDS = new Set(["lead", "tech"]);

function checksSummary(findings: AdFinding[]): string {
  const blocking = blockingFindings(findings).length;
  const advisory = advisoryFindings(findings).length;
  if (!blocking && !advisory) return "Kontrola: bez uwag";
  const parts = [];
  if (blocking) parts.push(`${blocking} do usunięcia`);
  if (advisory) parts.push(`${advisory} do poprawy`);
  return `Kontrola: ${parts.join(", ")}`;
}

export function JobAdWindow({
  jobId,
  jobTitle,
  jobClosed = false,
  open,
  onClose,
  api = jobAdApi,
  initialTab = "pracuj",
  focusChannel = null,
  openSkip = false,
  askRemind = false,
  openSend = false,
}: JobAdWindowProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [tab, setTab] = useState<JobAdTab>(focusChannel === "jjit" ? "jjit" : initialTab);
  const [firstLang, setFirstLang] = useState<AdLang>("pl");
  const [copied, setCopied] = useState<ReadonlySet<string>>(new Set());
  const [careerCopied, setCareerCopied] = useState(false);
  // Niezapisane teksty pól (obie zakładki i warunki z lewej kolumny).
  const [drafts, setDrafts] = useState<AdDrafts>({});
  const bodyRef = useRef<HTMLDivElement | null>(null);

  const queryKey = jobAdQueryKey(jobId);
  const query = useQuery({
    queryKey,
    queryFn: () => api.get(jobId),
    enabled: open,
  });

  // Wersja, na której opierają się otwarte poprawki. Zapytanie odświeża się
  // w tle (powrót do karty), więc wersja czytana z cache w chwili zapisu
  // byłaby już cudzą: serwer przyjąłby stary tekst jako poprawkę do nowej
  // treści. Dopóki coś jest w edycji, wersja bazowa stoi w miejscu.
  const baseVersion = useRef<string | null>(null);
  const editing = Object.keys(drafts).length > 0;
  const loadedVersion = query.data?.ad?.updated_at ?? null;
  useEffect(() => {
    if (!editing) baseVersion.current = loadedVersion;
  }, [editing, loadedVersion]);

  const setDraft = (key: AdEditKey, text: string | null) =>
    setDrafts((prev) => withDraft(prev, key, text));

  const applyState = (state: JobAdState) => {
    queryClient.setQueryData(queryKey, state);
    baseVersion.current = state.ad?.updated_at ?? null;
    // Zmiana treści zapala „do aktualizacji” w kolumnie „Ogłoszenia” listy,
    // a strona kariery — kropkę „Kariera” w nagłówku rekrutacji i na liście.
    if (state.publications.some((item) => !item.removed_at) || state.career.status !== "none") {
      void queryClient.invalidateQueries({ queryKey: [JOBS_LIST_QUERY_ROOT] });
    }
    // Nowa treść = nowe teksty do skopiowania; stare „Skopiowane” już nie obowiązuje.
    setCopied(new Set());
  };

  /** 409: wczytaj to, co zapisał ktoś inny; niezapisany tekst zostaje w polach. */
  const reloadAfterConflict = async () => {
    const fresh = await query.refetch();
    baseVersion.current = fresh.data?.ad?.updated_at ?? null;
  };

  const generate = useMutation({
    mutationFn: (lang: AdLang) => api.generate(jobId, lang, baseVersion.current),
    onSuccess: (state) => {
      applyState(state);
      // Poprawki dotyczyły poprzedniej treści.
      setDrafts({});
      if (state.ad?.source === "ai") showSuccess("Ogłoszenie przygotowane.");
    },
    onError: (err) => {
      if (isAdChangedError(err)) void reloadAfterConflict();
      showError(apiErrorMessage(err, "Nie udało się przygotować ogłoszenia. Spróbuj ponownie."));
    },
  });

  const save = useMutation({
    mutationFn: (input: { content: AdContent; tech: AdTechItem[] }) =>
      api.save(jobId, { ...input, expected_updated_at: baseVersion.current }),
    onSuccess: applyState,
    onError: (err) => {
      if (isAdChangedError(err)) void reloadAfterConflict();
      showError(apiErrorMessage(err, "Nie udało się zapisać poprawki. Spróbuj ponownie."));
    },
  });

  const publishCareer = useMutation({
    mutationFn: () => api.publishCareer(jobId, baseVersion.current),
    onSuccess: (state) => {
      applyState(state);
      void queryClient.invalidateQueries({ queryKey: [JOBS_LIST_QUERY_ROOT] });
      showSuccess("Ogłoszenie wisi na stronie kariery.");
    },
    onError: (err) => {
      if (isAdChangedError(err)) void reloadAfterConflict();
      showError(
        apiErrorMessage(err, "Nie udało się opublikować na stronie kariery. Spróbuj ponownie."),
      );
    },
  });

  const copyCareerLink = async (url: string) => {
    if (await copyTextToClipboard(url)) setCareerCopied(true);
    else showError("Nie udało się skopiować. Zaznacz link i skopiuj go ręcznie.");
  };

  const state = query.data;
  const ad = state?.ad ?? null;
  const rendered = state?.rendered ?? null;
  const findings = state?.findings ?? [];
  const busy = generate.isPending || save.isPending || publishCareer.isPending;

  const saveAd = async (content: AdContent, tech: AdTechItem[]): Promise<boolean> => {
    try {
      await save.mutateAsync({ content, tech });
      return true;
    } catch {
      return false;
    }
  };

  const saveField = async (key: AdEditKey, text: string): Promise<boolean> => {
    if (!ad) return false;
    const saved = await saveAd(withEdited(ad.content, key, text), ad.tech);
    if (saved) setDraft(key, null);
    return saved;
  };

  const saveTerms = async (terms: AdTerms): Promise<boolean> => {
    if (!ad) return false;
    const saved = await saveAd({ ...ad.content, ...terms }, ad.tech);
    if (saved)
      setDrafts((prev) => TERM_KEYS.reduce((next, key) => withDraft(next, key, null), prev));
    return saved;
  };

  const regenerate = async (lang: AdLang) => {
    const confirmed = await askConfirm({
      title: "Przygotować ogłoszenie ponownie?",
      description: `Obecna treść, razem z ręcznymi poprawkami${
        editing ? " i tekstem w otwartych polach," : ""
      } zostanie zastąpiona nową. Jeśli model będzie niedostępny, obecna treść zostanie bez zmian.`,
      confirmLabel: "Przygotuj ponownie",
    });
    if (confirmed) generate.mutate(lang);
  };

  const copy = async (key: string, html: string, text: string) => {
    const ok = html ? await copyHtmlToClipboard(html, text) : await copyTextToClipboard(text);
    if (ok) setCopied((prev) => new Set(prev).add(key));
    else showError("Nie udało się skopiować. Zaznacz tekst i skopiuj go ręcznie.");
  };

  const show = (field: string) => {
    if (JJIT_ONLY_FIELDS.has(field)) setTab("jjit");
    // Zakładka przełącza się w następnym renderze — dopiero wtedy pole istnieje.
    window.setTimeout(() => {
      const target = bodyRef.current?.querySelector<HTMLElement>(`[data-ad-field="${field}"]`);
      target?.scrollIntoView({ block: "center" });
      target?.querySelector<HTMLElement>("input, button")?.focus();
    }, 0);
  };

  const removeExcerpt = (finding: AdFinding) => {
    if (!ad) return;
    const next = withoutExcerpt(ad.content, finding);
    if (next) void saveAd(next, ad.tech);
    else show(finding.field ?? "");
  };

  const copyBlockedReason = !state?.can_copy
    ? "Najpierw usuń z treści fragmenty wskazane w kontroli."
    : save.isPending
      ? "Trwa zapis poprawki."
      : null;
  const blockingCount = blockingFindings(findings).length;
  // Na stronę idzie zapisana treść — otwarta poprawka jeszcze jej nie zmieniła.
  const publishBlockedReason =
    copyBlockedReason ??
    (editing
      ? "Najpierw zapisz albo zamknij otwarte poprawki."
      : generate.isPending
        ? "Trwa przygotowanie treści."
        : null);

  return (
    <>
      <Dialog open={open} onOpenChange={(value) => (value ? undefined : onClose())}>
        <DialogContent
          size="full"
          hideClose
          // `max-h-dvh`, nie `max-h-none` — patrz `CVBrandedEditModal`.
          className="left-0 top-0 h-dvh max-h-dvh w-full max-w-none translate-x-0 translate-y-0 rounded-none border-0 p-0 shadow-none"
          // Escape w polu edycji nie zamyka okna razem z niezapisaną poprawką.
          onEscapeKeyDown={(event) => {
            const target = event.target;
            if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) {
              event.preventDefault();
            }
          }}
          onInteractOutside={(event) => event.preventDefault()}
          data-testid="job-ad-window"
        >
          <DialogTitle className="sr-only">Ogłoszenie</DialogTitle>
          <Tabs
            value={tab}
            onValueChange={(value) => setTab(value as JobAdTab)}
            className="flex min-h-0 flex-1 flex-col"
          >
            <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-card px-4 py-2">
              <div className="flex min-w-0 items-center gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">Ogłoszenie</p>
                  <p className="truncate text-xs text-muted-foreground">{jobTitle}</p>
                </div>
                {ad ? (
                  <TabsList className="border-b-0">
                    <TabsTrigger value="pracuj">Pracuj.pl</TabsTrigger>
                    <TabsTrigger value="jjit">JustJoin.IT</TabsTrigger>
                  </TabsList>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                {ad ? (
                  <>
                    <SegmentedRadio
                      label="Język ogłoszenia"
                      size="sm"
                      value={ad.lang}
                      options={LANG_OPTIONS}
                      disabled={busy}
                      onChange={(lang) => void regenerate(lang)}
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      loading={generate.isPending}
                      disabled={busy}
                      onClick={() => void regenerate(ad.lang)}
                    >
                      <RefreshCcw className="h-3.5 w-3.5" aria-hidden="true" />
                      Przygotuj ponownie
                    </Button>
                  </>
                ) : null}
                <Button type="button" size="sm" variant="ghost" onClick={onClose}>
                  Zamknij
                </Button>
              </div>
            </header>

            <div ref={bodyRef} className="flex min-h-0 flex-1 bg-muted/40">
              {query.isError ? (
                <div className="m-auto flex max-w-md flex-col gap-3 p-6">
                  <Alert
                    variant="error"
                    title="Nie udało się wczytać ogłoszenia"
                    description={apiErrorMessage(query.error, "Spróbuj ponownie za chwilę.")}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="self-start"
                    onClick={() => void query.refetch()}
                  >
                    Spróbuj ponownie
                  </Button>
                </div>
              ) : !query.isSuccess || !state ? (
                <p className="m-auto flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  Wczytuję ogłoszenie…
                </p>
              ) : (
                <>
                  <AdFactsRail
                    facts={state.facts}
                    readiness={state.readiness}
                    content={ad?.content ?? null}
                    drafts={drafts}
                    saving={save.isPending}
                    locked={generate.isPending}
                    onDraftChange={setDraft}
                    onSaveTerms={saveTerms}
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto px-5 py-4">
                    {generate.isPending ? (
                      <p
                        role="status"
                        className="flex items-center gap-2 rounded-md bg-info-muted px-3 py-2 text-[13px] text-info-muted-foreground"
                      >
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                        Układam treść ogłoszenia z Profilu Championa. To może potrwać do minuty.
                      </p>
                    ) : null}

                    {!ad || !rendered ? (
                      <div className="m-auto flex max-w-lg flex-col items-start gap-3 rounded-lg border border-border bg-card p-6">
                        <h2 className="text-base font-semibold text-foreground">
                          Ta rekrutacja nie ma jeszcze ogłoszenia
                        </h2>
                        <p className="text-sm text-muted-foreground">
                          Ułożę treść z Profilu Championa — bez nazwy klienta i bez stawek.
                          Dostaniesz ją w dwóch formatach: pola formularza Pracuj.pl i opis
                          JustJoin.IT.
                        </p>
                        {openSend ? (
                          <p role="status" className="text-sm text-foreground">
                            Mail do opiekuna Pracuj.pl otworzy się, gdy treść będzie gotowa.
                          </p>
                        ) : null}
                        <div className="flex flex-wrap items-center gap-3">
                          <SegmentedRadio
                            label="Język ogłoszenia"
                            size="sm"
                            value={firstLang}
                            options={LANG_OPTIONS}
                            disabled={busy}
                            onChange={setFirstLang}
                          />
                          <Button
                            type="button"
                            loading={generate.isPending}
                            onClick={() => generate.mutate(firstLang)}
                          >
                            Przygotuj ogłoszenie
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        {ad.source === "template" ? (
                          <p
                            role="status"
                            className="rounded-md bg-info-muted px-3 py-2 text-[13px] text-info-muted-foreground"
                          >
                            <strong className="font-semibold">Model był niedostępny.</strong> Treść
                            złożono z pól rekrutacji bez redakcji — przejrzyj ją albo użyj
                            „Przygotuj ponownie”.
                          </p>
                        ) : null}
                        {ad.stale ? (
                          <p
                            role="status"
                            className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-[13px] text-warning-muted-foreground"
                          >
                            <strong className="font-semibold">
                              Rekrutacja zmieniła się od przygotowania ogłoszenia.
                            </strong>{" "}
                            Użyj „Przygotuj ponownie”, żeby treść uwzględniła zmiany.
                          </p>
                        ) : null}
                        {blockingCount > 0 ? (
                          <p
                            role="alert"
                            className="rounded-md border border-destructive/20 bg-destructive-muted px-3 py-2 text-[13px] text-destructive-muted-foreground"
                          >
                            <strong className="font-semibold">Kopiowanie jest wyłączone.</strong> W
                            treści{" "}
                            {blockingCount === 1 ? "jest fragment, który" : "są fragmenty, które"}{" "}
                            nie {blockingCount === 1 ? "może" : "mogą"} trafić na portal — usuń{" "}
                            {blockingCount === 1 ? "go" : "je"} albo popraw tekst.
                          </p>
                        ) : null}
                        <TabsContent value="pracuj" className="mt-0">
                          <PracujTab
                            content={ad.content}
                            rendered={rendered}
                            findings={findings}
                            saving={save.isPending}
                            locked={generate.isPending}
                            drafts={drafts}
                            copied={copied}
                            copyBlockedReason={copyBlockedReason}
                            onCopy={(key, html, text) => void copy(key, html, text)}
                            onDraftChange={setDraft}
                            onSaveField={saveField}
                          />
                        </TabsContent>
                        <TabsContent value="jjit" className="mt-0">
                          <JustJoinTab
                            content={ad.content}
                            tech={ad.tech}
                            rendered={rendered}
                            findings={findings}
                            saving={save.isPending}
                            locked={generate.isPending}
                            drafts={drafts}
                            copied={copied}
                            copyBlockedReason={copyBlockedReason}
                            onCopy={(key, html, text) => void copy(key, html, text)}
                            onDraftChange={setDraft}
                            onSaveField={saveField}
                            onSaveTech={(tech) => saveAd(ad.content, tech)}
                          />
                        </TabsContent>
                      </>
                    )}
                  </div>
                  {ad && rendered ? (
                    <AdChannels
                      jobId={jobId}
                      state={state}
                      jobClosed={jobClosed}
                      locked={busy}
                      publishBlockedReason={publishBlockedReason}
                      publishingCareer={publishCareer.isPending}
                      careerCopied={careerCopied}
                      onPublishCareer={() => publishCareer.mutate()}
                      onCopyCareerLink={(url) => void copyCareerLink(url)}
                      onShowFinding={show}
                      onRemoveFinding={removeExcerpt}
                      api={api}
                      focusChannel={focusChannel}
                      openSkip={openSkip}
                      askRemind={askRemind}
                      openSend={openSend}
                    />
                  ) : null}
                </>
              )}
            </div>

            {ad ? (
              <footer className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-border bg-card px-4 py-2 text-[13px]">
                <span
                  data-testid="job-ad-checks-summary"
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-medium",
                    blockingCount > 0
                      ? "bg-destructive-muted text-destructive-muted-foreground"
                      : findings.length > 0
                        ? "bg-warning-muted text-warning-muted-foreground"
                        : "bg-success-muted text-success-muted-foreground",
                  )}
                >
                  {findings.length === 0 ? (
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  ) : null}
                  {checksSummary(findings)}
                </span>
                <span className="text-muted-foreground">
                  Jedna treść dla strony kariery i obu portali — poprawka zmienia wszystkie.
                </span>
              </footer>
            ) : null}
          </Tabs>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </>
  );
}
