"use client";

import { useEffect, useMemo, useState } from"react";
import {
 useMutation,
 useQuery,
 useQueryClient,
} from"@tanstack/react-query";
import {
 AlertCircle,
 CheckCircle2,
 Copy,
 Link as LinkIcon,
 Loader2,
 Trash2,
} from"lucide-react";
import api from"@/lib/api";
import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { FormField } from"@/components/ui/form-field";
import { Input } from"@/components/ui/input";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { RadioGroup, RadioGroupItem } from"@/components/ui/radio-group";
import { Tabs, TabsContent, TabsList, TabsTrigger } from"@/components/ui/tabs";
import { Badge } from"@/components/ui/badge";

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 /**
 * Optional pre-selected job ID. When passed, the job select is initialised
 * with this value (e.g. when the modal is opened from a job detail page).
 * Users can still change it before generating the link.
 */
 defaultJobId?: number;
}

interface JobLite {
 id: number;
 title: string;
 status?: string;
}

type InviteStatus ="active" |"used" |"revoked" |"expired";

interface InviteLink {
 token: string;
 url: string;
 job: { id: number; title: string };
 label: string | null;
 expires_at: string;
 revoked: boolean;
 use_count: number;
 last_used_at: string | null;
 created_at: string;
 status: InviteStatus;
}

const EXPIRY_OPTIONS = [
 { value: 7, label: "7 dni" },
 { value: 14, label: "14 dni" },
 { value: 30, label: "30 dni" },
 { value: 90, label: "90 dni" },
] as const;

const STATUS_LABEL: Record<InviteStatus, string> = {
 active: "Aktywny",
 used: "Używany",
 revoked: "Wycofany",
 expired: "Wygasł",
};

const STATUS_VARIANT: Record<
 InviteStatus, "success" |"soft" |"neutral" |"danger"
> = {
 active: "success",
 used: "soft",
 revoked: "danger",
 expired: "neutral",
};

function formatDate(iso: string) {
 return new Date(iso).toLocaleDateString("pl-PL", {
 day: "2-digit",
 month: "short",
 year: "numeric",
 });
}

export function GenerateInviteLinkV2({
 open,
 onOpenChange,
 defaultJobId,
}: Props) {
 const qc = useQueryClient();
 const [activeTab, setActiveTab] = useState<"create" |"history">("create");

 // Create-tab state
 const [jobId, setJobId] = useState<string>(
 defaultJobId ? String(defaultJobId) :""
 );
 const [label, setLabel] = useState("");
 const [expiresInDays, setExpiresInDays] = useState<7 | 14 | 30 | 90>(30);
 const [result, setResult] = useState<InviteLink | null>(null);
 const [copied, setCopied] = useState(false);
 const [formError, setFormError] = useState<string | null>(null);

 useEffect(() => {
 if (!open) {
 setJobId(defaultJobId ? String(defaultJobId) :"");
 setLabel("");
 setExpiresInDays(30);
 setResult(null);
 setCopied(false);
 setFormError(null);
 setActiveTab("create");
 } else if (defaultJobId) {
 setJobId(String(defaultJobId));
 }
 }, [open, defaultJobId]);

 const jobsQuery = useQuery<JobLite[]>({
 queryKey: ["jobs","published"],
 queryFn: async () => {
 const res = await api.get("/api/jobs", {
 params: { status: "published", page_size: 100 },
 });
 const data = res.data;
 // jobs endpoint can return either {items: [...]} or raw array — normalize.
 const items: JobLite[] = Array.isArray(data)
 ? data
 : (data.items ?? []);
 return items;
 },
 enabled: open,
 staleTime: 30_000,
 });

 const linksQuery = useQuery<InviteLink[]>({
 queryKey: ["invite-links","mine"],
 queryFn: async () => {
 const res = await api.get("/api/invite-links", {
 params: { mine: true },
 });
 return res.data as InviteLink[];
 },
 enabled: open && activeTab ==="history",
 });

 const createMutation = useMutation({
 mutationFn: async (payload: {
 job_id: number;
 label?: string;
 expires_in_days: number;
 }) => {
 const res = await api.post("/api/invite-links", payload);
 return res.data as InviteLink;
 },
 onSuccess: (link) => {
 setResult(link);
 setFormError(null);
 qc.invalidateQueries({ queryKey: ["invite-links","mine"] });
 },
 onError: (err: unknown) => {
 const msg =
 (err as { response?: { data?: { detail?: string } } })?.response?.data
 ?.detail ??"Nie udało się wygenerować linku. Spróbuj ponownie.";
 setFormError(msg);
 },
 });

 const revokeMutation = useMutation({
 mutationFn: async (token: string) => {
 await api.post(`/api/invite-links/${token}/revoke`);
 return token;
 },
 onSuccess: () => {
 qc.invalidateQueries({ queryKey: ["invite-links","mine"] });
 },
 });

 const handleGenerate = () => {
 if (!jobId) {
 setFormError("Wybierz stanowisko.");
 return;
 }
 setResult(null);
 setFormError(null);
 createMutation.mutate({
 job_id: Number(jobId),
 label: label.trim() || undefined,
 expires_in_days: expiresInDays,
 });
 };

 const handleCopy = async (url: string) => {
 try {
 await navigator.clipboard.writeText(url);
 setCopied(true);
 setTimeout(() => setCopied(false), 2_500);
 } catch {
 // ignore — user can copy manually
 }
 };

 const publishedJobs = useMemo(
 () => (jobsQuery.data ?? []).filter((j) => !j.status || j.status ==="published"),
 [jobsQuery.data]
 );

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="lg">
 <DialogHeader>
 <DialogTitle className="flex items-center gap-2">
 <LinkIcon className="h-5 w-5 text-primary" />
 Linki aplikacyjne
 </DialogTitle>
 <DialogDescription>
 Wygeneruj link dla kandydata. Każda aplikacja przez ten link będzie
 przypisana do Ciebie.
 </DialogDescription>
 </DialogHeader>

 <DialogBody>
 <Tabs
 value={activeTab}
 onValueChange={(v) => setActiveTab(v as"create" |"history")}
 >
 <TabsList>
 <TabsTrigger value="create">Nowy link</TabsTrigger>
 <TabsTrigger value="history">Moje linki</TabsTrigger>
 </TabsList>

 <TabsContent value="create">
 {!result ? (
 <div className="space-y-4">
 <FormField label="Stanowisko" required>
 <Select
 value={jobId}
 onValueChange={(v) => setJobId(v)}
 disabled={jobsQuery.isLoading}
 >
 <SelectTrigger>
 <SelectValue
 placeholder={
 jobsQuery.isLoading
 ?"Ładowanie…"
 : publishedJobs.length === 0
 ?"Brak opublikowanych stanowisk"
 :"Wybierz stanowisko"
 }
 />
 </SelectTrigger>
 <SelectContent>
 {publishedJobs.map((j) => (
 <SelectItem key={j.id} value={String(j.id)}>
 {j.title}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 </FormField>

 <FormField
 label="Etykieta (opcjonalnie)"
 description={`Prywatna notatka, np. „LinkedIn post 04/26".`}
 >
 <Input
 value={label}
 onChange={(e) => setLabel(e.target.value)}
 maxLength={120}
 placeholder="LinkedIn, Facebook, konferencja…"
 />
 </FormField>

 <FormField label="Ważność linku">
 <RadioGroup
 className="grid grid-cols-4 gap-2"
 value={String(expiresInDays)}
 onValueChange={(v) =>
 setExpiresInDays(Number(v) as 7 | 14 | 30 | 90)
 }
 >
 {EXPIRY_OPTIONS.map((opt) => (
 <label
 key={opt.value}
 className={`flex items-center justify-center gap-2 rounded-md border px-3 py-2 cursor-pointer text-sm ${
 expiresInDays === opt.value
 ?"border-primary bg-primary/5 text-foreground"
 :"border-border text-muted-foreground"
 }`}
 >
 <RadioGroupItem
 value={String(opt.value)}
 className="sr-only"
 />
 {opt.label}
 </label>
 ))}
 </RadioGroup>
 </FormField>

 {formError && (
 <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
 <AlertCircle className="h-4 w-4" />
 {formError}
 </div>
 )}

 <Button
 type="button"
 variant="primary"
 className="w-full"
 onClick={handleGenerate}
 disabled={createMutation.isPending || !jobId}
 >
 {createMutation.isPending ? (
 <>
 <Loader2 className="h-4 w-4 animate-spin" />
 Generowanie…
 </>
 ) : ("Wygeneruj link"
 )}
 </Button>
 </div>
 ) : (
 <div className="space-y-4">
 <div className="flex items-center gap-2 text-sm text-foreground">
 <CheckCircle2 className="h-4 w-4 text-green-600" />
 Link gotowy — skopiuj i wyślij kandydatowi.
 </div>
 <div className="rounded-md border border-border bg-background/40 p-3 space-y-2">
 <div className="text-xs uppercase tracking-wider text-muted-foreground">
 URL
 </div>
 <div className="flex items-center gap-2">
 <code className="flex-1 text-xs font-mono break-all">
 {result.url}
 </code>
 <Button
 size="sm"
 variant="outline"
 onClick={() => handleCopy(result.url)}
 >
 <Copy className="h-3.5 w-3.5" />
 {copied ?"Skopiowano" :"Kopiuj"}
 </Button>
 </div>
 <div className="text-[11px] text-muted-foreground">
 Stanowisko: <strong>{result.job.title}</strong> · Ważny do{""}
 {formatDate(result.expires_at)}
 </div>
 </div>
 <div className="flex justify-between">
 <Button
 variant="ghost"
 onClick={() => {
 setResult(null);
 setLabel("");
 }}
 >
 Generuj kolejny
 </Button>
 <Button
 variant="outline"
 onClick={() => onOpenChange(false)}
 >
 Zamknij
 </Button>
 </div>
 </div>
 )}
 </TabsContent>

 <TabsContent value="history">
 {linksQuery.isLoading ? (
 <div className="py-10 flex items-center justify-center text-sm text-muted-foreground">
 <Loader2 className="h-4 w-4 animate-spin mr-2" /> Ładowanie…
 </div>
 ) : (linksQuery.data ?? []).length === 0 ? (
 <div className="py-10 text-center text-sm text-muted-foreground">
 Nie wygenerowałeś jeszcze żadnego linku aplikacyjnego.
 </div>
 ) : (
 <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
 {(linksQuery.data ?? []).map((link) => (
 <div
 key={link.token}
 className="rounded-md border border-border bg-card p-3 space-y-1.5"
 >
 <div className="flex items-center justify-between gap-3">
 <div className="min-w-0 flex-1">
 <div className="flex items-center gap-2 flex-wrap">
 <span className="font-semibold text-sm text-foreground truncate">
 {link.job.title}
 </span>
 <Badge variant={STATUS_VARIANT[link.status]}>
 {STATUS_LABEL[link.status]}
 </Badge>
 {link.use_count > 0 && (
 <span className="text-xs text-muted-foreground">
 · {link.use_count} aplikacji
 </span>
 )}
 </div>
 {link.label && (
 <div className="text-xs text-muted-foreground mt-0.5">
 {link.label}
 </div>
 )}
 <div className="text-[11px] text-muted-foreground mt-1">
 Utworzony {formatDate(link.created_at)} · Ważny do{""}
 {formatDate(link.expires_at)}
 </div>
 </div>
 <div className="flex items-center gap-1 shrink-0">
 <Button
 size="sm"
 variant="outline"
 onClick={() => handleCopy(link.url)}
 disabled={link.status !=="active" && link.status !=="used"}
 >
 <Copy className="h-3.5 w-3.5" />
 </Button>
 <Button
 size="sm"
 variant="ghost"
 onClick={() => revokeMutation.mutate(link.token)}
 disabled={
 link.revoked ||
 link.status ==="expired" ||
 revokeMutation.isPending
 }
 title="Wycofaj link"
 >
 <Trash2 className="h-3.5 w-3.5" />
 </Button>
 </div>
 </div>
 </div>
 ))}
 </div>
 )}
 </TabsContent>
 </Tabs>
 </DialogBody>
 </DialogContent>
 </Dialog>
 );
}
