"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  Loader2,
  MinusCircle,
  QrCode,
  Sparkles,
} from "lucide-react";

import { ogJobTiles } from "@/components/career/ogCard";
import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogBody, DialogFooter } from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { assignErrorMessage } from "@/lib/assign-error";
import {
  type ExpiryChoice,
  type InviteLink,
  type JobPublicProfile,
  type JobPublicProfileInput,
  type PublicProfileFinding,
  type PublicProfileSections,
  careerLinkQueryKey,
  careerLinksApi,
  findingsFromApproveError,
  inviteLinksQueryKey,
  jobPublicProfileQueryKey,
  useCareerLink,
  useInviteLinks,
  useJobPublicProfile,
  jobIsNotPublished,
  useShareableJob,
  useShareablePublishedJobs,
  type PublishedJobLite,
} from "@/lib/api/careerLinks";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { copyTextToClipboard } from "@/lib/clipboard";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { resolveViewState } from "@/lib/view-state";

import { LinkedInPreviewCard } from "./LinkedInPreviewCard";
import { ThemePicker } from "./ThemePicker";
import {
  EXPIRY_OPTIONS,
  FINDING_CATEGORIES,
  PAGE_STATE_LABEL,
  PROFILE_STATUS_LABEL,
  PROFILE_STATUS_VARIANT,
  activeLinkForJob,
  approveBlockedReason,
  careerPreviewHost,
  effectivePublicTitle,
  expiryToDays,
  formatDate,
  linkUrl,
  liveFindings,
  pageState,
  removeExcerpt,
} from "./share-utils";

interface FormState {
  /** „Tytuł na stronie"; pusty = tytuł domyślny z backendu. */
  public_title: string;
  subtitle: string;
  about: string;
  sections: PublicProfileSections;
  show_on_recruiter_page: boolean;
}

const SECTION_LABELS: { key: keyof PublicProfileSections; label: string }[] = [
  { key: "must", label: "Wymagania" },
  { key: "nice", label: "Mile widziane" },
  { key: "params", label: "Panel parametrów" },
  { key: "process", label: "Kroki procesu" },
];

function formFromProfile(profile: JobPublicProfile): FormState {
  return {
    public_title: profile.public_title ?? "",
    subtitle: profile.subtitle ?? "",
    about: profile.about ?? "",
    sections: { ...profile.sections },
    show_on_recruiter_page: profile.show_on_recruiter_page,
  };
}

function toInput(form: FormState): JobPublicProfileInput {
  return {
    public_title: form.public_title.trim() || null,
    subtitle: form.subtitle.trim() || null,
    about: form.about.trim() || null,
    sections: form.sections,
    show_on_recruiter_page: form.show_on_recruiter_page,
  };
}

export interface JobShareTabProps {
  enabled: boolean;
  defaultJobId?: number;
  /** Zmiana wybranej rekrutacji — opis w nagłówku okna. */
  onJobChange?: (title: string | null) => void;
}

export function JobShareTab({ enabled, defaultJobId, onJobChange }: JobShareTabProps) {
  const qc = useQueryClient();
  const { showSuccess, showError } = useToast();

  const [jobId, setJobId] = useState<number | null>(defaultJobId ?? null);
  const [form, setForm] = useState<FormState | null>(null);
  const [dirty, setDirty] = useState(false);
  const [blockedFindings, setBlockedFindings] = useState<PublicProfileFinding[] | null>(null);
  const [label, setLabel] = useState("");
  const [expiry, setExpiry] = useState<ExpiryChoice>("none");
  const [formError, setFormError] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [freshLink, setFreshLink] = useState<InviteLink | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (defaultJobId) setJobId(defaultJobId);
  }, [defaultJobId]);

  // Szukanie rekrutacji po stronie serwera + status wskazanej rekrutacji
  // jednym GET-em. Dawniej lista „pierwsze 100" i „nie ma jej na liście =
  // nieopublikowana" myliły rekrutację spoza setki z nieopublikowaną (FE-13).
  const [jobSearch, setJobSearch] = useState("");
  const debouncedJobSearch = useDebouncedValue(jobSearch.trim(), 300);
  const jobsQuery = useShareablePublishedJobs(enabled, debouncedJobSearch);
  const defaultJobQuery = useShareableJob(enabled && defaultJobId ? defaultJobId : null);
  // Rekrutacja wybrana z przefiltrowanej listy — jej tytuł zostaje po zmianie frazy.
  const [pickedJob, setPickedJob] = useState<PublishedJobLite | null>(null);
  const linksQuery = useInviteLinks(enabled);
  const profileQuery = useJobPublicProfile(enabled ? jobId : null);
  // Tylko po adres strony kariery (`base_url`) do podglądu posta.
  const careerQuery = useCareerLink(enabled);
  const profile = profileQuery.data ?? null;

  const jobs = useMemo(() => jobsQuery.data ?? [], [jobsQuery.data]);
  const defaultJob =
    defaultJobQuery.data && defaultJobQuery.data.id === jobId ? defaultJobQuery.data : null;
  const selectedJob =
    jobs.find((j) => j.id === jobId) ??
    (pickedJob?.id === jobId ? pickedJob : null) ??
    defaultJob;
  const jobTitle = selectedJob?.title || profile?.preview?.title || null;
  // Opcje selecta: wynik wyszukiwania + wybrana rekrutacja, jeśli fraza ją ukryła.
  const jobOptions = useMemo(
    () =>
      selectedJob && !jobs.some((j) => j.id === selectedJob.id) && !jobIsNotPublished(selectedJob)
        ? [selectedJob, ...jobs]
        : jobs,
    [jobs, selectedJob],
  );
  const defaultJobClosed = defaultJob != null && jobIsNotPublished(defaultJob);
  const defaultJobFailed =
    defaultJobQuery.isError && defaultJobId != null && jobId === defaultJobId;

  useEffect(() => {
    onJobChange?.(jobTitle);
  }, [jobTitle, onJobChange]);

  // Zmiana rekrutacji zeruje edycję, znaleziska z odmowy i świeży link.
  useEffect(() => {
    setForm(null);
    setDirty(false);
    setBlockedFindings(null);
    setFreshLink(null);
    setFormError(null);
    setLinkError(null);
  }, [jobId]);

  // Formularz idzie za serwerem, dopóki użytkownik niczego nie zmienił.
  useEffect(() => {
    if (profile && profile.job_id === jobId && !dirty) {
      setForm(formFromProfile(profile));
    }
  }, [profile, jobId, dirty]);

  const existingLink = useMemo(
    () => freshLink ?? activeLinkForJob(linksQuery.data ?? [], jobId),
    [freshLink, linksQuery.data, jobId],
  );

  // Tytuł na stronie też jest publiczny — znaleziska (np. nazwa klienta) go obejmują.
  const text = form ? `${form.public_title}\n${form.subtitle}\n${form.about}` : "";
  const savedText = profile
    ? `${profile.public_title ?? ""}\n${profile.subtitle ?? ""}\n${profile.about ?? ""}`
    : text;
  const shownFindings = liveFindings(
    blockedFindings ?? profile?.findings ?? [],
    text,
    savedText,
  );
  // Co dziś widzi kandydat: 404, wersję zatwierdzoną albo zatwierdzoną z czekającymi zmianami.
  const page = pageState(profile);
  const isLive = page !== "not_live";
  // Zielone „OK” tylko dla treści, którą serwer naprawdę sprawdził.
  const contentChecked =
    !dirty &&
    profile != null &&
    profile.status !== "none" &&
    Boolean(form && (form.about.trim() || form.subtitle.trim()));
  // Zatwierdzony, niezmieniony i aktualny — przycisk tylko kopiuje link.
  const copyOnly =
    profile?.status === "approved" && !dirty && !profile.approved_content_stale;
  const approveLabel = copyOnly
    ? "Skopiuj link"
    : isLive
      ? "Zatwierdź zmiany"
      : "Zatwierdź i skopiuj link";

  const update = (patch: Partial<FormState>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
    setFormError(null);
  };

  const applyServerProfile = (next: JobPublicProfile) => {
    qc.setQueryData(jobPublicProfileQueryKey(next.job_id), next);
    qc.invalidateQueries({ queryKey: careerLinkQueryKey() });
    setDirty(false);
    setForm(formFromProfile(next));
  };

  const draftMutation = useMutation({
    mutationFn: () => careerLinksApi.draftPublicProfile(jobId as number),
    onSuccess: (draft) => {
      update({ subtitle: draft.subtitle, about: draft.about });
      showSuccess("Szkic gotowy — przejrzyj i zapisz albo zatwierdź.");
    },
    onError: (err) =>
      setFormError(
        apiErrorMessage(err, "Nie udało się przygotować szkicu AI. Spróbuj ponownie."),
      ),
  });

  // Szablon graficzny (0478) — osobny zapis samego `theme`: nie rusza
  // niezapisanych pól formularza i nie cofa zatwierdzenia opisu.
  const [themeBusy, setThemeBusy] = useState(false);
  const handleTheme = async (next: string | null) => {
    if (jobId == null) return;
    setThemeBusy(true);
    try {
      const saved = await careerLinksApi.savePublicProfileTheme(jobId, next);
      qc.setQueryData(jobPublicProfileQueryKey(saved.job_id), saved);
      showSuccess(next ? "Zmieniono szablon strony." : "Przywrócono szablon domyślny.");
    } catch (err) {
      showError(apiErrorMessage(err, "Nie udało się zmienić szablonu."));
    } finally {
      setThemeBusy(false);
    }
  };

  const saveProfile = async (): Promise<JobPublicProfile | null> => {
    if (!form || jobId == null) return null;
    try {
      const saved = await careerLinksApi.savePublicProfile(jobId, toInput(form));
      applyServerProfile(saved);
      setBlockedFindings(null);
      return saved;
    } catch (err) {
      setFormError(apiErrorMessage(err, "Nie udało się zapisać opisu."));
      return null;
    }
  };

  const createLink = async (): Promise<InviteLink | null> => {
    if (jobId == null) return null;
    setLinkError(null);
    try {
      const link = await careerLinksApi.createInviteLink({
        job_id: jobId,
        label: label.trim() || undefined,
        expires_in_days: expiryToDays(expiry),
      });
      setFreshLink(link);
      qc.invalidateQueries({ queryKey: inviteLinksQueryKey() });
      qc.invalidateQueries({ queryKey: careerLinkQueryKey() });
      return link;
    } catch (err) {
      setLinkError(assignErrorMessage(err));
      return null;
    }
  };

  const copyLink = async (link: InviteLink) => {
    const ok = await copyTextToClipboard(linkUrl(link));
    if (ok) showSuccess("Skopiowano link.");
    else showError("Nie udało się skopiować — zaznacz adres i skopiuj ręcznie.");
    return ok;
  };

  const handleSaveDraft = async () => {
    setBusy(true);
    const saved = await saveProfile();
    setBusy(false);
    if (saved) showSuccess("Szkic zapisany.");
  };

  const handleCreateLink = async () => {
    setBusy(true);
    const link = await createLink();
    setBusy(false);
    // Przed zatwierdzeniem opisu link daje kandydatowi 404, a LinkedIn
    // zapamiętuje pusty podgląd — do schowka trafia dopiero działający adres.
    if (link && isLive) await copyLink(link);
  };

  /** Plakat A4 z kodem QR (etap 3) — z opublikowanej wersji opisu, ten sam link. */
  const [posterBusy, setPosterBusy] = useState(false);
  const handlePoster = async (link: InviteLink) => {
    if (jobId == null) return;
    setPosterBusy(true);
    try {
      await downloadAuthenticatedFile(
        `/api/jobs/${jobId}/public-profile/poster.pdf`,
        `plakat-${link.slug ?? jobId}.pdf`,
      );
    } catch (err) {
      showError(apiErrorMessage(err, "Nie udało się przygotować plakatu."));
    } finally {
      setPosterBusy(false);
    }
  };

  /** „Odrzuć zmiany”: szkic wraca do wersji, którą widzi kandydat. */
  const handleDiscard = async () => {
    const live = profile?.live;
    if (jobId == null || !form || !live) return;
    setBusy(true);
    setFormError(null);
    try {
      const restored = await careerLinksApi.savePublicProfile(jobId, {
        public_title:
          live.title === (profile?.default_title ?? profile?.effective_title)
            ? null
            : live.title,
        subtitle: live.subtitle,
        about: live.about,
        sections: live.sections,
        show_on_recruiter_page: form.show_on_recruiter_page,
      });
      applyServerProfile(restored);
      setBlockedFindings(null);
      showSuccess("Przywrócono opublikowaną wersję opisu.");
    } catch (err) {
      setFormError(apiErrorMessage(err, "Nie udało się przywrócić opublikowanej wersji."));
    } finally {
      setBusy(false);
    }
  };

  const handleApproveAndCopy = async () => {
    if (jobId == null || !form) return;
    setBusy(true);
    setFormError(null);
    try {
      if (copyOnly) {
        // Zatwierdzony i niezmieniony — ponowne zatwierdzenie niczego nie
        // publikuje, a wysyłało aktualizację na portale.
        const link = existingLink ?? (await createLink());
        if (link) await copyLink(link);
        return;
      }
      if (dirty || profile?.status === "none") {
        const saved = await saveProfile();
        if (!saved) return;
      }
      try {
        const approved = await careerLinksApi.approvePublicProfile(jobId);
        applyServerProfile(approved);
        setBlockedFindings(null);
        // Zatwierdzenie potrafi wymienić adres linku z nazwą klienta (stary
        // daje 404) — kopiujemy adres odświeżony z serwera, nie ten z pamięci.
        setFreshLink(null);
        await qc.invalidateQueries({ queryKey: inviteLinksQueryKey() });
      } catch (err) {
        const findings = findingsFromApproveError(err);
        if (findings) {
          setBlockedFindings(findings);
          setFormError("Opis zawiera fragmenty, których nie publikujemy — popraw je i zatwierdź ponownie.");
        } else {
          setFormError(apiErrorMessage(err, "Nie udało się zatwierdzić opisu."));
        }
        return;
      }
      if (isLive) {
        // Link już krąży — zatwierdzenie zmian tylko podmienia treść strony.
        showSuccess("Zmiany opublikowane — strona pokazuje nową wersję.");
        return;
      }
      const refreshed = activeLinkForJob(
        qc.getQueryData<InviteLink[]>(inviteLinksQueryKey()) ?? [],
        jobId,
      );
      const link = refreshed ?? (await createLink());
      if (!link) return;
      await copyLink(link);
    } finally {
      setBusy(false);
    }
  };

  // ── Powód wyłączenia „Zatwierdź" ─────────────────────────────────────
  let approveDisabledReason: string | null = null;
  if (jobId == null) approveDisabledReason = "Wybierz rekrutację.";
  else if (!form) approveDisabledReason = "Wczytuję opis publiczny…";
  else if (copyOnly) approveDisabledReason = null;
  else if (!form.about.trim()) approveDisabledReason = "Uzupełnij opis „O projekcie”.";
  else if (shownFindings.length > 0) approveDisabledReason = approveBlockedReason(shownFindings);

  const profileState = resolveViewState({
    isLoading: profileQuery.isLoading,
    isError: profileQuery.isError,
    error: profileQuery.error,
    isSuccess: profileQuery.isSuccess,
  });

  const jobsState = resolveViewState({
    isLoading: jobsQuery.isLoading,
    isError: jobsQuery.isError,
    error: jobsQuery.error,
    isSuccess: jobsQuery.isSuccess,
    isEmpty: jobs.length === 0 && !debouncedJobSearch,
  });

  const host = careerPreviewHost(
    existingLink ? linkUrl(existingLink) : null,
    careerQuery.data?.base_url,
  );
  // Starszy backend nie zwraca `default_title` — wtedy `effective_title`, potem tytuł rekrutacji.
  const defaultTitle = profile?.default_title ?? profile?.effective_title ?? null;
  const previewTitle = effectivePublicTitle(
    form ? form.public_title : profile?.public_title,
    defaultTitle,
    profile?.preview?.title ?? jobTitle,
  );

  return (
    <>
      <DialogBody className="space-y-5">
        {/* Wybór rekrutacji */}
        <FormField label="Rekrutacja" required>
          {jobsState === "error" || jobsState === "forbidden" || jobsState === "not_found" ? (
            <QueryStateNotice
              state={jobsState === "forbidden" ? "forbidden" : "error"}
              description="Nie udało się pobrać listy rekrutacji."
              onRetry={() => jobsQuery.refetch()}
            />
          ) : (
            <div className="space-y-2">
            <Input
              type="search"
              value={jobSearch}
              onChange={(e) => setJobSearch(e.target.value)}
              placeholder="Szukaj opublikowanej rekrutacji…"
              aria-label="Szukaj rekrutacji"
            />
            <Select
              value={jobId != null ? String(jobId) : ""}
              onValueChange={(v) => {
                const id = Number(v);
                setJobId(id);
                setPickedJob(jobOptions.find((j) => j.id === id) ?? null);
              }}
              disabled={jobsState === "loading"}
            >
              <SelectTrigger aria-label="Rekrutacja">
                <SelectValue
                  placeholder={
                    jobsState === "loading"
                      ? "Ładowanie…"
                      : jobsState === "empty"
                        ? "Brak opublikowanych rekrutacji"
                        : "Wybierz rekrutację"
                  }
                >
                  {jobTitle ?? undefined}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {jobOptions.length === 0 && debouncedJobSearch ? (
                  <p className="px-2 py-1.5 text-sm text-muted-foreground">
                    Brak opublikowanych rekrutacji pasujących do «{debouncedJobSearch}».
                  </p>
                ) : null}
                {jobOptions.map((j) => (
                  <SelectItem key={j.id} value={String(j.id)}>
                    {j.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            </div>
          )}
          {defaultJobClosed ? (
            <p className="text-xs text-warning-muted-foreground">
              Ta rekrutacja nie jest opublikowana — link publiczny działa tylko dla
              opublikowanych rekrutacji.
            </p>
          ) : defaultJobFailed ? (
            <p className="text-xs text-destructive">
              {apiErrorMessage(defaultJobQuery.error, "Nie udało się wczytać tej rekrutacji.")}
            </p>
          ) : null}
        </FormField>

        {jobId != null && profile ? (
          <div
            role="status"
            data-testid="career-page-state"
            className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm"
          >
            <Badge size="sm" variant={isLive ? "success" : "neutral"}>
              {PAGE_STATE_LABEL[page]}
            </Badge>
            <span className="min-w-0 flex-1 text-muted-foreground">
              {page === "not_live"
                ? "Kandydat zobaczy stronę po zatwierdzeniu opisu."
                : page === "live_pending"
                  ? `Kandydaci widzą wersję zatwierdzoną${
                      profile.approved_at ? ` ${formatDate(profile.approved_at)}` : ""
                    }. Zmiany czekają na zatwierdzenie.`
                  : `Zatwierdzona${profile.approved_at ? ` ${formatDate(profile.approved_at)}` : ""}${
                      profile.approved_by_name ? ` · ${profile.approved_by_name}` : ""
                    }.`}
            </span>
            {page === "live_pending" ? (
              <Button size="sm" variant="outline" onClick={handleDiscard} disabled={busy}>
                Odrzuć zmiany
              </Button>
            ) : null}
          </div>
        ) : null}

        {jobId == null ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
            Wybierz rekrutację, żeby przygotować opis publiczny i link.
          </p>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            {/* Lewa kolumna: opis publiczny + kontrola */}
            <div className="space-y-5">
              <section className="space-y-3" aria-labelledby="public-profile-heading">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <h3 id="public-profile-heading" className="text-sm font-semibold text-foreground">
                      Opis publiczny
                    </h3>
                    {profile ? (
                      <Badge size="sm" variant={PROFILE_STATUS_VARIANT[profile.status]}>
                        {PROFILE_STATUS_LABEL[profile.status]}
                      </Badge>
                    ) : null}
                    {dirty ? (
                      <span className="text-xs text-muted-foreground">· niezapisane zmiany</span>
                    ) : null}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => draftMutation.mutate()}
                    disabled={!form || draftMutation.isPending || busy}
                  >
                    {draftMutation.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    Szkic AI z profilu Championa
                  </Button>
                </div>

                {profile?.status === "approved" && profile.approved_content_stale ? (
                  <p
                    role="status"
                    className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
                  >
                    Wymagania, miasto, start albo długość zmieniły się w rekrutacji od zatwierdzenia.
                    Strona kariery i portale pokazują stan z zatwierdzenia — zatwierdź opis ponownie,
                    żeby opublikować zmiany z podglądu.
                  </p>
                ) : null}

                {profileState === "loading" ? (
                  <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Wczytuję opis…
                  </div>
                ) : profileState !== "ready" ? (
                  <QueryStateNotice
                    state={profileState === "forbidden" ? "forbidden" : "error"}
                    description="Nie udało się wczytać opisu publicznego. To nie znaczy, że go nie ma."
                    onRetry={() => profileQuery.refetch()}
                  />
                ) : form ? (
                  <>
                    <FormField
                      label="Tytuł na stronie"
                      htmlFor="pp-public-title"
                      description="Puste = tytuł domyślny, bez nazwy klienta i kodów wewnętrznych."
                    >
                      <Input
                        id="pp-public-title"
                        value={form.public_title}
                        maxLength={200}
                        onChange={(e) => update({ public_title: e.target.value })}
                        placeholder={defaultTitle ?? jobTitle ?? "np. Senior Java Developer"}
                      />
                    </FormField>
                    <FormField label="Podtytuł (linia komentarza pod tytułem)" htmlFor="pp-subtitle">
                      <Input
                        id="pp-subtitle"
                        value={form.subtitle}
                        maxLength={200}
                        onChange={(e) => update({ subtitle: e.target.value })}
                        placeholder="np. rozwój platformy płatności w dużym projekcie"
                      />
                    </FormField>
                    <FormField label="O projekcie" htmlFor="pp-about">
                      <Textarea
                        id="pp-about"
                        value={form.about}
                        rows={7}
                        onChange={(e) => update({ about: e.target.value })}
                        placeholder="Kilka akapitów o projekcie i zespole — bez nazwy klienta i bez stawek."
                      />
                    </FormField>
                    <fieldset className="space-y-2">
                      <legend className="mb-1 text-sm font-medium text-foreground">
                        Pokaż na stronie
                      </legend>
                      <div className="grid grid-cols-2 gap-2">
                        {SECTION_LABELS.map(({ key, label: sectionLabel }) => (
                          <label
                            key={key}
                            className="flex cursor-pointer items-center gap-2 text-sm text-foreground"
                          >
                            <Checkbox
                              checked={form.sections[key]}
                              onCheckedChange={(v) =>
                                update({ sections: { ...form.sections, [key]: v === true } })
                              }
                              aria-label={sectionLabel}
                            />
                            {sectionLabel}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 text-sm text-foreground">
                      <span>
                        Pokaż na mojej stronie
                        <span className="block text-xs text-muted-foreground">
                          Rekrutacja pojawi się na Twoim stałym linku po zatwierdzeniu.
                        </span>
                      </span>
                      <Switch
                        checked={form.show_on_recruiter_page}
                        onCheckedChange={(v) => update({ show_on_recruiter_page: v })}
                        aria-label="Pokaż na mojej stronie"
                      />
                    </label>
                  </>
                ) : null}
              </section>

              {form ? (
                <section className="space-y-2" aria-labelledby="public-check-heading">
                  <h3 id="public-check-heading" className="text-sm font-semibold text-foreground">
                    Kontrola przed publikacją
                  </h3>
                  <ul className="space-y-1.5" data-testid="public-profile-findings">
                    {FINDING_CATEGORIES.map((cat) => {
                      const hits = shownFindings.filter((f) => cat.codes.includes(f.code));
                      if (hits.length === 0) {
                        // Zielone tylko dla treści sprawdzonej przez serwer — puste
                        // pole albo niezapisana zmiana to „jeszcze nie sprawdzono”.
                        return contentChecked ? (
                          <li key={cat.key} className="flex items-start gap-2 text-sm text-foreground">
                            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                            {cat.okLabel}
                          </li>
                        ) : (
                          <li
                            key={cat.key}
                            className="flex items-start gap-2 text-sm text-muted-foreground"
                            data-testid="finding-unchecked"
                          >
                            <MinusCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                            {cat.okLabel} — sprawdzę po zapisaniu
                          </li>
                        );
                      }
                      return hits.map((f, i) => (
                        <li
                          key={`${cat.key}-${i}`}
                          className="flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted px-2.5 py-2 text-sm text-warning-muted-foreground"
                          role="alert"
                        >
                          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                          <span className="min-w-0 flex-1">
                            {f.message}
                            {f.excerpt ? (
                              <>
                                {" "}
                                <Button
                                  size="sm"
                                  variant="tertiary"
                                  className="h-auto p-0 align-baseline"
                                  onClick={() =>
                                    update({
                                      public_title: removeExcerpt(
                                        form.public_title,
                                        f.excerpt as string,
                                      ),
                                      subtitle: removeExcerpt(form.subtitle, f.excerpt as string),
                                      about: removeExcerpt(form.about, f.excerpt as string),
                                    })
                                  }
                                >
                                  Usuń fragment
                                </Button>
                              </>
                            ) : null}
                          </span>
                        </li>
                      ));
                    })}
                  </ul>
                </section>
              ) : null}
            </div>

            {/* Prawa kolumna: podgląd + link */}
            <div className="space-y-4">
              <div className="space-y-1.5">
                <span className="text-sm font-medium text-foreground">Podgląd posta na LinkedInie</span>
                <LinkedInPreviewCard
                  status={{ label: "Rekrutacja otwarta" }}
                  kicker="Rekrutacja IT"
                  headline={previewTitle}
                  facts={ogJobTiles(profile?.preview?.params)}
                  foot="Aplikuj w 2 minuty →"
                  cardTitle={previewTitle}
                  host={host}
                  theme={profile ? profile.theme ?? profile.theme_default : null}
                />
              </div>

              {profile ? (
                <ThemePicker
                  value={profile.theme}
                  defaultTheme={profile.theme_default}
                  onChange={handleTheme}
                  busy={themeBusy}
                />
              ) : null}

              <section className="space-y-3" aria-labelledby="job-link-heading">
                <h3 id="job-link-heading" className="text-sm font-semibold text-foreground">
                  Link
                </h3>
                {linksQuery.isLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Sprawdzam linki…
                  </div>
                ) : linksQuery.isError ? (
                  <QueryStateNotice
                    state="error"
                    description="Nie udało się sprawdzić, czy masz już link do tej rekrutacji."
                    onRetry={() => linksQuery.refetch()}
                  />
                ) : existingLink ? (
                  <div className="space-y-2">
                    {/* Cały adres, z łamaniem — w polu tekstowym slug znikał za krawędzią. */}
                    <p
                      data-testid="job-link-url"
                      aria-label="Adres linku"
                      className={
                        isLive
                          ? "select-all break-all rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-foreground"
                          : "break-all rounded-md border border-dashed border-border bg-muted/40 px-3 py-2 font-mono text-xs text-muted-foreground"
                      }
                    >
                      {linkUrl(existingLink)}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => copyLink(existingLink)}
                        disabled={!isLive}
                      >
                        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                        Kopiuj
                      </Button>
                      {isLive ? (
                        <Button variant="outline" size="sm" asChild>
                          <a href={linkUrl(existingLink)} target="_blank" rel="noopener noreferrer">
                            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                            Otwórz stronę
                          </a>
                        </Button>
                      ) : null}
                      {isLive ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handlePoster(existingLink)}
                          loading={posterBusy}
                          disabled={posterBusy}
                        >
                          <QrCode className="h-3.5 w-3.5" aria-hidden="true" />
                          Plakat z QR
                        </Button>
                      ) : null}
                    </div>
                    {isLive ? (
                      <p className="text-xs text-muted-foreground">
                        {existingLink.label ? `${existingLink.label} · ` : ""}
                        {existingLink.expires_at
                          ? `ważny do ${formatDate(existingLink.expires_at)}`
                          : "ważny do zamknięcia rekrutacji"}
                      </p>
                    ) : (
                      <p className="text-xs text-warning-muted-foreground" data-testid="link-not-live">
                        Link zadziała po zatwierdzeniu opisu. Wcześniej kandydat zobaczyłby błąd,
                        a LinkedIn zapamiętałby pusty podgląd.
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3">
                    <FormField label="Etykieta źródła (do statystyk)" htmlFor="link-label">
                      <Input
                        id="link-label"
                        value={label}
                        maxLength={120}
                        onChange={(e) => setLabel(e.target.value)}
                        placeholder="np. Post LinkedIn 21.09"
                      />
                    </FormField>
                    <FormField label="Ważność linku">
                      <Select value={expiry} onValueChange={(v) => setExpiry(v as ExpiryChoice)}>
                        <SelectTrigger aria-label="Ważność linku">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {EXPIRY_OPTIONS.map((o) => (
                            <SelectItem key={o.value} value={o.value}>
                              {o.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormField>
                    <Button
                      variant="outline"
                      className="w-full"
                      onClick={handleCreateLink}
                      disabled={busy}
                    >
                      Wygeneruj link
                    </Button>
                  </div>
                )}
                {linkError ? (
                  <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    {linkError}
                  </p>
                ) : null}
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Link działa, dopóki rekrutacja jest otwarta; potem pokazuje „proces
                  zakończony”. Zgłoszenie trafia do „Nowi” tej rekrutacji, a Ty dostajesz
                  powiadomienie.
                </p>
              </section>
            </div>
          </div>
        )}

        {formError ? (
          <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {formError}
          </p>
        ) : null}
      </DialogBody>

      <DialogFooter className="sm:items-center sm:justify-between">
        <span className="text-sm text-warning-muted-foreground" data-testid="approve-disabled-reason">
          {/* Bez wybranej rekrutacji treść okna mówi to samo — bez powtórki w stopce. */}
          {jobId == null ? "" : (approveDisabledReason ?? "")}
        </span>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <Button
            variant="outline"
            onClick={handleSaveDraft}
            disabled={!form || !dirty || busy}
          >
            {isLive ? "Zapisz zmiany" : "Zapisz szkic"}
          </Button>
          <Button
            onClick={handleApproveAndCopy}
            disabled={approveDisabledReason != null || busy}
            loading={busy}
          >
            {approveLabel}
          </Button>
        </div>
      </DialogFooter>
    </>
  );
}
