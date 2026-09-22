"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Loader2, Trash2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  careerLinksApi,
  inviteLinksQueryKey,
  useInviteLinks,
} from "@/lib/api/careerLinks";
import { copyTextToClipboard } from "@/lib/clipboard";
import { resolveViewState } from "@/lib/view-state";

import {
  INVITE_STATUS_LABEL,
  INVITE_STATUS_VARIANT,
  formatDate,
  isLinkLive,
  linkUrl,
} from "./share-utils";

/** „Historia linków" — linki do rekrutacji tej osoby, z możliwością wycofania. */
export function InviteLinkHistory({ enabled }: { enabled: boolean }) {
  const qc = useQueryClient();
  const { showSuccess, showError } = useToast();
  const linksQuery = useInviteLinks(enabled);
  const links = linksQuery.data ?? [];

  const revoke = useMutation({
    mutationFn: careerLinksApi.revokeInviteLink,
    onSuccess: () => {
      showSuccess("Link wycofany.");
      qc.invalidateQueries({ queryKey: inviteLinksQueryKey() });
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się wycofać linku.")),
  });

  const handleCopy = async (url: string) => {
    const ok = await copyTextToClipboard(url);
    if (ok) showSuccess("Skopiowano link.");
    else showError("Nie udało się skopiować — zaznacz adres i skopiuj ręcznie.");
  };

  const state = resolveViewState({
    isLoading: linksQuery.isLoading,
    isError: linksQuery.isError,
    error: linksQuery.error,
    isSuccess: linksQuery.isSuccess,
    isEmpty: links.length === 0,
  });

  return (
    <section className="space-y-2" aria-labelledby="career-history-heading">
      <h3 id="career-history-heading" className="text-sm font-semibold text-foreground">
        Historia linków
      </h3>
      {state === "loading" ? (
        <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Ładowanie…
        </div>
      ) : state === "forbidden" || state === "error" || state === "not_found" ? (
        <QueryStateNotice
          state={state === "not_found" ? "error" : state}
          description="Nie udało się pobrać historii linków. To nie znaczy, że jej nie masz."
          onRetry={() => linksQuery.refetch()}
        />
      ) : state === "empty" ? (
        <p className="py-3 text-sm text-muted-foreground">
          Nie masz jeszcze żadnych linków do rekrutacji.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {links.map((link) => {
            const live = isLinkLive(link);
            return (
              <li key={link.token} className="flex items-center gap-3 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-medium text-foreground">
                      {link.job?.title ?? "Rekrutacja"}
                    </span>
                    <Badge size="sm" variant={INVITE_STATUS_VARIANT[link.status]}>
                      {INVITE_STATUS_LABEL[link.status]}
                    </Badge>
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {link.label ? `${link.label} · ` : ""}
                    Utworzony {formatDate(link.created_at)} ·{" "}
                    {link.expires_at
                      ? `ważny do ${formatDate(link.expires_at)}`
                      : "do zamknięcia rekrutacji"}
                    {` · ${link.use_count} zgłoszeń`}
                  </div>
                </div>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => handleCopy(linkUrl(link))}
                  disabled={!live}
                  aria-label={`Kopiuj link: ${link.job?.title ?? "rekrutacja"}`}
                  title="Kopiuj link"
                >
                  <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => revoke.mutate(link.token)}
                  disabled={!live || revoke.isPending}
                  aria-label={`Wycofaj link: ${link.job?.title ?? "rekrutacja"}`}
                  title="Wycofaj link"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
