"use client";

import * as React from"react";
import { useMutation } from"@tanstack/react-query";
import { CheckCircle2 } from"lucide-react";
import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { Input } from"@/components/ui/input";
import { Label } from"@/components/ui/label";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { contractsApi, type ContractorListItem } from"@/lib/api";
import {
 canManageCandidateFinance,
 useAuthStore,
} from"@/store/auth";

interface Props {
 contractor: ContractorListItem;
 open: boolean;
 onOpenChange: (open: boolean) => void;
 onActivated: () => void;
}

interface FormState {
 start_date: string;
 end_date: string;
 rate_candidate: string;
 rate_client: string;
 rate_candidate_currency: string;
 rate_client_currency: string;
 contract_type: "b2b" |"uop" |"uzlecenie";
 work_mode: "" |"remote" |"hybrid" |"onsite";
}

function toFormState(c: ContractorListItem): FormState {
 return {
 start_date: c.start_date ??"",
 end_date: c.end_date ??"",
 rate_candidate: c.rate_candidate != null ? String(c.rate_candidate) : "",
 rate_client: c.rate_client != null ? String(c.rate_client) : "",
 rate_candidate_currency:
 c.rate_candidate_currency ?? c.currency ?? "PLN",
 rate_client_currency: c.rate_client_currency ?? c.currency ?? "PLN",
 contract_type: c.contract_type ??"b2b",
 work_mode: c.work_mode ??"",
 };
}

/**
 * Lustro `ACTIVATION_REQUIRED_FIELDS` (backend/app/services/contract_service.py).
 * `end_date` świadomie POZA listą: umowa bezterminowa to normalny stan
 * body-leasingu, a nie brak danych — wymaganie daty zamykało przycisk
 * „Uzupełnij i aktywuj" na stałe dla kontraktów, których backend już aktywuje.
 */
function formDirtyOrValid(
 form: FormState,
 canManageFinance: boolean
): boolean {
 return Boolean(
 form.start_date &&
 form.contract_type &&
 (!canManageFinance ||
 (form.rate_candidate &&
 form.rate_client &&
 form.rate_candidate_currency &&
 form.rate_client_currency))
 );
}

/**
 * DraftCompletionModal — fills the activation-required fields
 * (start_date, rate_candidate, rate_client, contract_type; work mode and the
 * end date are optional) with one PATCH. The backend automatically activates
 * an incomplete draft when this write closes its last completeness gap. A
 * legacy draft that was already complete still uses the explicit command, so
 * an incidental edit elsewhere cannot become a retroactive status sweep.
 */
export function DraftCompletionModal({
 contractor,
 open,
 onOpenChange,
 onActivated,
}: Props) {
 const user = useAuthStore((state) => state.user);
 const canManageFinance = canManageCandidateFinance(user);
 const needsAdminFinance =
 !canManageFinance &&
 contractor.missing_fields.some((field) =>
 ["rate_candidate","rate_client"].includes(field)
 );
 const [form, setForm] = React.useState<FormState>(() =>
 toFormState(contractor)
 );
 const [error, setError] = React.useState<string | null>(null);

 React.useEffect(() => {
 setForm(toFormState(contractor));
 setError(null);
 }, [contractor]);

 const saveRequiredFields = useMutation({
 mutationFn: async () => {
 const payload: Record<string, unknown> = {
 start_date: form.start_date,
 // Pusty string to nie jest data — backend odrzuciłby go 422.
 // `null` znaczy „bezterminowo" i tak też czyta go bramka aktywacji.
 end_date: form.end_date || null,
 contract_type: form.contract_type,
 work_mode: form.work_mode || null,
 };
 if (canManageFinance) {
 payload.rate_candidate = Number(form.rate_candidate);
 payload.rate_client = Number(form.rate_client);
 payload.rate_candidate_currency = form.rate_candidate_currency;
 payload.rate_client_currency = form.rate_client_currency;
 }
 const response = await contractsApi.update(contractor.contract_id, payload);
 // Normally the PATCH above is the whole transition. A complete legacy draft
 // has no new incomplete→complete edge, so the deliberate click on this modal
 // remains its explicit opt-in to activation. The fallback also keeps a rolling
 // frontend/backend deploy safe while an older API version is still serving.
 if (!needsAdminFinance && response.data?.status === "draft") {
 await contractsApi.activate(contractor.contract_id);
 }
 },
 onSuccess: () => {
 onActivated();
 },
 onError: (err: unknown) => {
 const axiosErr = err as {
 response?: { data?: { detail?: unknown } };
 };
 const detail = axiosErr.response?.data?.detail;
 if (detail && typeof detail === "object" &&"missing" in detail) {
 const missing = (detail as { missing: string[] }).missing;
 setError(`Brakuje pól: ${missing.join(",")}`);
 return;
 }
 if (typeof detail === "string") {
 setError(detail);
 return;
 }
 setError("Nie udało się aktywować kontraktu. Sprawdź dane i spróbuj ponownie.");
 },
 });

 const currenciesMatch =
 form.rate_candidate_currency.toUpperCase() ===
 form.rate_client_currency.toUpperCase();
 const margin =
 canManageFinance &&
 currenciesMatch &&
 form.rate_candidate &&
 form.rate_client
 ? Number(form.rate_client) - Number(form.rate_candidate)
 : null;
 const canSubmit =
 formDirtyOrValid(form, canManageFinance) && !saveRequiredFields.isPending;

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="lg">
 <DialogHeader>
 <DialogTitle>
 Uzupełnij kontrakt — {contractor.candidate.name}{""}
 {contractor.candidate.lastname}
 </DialogTitle>
 <DialogDescription>
 {needsAdminFinance
 ? "Uzupełnij dane operacyjne. Po uzupełnieniu stawek przez administratora kontrakt aktywuje się automatycznie."
 : "Wypełnij wymagane pola. Po zapisaniu kontrakt aktywuje się automatycznie i trafia do zakładki „Aktywni”."}
 </DialogDescription>
 </DialogHeader>

 <DialogBody>
 <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
 <div>
 <Label htmlFor="start_date">Data rozpoczęcia *</Label>
 <Input
 id="start_date"
 type="date"
 value={form.start_date}
 onChange={(e) =>
 setForm((f) => ({ ...f, start_date: e.target.value }))
 }
 />
 </div>
 <div>
 <Label htmlFor="end_date">Data zakończenia</Label>
 <Input
 id="end_date"
 type="date"
 value={form.end_date}
 onChange={(e) =>
 setForm((f) => ({ ...f, end_date: e.target.value }))
 }
 />
 <p className="mt-1 text-xs text-muted-foreground">
 Puste = umowa bezterminowa.
 </p>
 </div>
 {canManageFinance && (
 <>
 <div>
 <Label htmlFor="rate_candidate">Stawka kosztowa (kandydata) *</Label>
 <Input
 id="rate_candidate"
 type="number"
 min={0}
 step={0.001}
 value={form.rate_candidate}
 onChange={(e) =>
 setForm((f) => ({ ...f, rate_candidate: e.target.value }))
 }
 />
 </div>
 <div>
 <Label htmlFor="rate_candidate_currency">
 Waluta stawki kosztowej (kandydata) *
 </Label>
 <Select
 value={form.rate_candidate_currency}
 onValueChange={(value) =>
 setForm((current) => ({
 ...current,
 rate_candidate_currency: value,
 }))
 }
 >
 <SelectTrigger
 id="rate_candidate_currency"
 aria-label="Waluta stawki kosztowej (kandydata)"
 >
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="PLN">PLN</SelectItem>
 <SelectItem value="EUR">EUR</SelectItem>
 <SelectItem value="USD">USD</SelectItem>
 <SelectItem value="GBP">GBP</SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div>
 <Label htmlFor="rate_client">Stawka przychodowa (klienta) *</Label>
 <Input
 id="rate_client"
 type="number"
 min={0}
 step={0.001}
 value={form.rate_client}
 onChange={(e) =>
 setForm((f) => ({ ...f, rate_client: e.target.value }))
 }
 />
 </div>
 <div>
 <Label htmlFor="rate_client_currency">
 Waluta stawki przychodowej (klienta) *
 </Label>
 <Select
 value={form.rate_client_currency}
 onValueChange={(value) =>
 setForm((current) => ({
 ...current,
 rate_client_currency: value,
 }))
 }
 >
 <SelectTrigger
 id="rate_client_currency"
 aria-label="Waluta stawki przychodowej (klienta)"
 >
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="PLN">PLN</SelectItem>
 <SelectItem value="EUR">EUR</SelectItem>
 <SelectItem value="USD">USD</SelectItem>
 <SelectItem value="GBP">GBP</SelectItem>
 </SelectContent>
 </Select>
 </div>
 </>
 )}
 <div>
 <Label htmlFor="contract_type">Typ umowy *</Label>
 <Select
 value={form.contract_type}
 onValueChange={(v) =>
 setForm((f) => ({
 ...f,
 contract_type: v as FormState["contract_type"],
 }))
 }
 >
 <SelectTrigger id="contract_type">
 <SelectValue placeholder="Wybierz typ" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="b2b">B2B</SelectItem>
 <SelectItem value="uop">Umowa o pracę</SelectItem>
 <SelectItem value="uzlecenie">Umowa zlecenie</SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div>
 <Label htmlFor="work_mode">Tryb pracy (opcjonalnie)</Label>
 <Select
 value={form.work_mode}
 onValueChange={(v) =>
 setForm((f) => ({
 ...f,
 work_mode: v === "none" ? "" : (v as FormState["work_mode"]),
 }))
 }
 >
 <SelectTrigger id="work_mode">
 <SelectValue placeholder="Wybierz tryb" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="none">Nie określono</SelectItem>
 <SelectItem value="remote">Zdalnie</SelectItem>
 <SelectItem value="hybrid">Hybryda</SelectItem>
 <SelectItem value="onsite">Biuro</SelectItem>
 </SelectContent>
 </Select>
 </div>
 </div>

 {margin != null && (
 <div className="mt-4 p-3 rounded-md bg-[hsl(var(--bg-subtle))] text-sm">
 <span className="text-muted-foreground">Marża: </span>
 <span className="font-mono font-semibold text-foreground">
 {margin.toLocaleString("pl-PL")} {form.rate_client_currency}
 </span>
 </div>
 )}

 {error && (
 <div className="mt-3 p-3 rounded-md bg-destructive/10 border border-destructive/20 text-sm text-red-800">
 {error}
 </div>
 )}
 </DialogBody>

 <DialogFooter>
 <Button
 variant="ghost"
 onClick={() => onOpenChange(false)}
 disabled={saveRequiredFields.isPending}
 >
 Anuluj
 </Button>
 <Button
 variant="primary"
 disabled={!canSubmit}
 loading={saveRequiredFields.isPending}
 onClick={() => saveRequiredFields.mutate()}
 >
 <CheckCircle2 className="h-4 w-4" />{""}
 {needsAdminFinance ? "Zapisz dane operacyjne" : "Aktywuj kontrakt"}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 );
}
