"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Loader2,
  Sparkles,
} from "lucide-react";

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
  useInviteLinks,
  useJobPublicProfile,
  useShareablePublishedJobs,
} from "@/lib/api/careerLinks";
import { copyTextToClipboard } from "@/lib/clipboard";
import { resolveViewState } from "@/lib/view-state";

import { LinkedInPreviewCard } from "./LinkedInPreviewCard";
import {
  EXPIRY_OPTIONS,
  FINDING_CATEGORIES,
  PROFILE_STATUS_LABEL,
  PROFILE_STATUS_VARIANT,
  activeLinkForJob,
  approveBlockedReason,
  expiryToDays,
  formatDate,
  hostFromUrl,
  linkUrl,
  liveFindings,
  paramsTagline,
  removeExcerpt,
  slugifyTitle,
} from "./share-utils";

interface FormState {
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
    subtitle: profile.subtitle ?? "",
    about: profile.about ?? "",
    sections: { ...profile.sections },
    show_on_recruiter_page: profile.show_on_recruiter_page,
  };
}

function toInput(form: FormState): JobPublicProfileInput {
  return {
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

  const jobsQuery = useShareablePublishedJobs(enabled);
  const linksQuery = useInviteLinks(enabled);
  const profileQuery = useJobPublicProfile(enabled ? jobId : null);
  const profile = profileQuery.data ?? null;

  const jobs = useMemo(() => jobsQuery.data ?? [], [jobsQuery.data]);
  const selectedJob = jobs.find((j) => j.id === jobId) ?? null;
  const jobTitle = selectedJob?.title ?? profile?.preview?.title ?? null;
  const jobNotListed = jobsQuery.isSuccess && jobId != null && !selectedJob;

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

  const text = form ? `${form.subtitle}\n${form.about}` : "";
  const shownFindings = liveFindings(blockedFindings ?? profile?.findings ?? [], text);

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
    if (link) await copyLink(link);
  };

  const handleApproveAndCopy = async () => {
    if (jobId == null || !form) return;
    setBusy(true);
    setFormError(null);
    try {
      if (dirty || profile?.status === "none") {
        const saved = await saveProfile();
        if (!saved) return;
      }
      try {
        const approved = await careerLinksApi.approvePublicProfile(jobId);
        applyServerProfile(approved);
        setBlockedFindings(null);
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
      const link = existingLink ?? (await createLink());
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
    isEmpty: jobs.length === 0,
  });

  const host = hostFromUrl(existingLink ? linkUrl(existingLink) : null);
  const previewTitle = jobTitle ?? "Rekrutacja";

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
            <Select
              value={jobId != null ? String(jobId) : ""}
              onValueChange={(v) => setJobId(Number(v))}
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
                {jobs.map((j) => (
                  <SelectItem key={j.id} value={String(j.id)}>
                    {j.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {jobNotListed ? (
            <p className="text-xs text-warning-muted-foreground">
              Ta rekrutacja nie jest opublikowana — link publiczny działa tylko dla
              opublikowanych rekrutacji.
            </p>
          ) : null}
        </FormField>

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
                        return (
                          <li key={cat.key} className="flex items-start gap-2 text-sm text-foreground">
                            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                            {cat.okLabel}
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
                  {dirty ? (
                    <p className="text-xs text-muted-foreground">
                      Treść zmieniona — pełną kontrolę serwer zrobi przy zapisie i zatwierdzeniu.
                    </p>
                  ) : null}
                </section>
              ) : null}
            </div>

            {/* Prawa kolumna: podgląd + link */}
            <div className="space-y-4">
              <div className="space-y-1.5">
                <span className="text-sm font-medium text-foreground">Podgląd posta na LinkedInie</span>
                <LinkedInPreviewCard
                  command={`cat /rekrutacje/${slugifyTitle(previewTitle)}`}
                  headline={previewTitle}
                  tagline={paramsTagline(profile?.preview?.params)}
                  cardTitle={`${previewTitle} — Dynaminds`}
                  host={host}
                />
              </div>

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
                  <div className="space-y-1.5">
                    <div className="flex gap-2">
                      <Input
                        readOnly
                        value={linkUrl(existingLink)}
                        aria-label="Adres linku"
                        className="font-mono text-xs"
                        onFocus={(e) => e.currentTarget.select()}
                      />
                      <Button variant="outline" onClick={() => copyLink(existingLink)}>
                        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                        Kopiuj
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {existingLink.label ? `${existingLink.label} · ` : ""}
                      {existingLink.expires_at
                        ? `ważny do ${formatDate(existingLink.expires_at)}`
                        : "ważny do zamknięcia rekrutacji"}
                    </p>
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
                  Link działa, dopóki rekrutacja jest otwarta. Po zamknięciu kandydat zobaczy
                  zaproszenie do Twojej bazy. Kandydaci trafiają na etap „Nowy”, a Ty dostajesz
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
          {approveDisabledReason ?? ""}
        </span>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <Button
            variant="outline"
            onClick={handleSaveDraft}
            disabled={!form || !dirty || busy}
          >
            Zapisz szkic
          </Button>
          <Button
            onClick={handleApproveAndCopy}
            disabled={approveDisabledReason != null || busy}
            loading={busy}
          >
            Zatwierdź i skopiuj link
          </Button>
        </div>
      </DialogFooter>
    </>
  );
}
