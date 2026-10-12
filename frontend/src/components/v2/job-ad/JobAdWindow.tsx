"use client";

/**
 * Okno „Ogłoszenie na portale” (12.10.2026) — jedna treść rekrutacji w dwóch
 * formatach: pola formularza Pracuj.pl i opis JustJoin.IT. Rekruter układa
 * ją jednym kliknięciem z Profilu Championa, poprawia i kopiuje do portalu.
 *
 * Do schowka idą WYŁĄCZNIE teksty policzone przez serwer dla zapisanego
 * stanu (`rendered`), po kontroli: znalezisko blokujące (nazwa klienta,
 * kwota, kontakt, nazwisko) wyłącza kopiowanie w całym oknie.
 *
 * Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenie-na-portale-kopiuj-wklej.md`.
 */

import { useRef, useState } from "react";
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

import { AdChecksPanel } from "./AdChecksPanel";
import { AdFactsRail } from "./AdFactsRail";
import { JustJoinTab } from "./JustJoinTab";
import { PracujTab } from "./PracujTab";
import { withEdited, withoutExcerpt, type AdEditKey } from "./job-ad-edit";

export type JobAdTab = "pracuj" | "jjit";

/** Trzy wywołania okna — harness `/preview/job-ad` podaje je z pamięci. */
export type JobAdWindowApi = Pick<typeof jobAdApi, "get" | "generate" | "save">;

export interface JobAdWindowProps {
  jobId: number;
  jobTitle: string;
  open: boolean;
  onClose: () => void;
  api?: JobAdWindowApi;
  initialTab?: JobAdTab;
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
  open,
  onClose,
  api = jobAdApi,
  initialTab = "pracuj",
}: JobAdWindowProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [tab, setTab] = useState<JobAdTab>(initialTab);
  const [firstLang, setFirstLang] = useState<AdLang>("pl");
  const [copied, setCopied] = useState<ReadonlySet<string>>(new Set());
  const bodyRef = useRef<HTMLDivElement | null>(null);

  const queryKey = jobAdQueryKey(jobId);
  const query = useQuery({ queryKey, queryFn: () => api.get(jobId), enabled: open });

  const applyState = (state: JobAdState) => {
    queryClient.setQueryData(queryKey, state);
    // Nowa treść = nowe teksty do skopiowania; stare „Skopiowane” już nie obowiązuje.
    setCopied(new Set());
  };

  const generate = useMutation({
    mutationFn: (lang: AdLang) => api.generate(jobId, lang),
    onSuccess: (state) => {
      applyState(state);
      if (state.ad?.source === "ai") showSuccess("Ogłoszenie przygotowane.");
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się przygotować ogłoszenia. Spróbuj ponownie.")),
  });

  const save = useMutation({
    mutationFn: (input: { content: AdContent; tech: AdTechItem[] }) =>
      api.save(jobId, { ...input, expected_updated_at: query.data?.ad?.updated_at ?? null }),
    onSuccess: applyState,
    onError: (err) => {
      if (isAdChangedError(err)) void query.refetch();
      showError(apiErrorMessage(err, "Nie udało się zapisać poprawki. Spróbuj ponownie."));
    },
  });

  const state = query.data;
  const ad = state?.ad ?? null;
  const rendered = state?.rendered ?? null;
  const findings = state?.findings ?? [];
  const busy = generate.isPending || save.isPending;

  const saveAd = async (content: AdContent, tech: AdTechItem[]): Promise<boolean> => {
    try {
      await save.mutateAsync({ content, tech });
      return true;
    } catch {
      return false;
    }
  };

  const saveField = (key: AdEditKey, text: string) =>
    ad ? saveAd(withEdited(ad.content, key, text), ad.tech) : Promise.resolve(false);

  const regenerate = async (lang: AdLang) => {
    const confirmed = await askConfirm({
      title: "Przygotować ogłoszenie ponownie?",
      description:
        "Obecna treść, razem z ręcznymi poprawkami, zostanie zastąpiona nową. Jeśli model będzie niedostępny, obecna treść zostanie bez zmian.",
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
          <DialogTitle className="sr-only">Ogłoszenie na portale</DialogTitle>
          <Tabs
            value={tab}
            onValueChange={(value) => setTab(value as JobAdTab)}
            className="flex min-h-0 flex-1 flex-col"
          >
            <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-card px-4 py-2">
              <div className="flex min-w-0 items-center gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">Ogłoszenie na portale</p>
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
                    saving={save.isPending}
                    onSaveTerms={(terms) =>
                      ad ? saveAd({ ...ad.content, ...terms }, ad.tech) : Promise.resolve(false)
                    }
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
                          Ułożę treść z Profilu Championa — bez nazwy klienta i bez stawek. Dostaniesz
                          ją w dwóch formatach: pola formularza Pracuj.pl i opis JustJoin.IT.
                        </p>
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
                            treści {blockingCount === 1 ? "jest fragment, który" : "są fragmenty, które"}{" "}
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
                            copied={copied}
                            copyBlockedReason={copyBlockedReason}
                            onCopy={(key, html, text) => void copy(key, html, text)}
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
                            copied={copied}
                            copyBlockedReason={copyBlockedReason}
                            onCopy={(key, html, text) => void copy(key, html, text)}
                            onSaveField={saveField}
                            onSaveTech={(tech) => saveAd(ad.content, tech)}
                          />
                        </TabsContent>
                      </>
                    )}
                  </div>
                  {ad && findings.length > 0 ? (
                    <AdChecksPanel
                      findings={findings}
                      busy={busy}
                      onShow={show}
                      onRemove={removeExcerpt}
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
                  Ta sama treść w obu zakładkach — poprawka w jednej zmienia obie.
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
