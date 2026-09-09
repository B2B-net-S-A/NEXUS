"use client";

/**
 * Udostępnianie WYGENEROWANEGO CV (Generator B2B) hiring managerowi.
 *
 * Mirror wzorca CVShareLinkModal (brandowane CV): token pokazywany JEDEN raz
 * (w DB tylko SHA-256), potem zarządzanie wyłącznie po revoke-key. Link
 * prowadzi na `/cv/i/{token}` — stronę z widokiem classic + interaktywnym
 * (kafelki wymagań + chat, jeśli dostępne dla tego CV/klienta).
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, Copy, Link2, Loader2, Sparkles } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/Toast";
import {
  cvGeneratedShareApi,
  type CvGeneratedShareCreateResp,
  type CvGeneratedShareListItem,
} from "@/lib/api";

type Props = {
  generatedId: number | null;
  candidateName?: string;
  onClose: () => void;
};

function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pl-PL", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function CvGeneratedShareModal(props: Props) {
  return <CvGeneratedShareModalContent key={props.generatedId ?? "closed"} {...props} />;
}

function CvGeneratedShareModalContent({
  generatedId,
  candidateName,
  onClose,
}: Props) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [days, setDays] = useState(14);
  const [maxViews, setMaxViews] = useState<string>("");
  const [created, setCreated] = useState<CvGeneratedShareCreateResp | null>(
    null,
  );
  const [copied, setCopied] = useState(false);

  const open = generatedId !== null;
  const [selectedVersion, setSelectedVersion] = useState("");
  useEffect(() => {
    setSelectedVersion("");
    setCreated(null);
    setCopied(false);
  }, [generatedId]);
  const versionsQuery = useQuery({
    queryKey: ["cv-generated-approved-versions", generatedId],
    queryFn: () => cvGeneratedShareApi.approvedVersions(generatedId as number).then(r => r.data),
    enabled: open,
  });
  const selected = versionsQuery.data?.find(v => String(v.id) === selectedVersion);


  const tokensQuery = useQuery({
    queryKey: ["cv-generated-share-tokens", generatedId],
    queryFn: () =>
      cvGeneratedShareApi.list(generatedId as number).then((r) => r.data),
    enabled: open,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("Wybierz zatwierdzoną wersję CV.");
      return cvGeneratedShareApi.create(
        generatedId as number,
        days,
        maxViews ? Number(maxViews) : undefined,
        selected.id,
      );
    },
    onSuccess: (res) => {
      setCreated(res.data);
      setCopied(false);
      void queryClient.invalidateQueries({
        queryKey: ["cv-generated-share-tokens", generatedId],
      });
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      showToast(detail ?? "Nie udało się utworzyć linku", "error");
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (revokeKey: string) => cvGeneratedShareApi.revoke(revokeKey),
    onSuccess: () => {
      showToast("Link odwołany", "success");
      void queryClient.invalidateQueries({
        queryKey: ["cv-generated-share-tokens", generatedId],
      });
    },
    onError: () => showToast("Nie udało się odwołać linku", "error"),
  });

  const shareUrl = created
    ? `${window.location.origin}${created.share_url_suffix}`
    : null;

  async function copyLink() {
    if (!shareUrl) return;
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    showToast("Link skopiowany do schowka", "success");
  }

  function handleClose() {
    setCreated(null);
    setCopied(false);
    onClose();
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            Udostępnij CV klientowi
            {candidateName ? (
              <span className="font-normal text-muted-foreground">
                · {candidateName}
              </span>
            ) : null}
          </DialogTitle>
        </DialogHeader>

        {/* Formularz tworzenia */}
        {!created && (
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="cvi-version">Zatwierdzona wersja CV</Label>
              <select id="cvi-version" value={selectedVersion}
                onChange={e => setSelectedVersion(e.target.value)}
                disabled={versionsQuery.isLoading || versionsQuery.isError}
                className="w-full rounded-md border border-border bg-background p-2 text-sm">
                <option value="">Wybierz wersję</option>
                {versionsQuery.data?.map(v => (
                  <option key={v.id} value={String(v.id)}>
                    Wersja {v.version} · {v.language?.toUpperCase()} · {formatDate(v.approved_at)} · {v.job_title}
                  </option>
                ))}
              </select>
              {versionsQuery.isError ? (
                <p role="alert" className="text-sm text-destructive">Nie udało się pobrać wersji. <button type="button" className="underline" onClick={() => versionsQuery.refetch()}>Spróbuj ponownie</button></p>
              ) : !versionsQuery.isLoading && !versionsQuery.data?.length ? (
                <p className="text-sm text-muted-foreground">Brak zatwierdzonych wersji. Zatwierdź to CV w procesie rekrutacyjnym przed utworzeniem linku.</p>
              ) : null}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="cvi-days">Ważność (dni)</Label>
                <Input
                  id="cvi-days"
                  type="number"
                  min={1}
                  max={90}
                  value={days}
                  onChange={(e) =>
                    setDays(
                      Math.min(90, Math.max(1, Number(e.target.value) || 14)),
                    )
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="cvi-views">Limit wyświetleń</Label>
                <Input
                  id="cvi-views"
                  type="number"
                  min={1}
                  max={1000}
                  placeholder="bez limitu"
                  value={maxViews}
                  onChange={(e) => setMaxViews(e.target.value)}
                />
              </div>
            </div>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending || !selected}
              className="w-full"
            >
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Link2 className="h-4 w-4" />
              )}
              Wygeneruj link
            </Button>
          </div>
        )}

        {/* Świeżo utworzony link — sekret widoczny JEDEN raz */}
        {created && shareUrl && (
          <div className="space-y-3">
            <Alert variant="success" className="text-sm">
              Link utworzony. Skopiuj go teraz — ze względów bezpieczeństwa nie
              da się go ponownie wyświetlić (można go tylko odwołać).
            </Alert>
            <div className="flex items-center gap-2">
              <Input readOnly value={shareUrl} className="font-mono text-xs" />
              <Button variant="outline" size="sm" onClick={copyLink}>
                {copied ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
            {created.interactive_available ? (
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                Klient zobaczy wersję interaktywną (kafelki wymagań
                {" + chat"}) z przełącznikiem na widok klasyczny.
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Klient zobaczy klasyczny widok CV (wersja interaktywna
                niedostępna dla tego CV).
              </p>
            )}
            <Button
              variant="outline"
              className="w-full"
              onClick={() => setCreated(null)}
            >
              Wygeneruj kolejny link
            </Button>
          </div>
        )}

        {/* Istniejące linki */}
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Aktywne i odwołane linki
          </p>
          {tokensQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Ładowanie…</p>
          ) : !tokensQuery.data?.length ? (
            <p className="text-sm text-muted-foreground">
              Brak linków dla tego CV.
            </p>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border">
              {tokensQuery.data.map((tok: CvGeneratedShareListItem) => (
                <li
                  key={tok.revoke_key}
                  className="flex items-center justify-between gap-2 px-3 py-2"
                >
                  <div className="min-w-0 text-xs">
                    <p className="font-mono truncate">{tok.token_preview}</p>
                    <p className="text-muted-foreground">
                      do {formatDate(tok.expires_at)} · {tok.view_count}
                      {tok.max_views ? `/${tok.max_views}` : ""} wyświetleń
                      {tok.created_by_name ? ` · ${tok.created_by_name}` : ""}
                    </p>
                  </div>
                  {tok.revoked ? (
                    <Badge variant="outline">odwołany</Badge>
                  ) : (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => revokeMutation.mutate(tok.revoke_key)}
                      disabled={revokeMutation.isPending}
                      title="Odwołaj link"
                    >
                      <Ban className="h-4 w-4" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
