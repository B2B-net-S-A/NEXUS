"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Copy, Loader2, PowerOff } from "lucide-react";

import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DialogBody } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import {
  type CareerLinkJob,
  careerLinkQueryKey,
  careerLinksApi,
  useCareerLink,
  useSlugAvailability,
} from "@/lib/api/careerLinks";
import { copyTextToClipboard } from "@/lib/clipboard";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { InviteLinkHistory } from "./InviteLinkHistory";
import { LinkedInPreviewCard } from "./LinkedInPreviewCard";
import {
  PROFILE_STATUS_LABEL,
  PROFILE_STATUS_VARIANT,
  hostFromUrl,
  isSlugFormatValid,
} from "./share-utils";

/** Opóźnienie sprawdzania dostępności adresu (ms) — eksport dla testów. */
export const SLUG_CHECK_DEBOUNCE_MS = 400;

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}

function Stat({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xl font-semibold tabular-nums text-foreground">
        {value == null ? "—" : value}
      </span>
    </div>
  );
}

function VisibilityRow({
  job,
  onToggle,
  pending,
}: {
  job: CareerLinkJob;
  onToggle: (show: boolean) => void;
  pending: boolean;
}) {
  const approved = job.profile_status === "approved";
  const reason = approved ? null : "Najpierw zatwierdź opis publiczny tej rekrutacji.";
  return (
    <li className="flex items-center gap-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-foreground">{job.title}</div>
        {reason ? <div className="text-xs text-muted-foreground">{reason}</div> : null}
      </div>
      <Badge size="sm" variant={PROFILE_STATUS_VARIANT[job.profile_status]}>
        {job.profile_status === "draft" ? "szkic" : PROFILE_STATUS_LABEL[job.profile_status].toLowerCase()}
      </Badge>
      <Switch
        checked={approved && job.show_on_recruiter_page}
        disabled={!approved || pending}
        onCheckedChange={onToggle}
        aria-label={`Pokaż na stronie: ${job.title}`}
        title={reason ?? undefined}
      />
    </li>
  );
}

export function GeneralLinkTab({ enabled }: { enabled: boolean }) {
  const qc = useQueryClient();
  const { showSuccess, showError } = useToast();
  const userName = useAuthStore((s) => s.user?.name ?? "");
  const firstName = userName.trim().split(/\s+/)[0] || "Rekruter";

  const careerQuery = useCareerLink(enabled);
  const data = careerQuery.data ?? null;
  const link = data?.link ?? null;

  const [slug, setSlug] = useState("");
  const [touched, setTouched] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDisable, setConfirmDisable] = useState(false);

  // Adres idzie za serwerem, dopóki użytkownik go nie edytuje.
  useEffect(() => {
    if (!touched && data) setSlug(link?.slug ?? data.suggested_slug ?? "");
  }, [data, link?.slug, touched]);

  const normalized = slug.trim().toLowerCase();
  const isCurrent = !!link && normalized === link.slug;
  const formatOk = isSlugFormatValid(normalized);
  const debounced = useDebounced(normalized, SLUG_CHECK_DEBOUNCE_MS);
  const shouldCheck = enabled && formatOk && !isCurrent && debounced === normalized;
  const availability = useSlugAvailability(shouldCheck ? debounced : null);

  let slugMessage: { tone: "ok" | "bad" | "muted"; text: string } | null = null;
  if (!normalized) slugMessage = null;
  else if (isCurrent) slugMessage = { tone: "ok", text: "To Twój obecny adres · działa bez terminu, do odwołania" };
  else if (!formatOk)
    slugMessage = {
      tone: "bad",
      text: "Tylko małe litery, cyfry i myślnik (3–40 znaków, bez myślnika na początku i końcu).",
    };
  else if (!shouldCheck || availability.isLoading) slugMessage = { tone: "muted", text: "Sprawdzam adres…" };
  else if (availability.isError) slugMessage = { tone: "bad", text: "Nie udało się sprawdzić adresu — spróbuj za chwilę." };
  else if (availability.data?.available)
    slugMessage = { tone: "ok", text: "Adres wolny · działa bez terminu, do odwołania" };
  else if (availability.data)
    slugMessage = { tone: "bad", text: availability.data.reason || "Ten adres jest zajęty." };

  const canSave =
    formatOk && !isCurrent && availability.data?.available === true && shouldCheck;

  const saveMutation = useMutation({
    mutationFn: () => careerLinksApi.saveCareerLink(normalized),
    onSuccess: () => {
      setTouched(false);
      setSaveError(null);
      showSuccess(link ? "Adres zapisany." : "Link utworzony.");
      qc.invalidateQueries({ queryKey: careerLinkQueryKey() });
    },
    onError: (err) => setSaveError(apiErrorMessage(err, "Nie udało się zapisać adresu.")),
  });

  const disableMutation = useMutation({
    mutationFn: careerLinksApi.disableCareerLink,
    onSuccess: () => {
      setConfirmDisable(false);
      setTouched(false);
      showSuccess("Link wyłączony.");
      qc.invalidateQueries({ queryKey: careerLinkQueryKey() });
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się wyłączyć linku.")),
  });

  const visibilityMutation = useMutation({
    mutationFn: ({ jobId, show }: { jobId: number; show: boolean }) =>
      careerLinksApi.setVisibility(jobId, show),
    onSuccess: () => qc.invalidateQueries({ queryKey: careerLinkQueryKey() }),
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się zmienić widoczności rekrutacji.")),
  });

  const handleCopy = async () => {
    if (!link) return;
    const ok = await copyTextToClipboard(link.public_url);
    if (ok) showSuccess("Skopiowano link.");
    else showError("Nie udało się skopiować — zaznacz adres i skopiuj ręcznie.");
  };

  const state = resolveViewState({
    isLoading: careerQuery.isLoading,
    isError: careerQuery.isError,
    error: careerQuery.error,
    isSuccess: careerQuery.isSuccess,
  });

  const host = hostFromUrl(link?.public_url);
  const jobs = data?.jobs ?? [];

  return (
    <DialogBody className="space-y-6">
      {state === "loading" ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Wczytuję Twój link…
        </div>
      ) : state !== "ready" ? (
        <QueryStateNotice
          state={state === "forbidden" ? "forbidden" : "error"}
          description="Nie udało się wczytać Twojego linku ogólnego. To nie znaczy, że go nie masz."
          onRetry={() => careerQuery.refetch()}
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <div className="space-y-6">
            <section className="space-y-2">
              <label
                htmlFor="career-slug"
                className="text-sm font-semibold text-foreground"
              >
                Twój adres
              </label>
              <div className="flex h-10 items-stretch overflow-hidden rounded-md border border-border bg-card focus-within:ring-2 focus-within:ring-ring">
                <span className="flex items-center border-r border-border bg-muted px-3 font-mono text-xs text-muted-foreground">
                  {host}/
                </span>
                <input
                  id="career-slug"
                  value={slug}
                  onChange={(e) => {
                    setTouched(true);
                    setSaveError(null);
                    setSlug(e.target.value);
                  }}
                  maxLength={40}
                  spellCheck={false}
                  autoComplete="off"
                  className="min-w-0 flex-1 bg-transparent px-3 font-mono text-sm text-foreground outline-hidden"
                  aria-describedby="career-slug-status"
                />
              </div>
              <p
                id="career-slug-status"
                aria-live="polite"
                className={
                  slugMessage?.tone === "ok"
                    ? "text-xs text-success-muted-foreground"
                    : slugMessage?.tone === "bad"
                      ? "text-xs text-destructive"
                      : "text-xs text-muted-foreground"
                }
              >
                {slugMessage?.text ?? ""}
              </p>
              {saveError ? (
                <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  {saveError}
                </p>
              ) : null}

              <div className="flex flex-wrap gap-2 pt-1">
                {!link || !isCurrent ? (
                  <Button
                    onClick={() => saveMutation.mutate()}
                    disabled={!canSave || saveMutation.isPending}
                    loading={saveMutation.isPending}
                  >
                    {link ? "Zapisz adres" : "Utwórz link"}
                  </Button>
                ) : null}
                {link ? (
                  <>
                    <Button variant={isCurrent ? "primary" : "outline"} onClick={handleCopy}>
                      <Copy className="h-3.5 w-3.5" aria-hidden="true" /> Kopiuj link
                    </Button>
                    <Button variant="outline" asChild>
                      <a href={link.public_url} target="_blank" rel="noopener noreferrer">
                        Otwórz stronę
                      </a>
                    </Button>
                    {!confirmDisable ? (
                      <Button variant="ghost" onClick={() => setConfirmDisable(true)}>
                        <PowerOff className="h-3.5 w-3.5" aria-hidden="true" /> Wyłącz link
                      </Button>
                    ) : null}
                  </>
                ) : null}
              </div>

              {link && confirmDisable ? (
                <div
                  role="alertdialog"
                  aria-label="Potwierdź wyłączenie linku"
                  className="space-y-2 rounded-lg border border-destructive/20 bg-destructive-muted p-3 text-sm text-destructive-muted-foreground"
                >
                  <p>
                    Na pewno wyłączyć link? Adres przestanie działać od razu, a posty z tym
                    linkiem zaprowadzą kandydatów donikąd.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => disableMutation.mutate()}
                      loading={disableMutation.isPending}
                      disabled={disableMutation.isPending}
                    >
                      Tak, wyłącz link
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setConfirmDisable(false)}>
                      Anuluj
                    </Button>
                  </div>
                </div>
              ) : null}
            </section>

            <section className="space-y-2" aria-labelledby="general-stats-heading">
              <h3 id="general-stats-heading" className="text-sm font-semibold text-foreground">
                Ostatnie {data?.stats?.days ?? 30} dni
              </h3>
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Wejścia" value={link?.visit_count} />
                <Stat label="Zgłoszenia" value={data?.stats?.applications} />
                <Stat label="Nowi w bazie" value={data?.stats?.new_candidates} />
              </div>
            </section>

            <section className="space-y-1" aria-labelledby="general-jobs-heading">
              <h3 id="general-jobs-heading" className="text-sm font-semibold text-foreground">
                Rekrutacje widoczne na Twojej stronie
              </h3>
              <p className="text-xs text-muted-foreground">
                Tylko otwarte, z zatwierdzonym opisem publicznym.
              </p>
              {jobs.length === 0 ? (
                <p className="py-3 text-sm text-muted-foreground">
                  Nie masz jeszcze aktywnych linków do otwartych rekrutacji — utwórz je
                  w zakładce „Link do tej rekrutacji”.
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {jobs.map((job) => (
                    <VisibilityRow
                      key={job.job_id}
                      job={job}
                      pending={visibilityMutation.isPending}
                      onToggle={(show) => visibilityMutation.mutate({ jobId: job.job_id, show })}
                    />
                  ))}
                </ul>
              )}
            </section>
          </div>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <span className="text-sm font-medium text-foreground">Podgląd posta na LinkedInie</span>
              <LinkedInPreviewCard
                command={`whoami — ${firstName.toLowerCase()}@dynaminds`}
                headline="Szukasz kolejnego projektu IT?"
                tagline="[zostaw CV · odezwę się z konkretem]"
                cardTitle={`${firstName} — rekrutacja IT · Dynaminds`}
                host={host}
              />
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Kandydaci z tego linku trafiają do bazy przypisani do Ciebie i pojawiają się
              w „Moich ludziach”. Nowe CV od razu przechodzi dopasowanie do otwartych
              rekrutacji.
            </p>
          </div>
        </div>
      )}

      <InviteLinkHistory enabled={enabled} />
    </DialogBody>
  );
}
