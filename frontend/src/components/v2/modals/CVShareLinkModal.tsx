"use client";

/**
 * CVShareLinkModal – generuje token-link do brandowanego CV i pokazuje URL
 * gotowy do skopiowania. Klient otwiera link bez logowania.
 *
 * PR2 – Faza 5. Wymaga że brandowane CV jest sfinalizowane (status='finalized').
 * Backend zwraca 409 inaczej.
 */

import { useState, useEffect } from"react";
import { useMutation } from"@tanstack/react-query";
import { Check, Copy, Link2, Loader2, AlertCircle, X } from"lucide-react";

import { Dialog, DialogContent } from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { Label } from"@/components/ui/label";
import { Input } from"@/components/ui/input";
import { useToast } from"@/components/Toast";
import {
 candidateStageCvApi,
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
 const [days, setDays] = useState<number>(30);
 const [token, setToken] = useState<CVShareTokenResp | null>(null);
 const [errorMsg, setErrorMsg] = useState<string | null>(null);
 const [copied, setCopied] = useState(false);

 // Reset state when modal opens
 useEffect(() => {
 if (open) {
 setToken(null);
 setErrorMsg(null);
 setCopied(false);
 setDays(30);
 }
 }, [open]);

 const createMut = useMutation({
 mutationFn: () => candidateStageCvApi.share.create(stageId, days),
 onSuccess: (res) => {
 setToken(res.data);
 setErrorMsg(null);
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
 onChange={(e) => setDays(parseInt(e.target.value) || 30)}
 min={1}
 max={365}
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
 Aktywny do {expiresLabel}
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
 </div>
 </DialogContent>
 </Dialog>
 );
}
