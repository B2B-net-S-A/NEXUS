"use client";

/**
 * CVShareLinkModal — generuje token-link do brandowanego CV i pokazuje URL
 * gotowy do skopiowania. Klient otwiera link bez logowania.
 *
 * PR2 — Faza 5. Wymaga że brandowane CV jest sfinalizowane (status='finalized').
 * Backend zwraca 409 inaczej.
 */

import { useState, useEffect } from"react";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { Check, Copy, Link2, Loader2, AlertCircle, X } from"lucide-react";

import { Dialog, DialogContent } from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { Label } from"@/components/ui/label";
import { Input } from"@/components/ui/input";
import { useToast } from"@/components/Toast";
import {
 candidateStageCvApi,
 type CVShareTokenListItem,
 type CVShareTokenResp,
} from"@/lib/api";

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 stageId: number;
 candidateName: string;
}

function getErrorMessage(e: unknown): string {
 return (
 (e as { response?: { data?: { detail?: string } } })?.response?.data
 ?.detail ??"Nie udało się wygenerować linku."
 );
}

export function CVShareLinkModal({
 open,
 onOpenChange,
 stageId,
 candidateName,
}: Props) {
 const { showSuccess, showError } = useToast();
 const queryClient = useQueryClient();
 const [days, setDays] = useState<number>(14);
 const [token, setToken] = useState<CVShareTokenResp | null>(null);
 const [errorMsg, setErrorMsg] = useState<string | null>(null);
 const [copied, setCopied] = useState(false);

 // Reset state when modal opens
 useEffect(() => {
 if (open) {
 setToken(null);
 setErrorMsg(null);
 setCopied(false);
 setDays(14);
 }
 }, [open]);

 const linksQuery = useQuery({
 queryKey: ["cv-share-tokens", stageId],
 queryFn: async () => (await candidateStageCvApi.share.list(stageId)).data,
 enabled: open,
 });
 const activeLinks = (linksQuery.data ?? []).filter((l) => !l.revoked);

 const revokeByKeyMut = useMutation({
 mutationFn: (key: string) => candidateStageCvApi.share.revoke(key),
 onSuccess: () => {
 showSuccess("Link odwołany");
 queryClient.invalidateQueries({ queryKey: ["cv-share-tokens", stageId] });
 },
 onError: (e) => showError(getErrorMessage(e)),
 });

 const createMut = useMutation({
 mutationFn: () => candidateStageCvApi.share.create(stageId, days),
 onSuccess: (res) => {
 setToken(res.data);
 setErrorMsg(null);
 queryClient.invalidateQueries({ queryKey: ["cv-share-tokens", stageId] });
 },
 onError: (e) => {
 const msg = getErrorMessage(e);
 setErrorMsg(msg);
 showError(msg);
 },
 });

 const revokeMut = useMutation({
 mutationFn: (tk: string) => candidateStageCvApi.share.revoke(tk),
 onSuccess: () => {
 showSuccess("Link odwołany");
 setToken(null);
 queryClient.invalidateQueries({ queryKey: ["cv-share-tokens", stageId] });
 },
 onError: (e) => showError(getErrorMessage(e)),
 });

 const fullUrl = token
 ? `${typeof window !== "undefined" ? window.location.origin : ""}${
 token.share_url_suffix
 }`
 :"";

 const onCopy = async () => {
 if (!fullUrl) return;
 try {
 await navigator.clipboard.writeText(fullUrl);
 setCopied(true);
 showSuccess("Link skopiowany do schowka");
 setTimeout(() => setCopied(false), 2000);
 } catch {
 showError("Nie udało się skopiować linku");
 }
 };

 const expiresLabel = token?.expires_at
 ? new Date(token.expires_at).toLocaleDateString("pl-PL", {
 day: "numeric",
 month: "long",
 year: "numeric",
 })
 : null;

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="lg" className="p-0">
 <div className="px-5 py-4 border-b border-border">
 <div className="text-xs uppercase tracking-wider text-muted-foreground">
 Wyślij CV klientowi
 </div>
 <div className="text-sm font-medium text-foreground mt-0.5">
 {candidateName}
 </div>
 </div>

 <div className="p-5 space-y-4">
 {!token ? (
 <>
 <div>
 <Label htmlFor="cv-share-days" className="text-xs">
 Czas ważności linku
 </Label>
 <div className="flex items-center gap-2 mt-1">
 <Input
 id="cv-share-days"
 type="number"
 value={days}
 onChange={(e) => setDays(parseInt(e.target.value) || 14)}
 min={1}
 max={90}
 className="w-24"
 />
 <span className="text-sm text-muted-foreground">
 dni
 </span>
 </div>
 </div>

 {errorMsg ? (
 <div className="rounded-lg border border-destructive/20 bg-destructive/10 dark:border-red-900 dark:bg-red-950 px-3 py-2 text-xs text-destructive dark:text-red-300 flex items-start gap-2">
 <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
 <span>{errorMsg}</span>
 </div>
 ) : null}

 <Button
 onClick={() => createMut.mutate()}
 disabled={createMut.isPending}
 className="w-full"
 >
 {createMut.isPending ? (
 <Loader2 className="h-4 w-4 mr-2 animate-spin" />
 ) : (
 <Link2 className="h-4 w-4 mr-2" />
 )}
 Wygeneruj link
 </Button>
 </>
 ) : (
 <>
 <div>
 <Label className="text-xs">Link dla klienta</Label>
 <div className="flex items-center gap-2 mt-1">
 <Input
 readOnly
 value={fullUrl}
 onFocus={(e) => e.currentTarget.select()}
 className="font-mono text-xs"
 />
 <Button onClick={onCopy} variant="outline" size="sm">
 {copied ? (
 <Check className="h-3.5 w-3.5" />
 ) : (
 <Copy className="h-3.5 w-3.5" />
 )}
 </Button>
 </div>
 {expiresLabel ? (
 <p className="text-[11px] text-muted-foreground mt-1.5">
 Aktywny do {expiresLabel}. Skopiuj teraz — ze względów
 bezpieczeństwa link nie jest przechowywany i nie da się go
 ponownie wyświetlić (można go tylko odwołać).
 </p>
 ) : null}
 </div>

 <div className="flex items-center justify-between gap-2 pt-2 border-t border-border">
 <Button
 variant="ghost"
 size="sm"
 onClick={() => revokeMut.mutate(token.token)}
 disabled={revokeMut.isPending}
 className="text-destructive hover:text-destructive"
 >
 <X className="h-3.5 w-3.5 mr-1.5" />
 Cofnij udostępnienie
 </Button>
 <Button
 variant="outline"
 size="sm"
 onClick={() => onOpenChange(false)}
 >
 Zamknij
 </Button>
 </div>
 </>
 )}
 <ActiveLinksSection
 links={activeLinks}
 loading={linksQuery.isLoading}
 error={linksQuery.isError}
 onRevoke={(key) => revokeByKeyMut.mutate(key)}
 revoking={revokeByKeyMut.isPending}
 />
 </div>
 </DialogContent>
 </Dialog>
 );
}

function ActiveLinksSection({
 links,
 loading,
 error,
 onRevoke,
 revoking,
}: {
 links: CVShareTokenListItem[];
 loading: boolean;
 error: boolean;
 onRevoke: (key: string) => void;
 revoking: boolean;
}) {
 if (loading) {
 return (
 <div className="pt-3 border-t border-border text-xs text-muted-foreground">
 Ładowanie listy linków…
 </div>
 );
 }
 if (error) {
 return (
 <div className="pt-3 border-t border-border text-xs text-destructive">
 Nie udało się pobrać listy linków.
 </div>
 );
 }
 if (links.length === 0) return null;
 return (
 <div className="pt-3 border-t border-border space-y-2">
 <div className="text-xs uppercase tracking-wider text-muted-foreground">
 Aktywne linki ({links.length})
 </div>
 {links.map((l) => (
 <div
 key={l.revoke_key}
 className="flex items-center justify-between gap-2 text-xs"
 >
 <div className="min-w-0">
 <span className="font-mono">{l.token_preview}</span>
 <span className="text-muted-foreground">
 {" "}· {l.view_count}
 {l.max_views ? `/${l.max_views}` : ""} wyśw.
 {l.expires_at
 ? ` · do ${new Date(l.expires_at).toLocaleDateString("pl-PL")}`
 : ""}
 </span>
 </div>
 <Button
 variant="ghost"
 size="sm"
 disabled={revoking}
 onClick={() => onRevoke(l.revoke_key)}
 className="h-6 px-2 text-destructive hover:text-destructive"
 >
 <X className="h-3 w-3 mr-1" />
 Odwołaj
 </Button>
 </div>
 ))}
 </div>
 );
}
