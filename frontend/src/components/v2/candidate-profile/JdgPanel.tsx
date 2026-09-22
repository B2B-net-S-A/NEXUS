"use client";

/** Dane do umowy (JDG / firma) — trafiają do szablonu umowy B2B. */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileSignature } from "lucide-react";

import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

// ─── Dane do umowy (JDG) ─────────────────────────────────────────────────

interface JDGPanelInitial {
 legal_name?: string | null;
 nip?: string | null;
 regon?: string | null;
 business_address?: string | null;
 business_form?: string | null;
}

const BUSINESS_FORM_OPTIONS: { value: string; label: string }[] = [
 { value: "jdg", label: "JDG (jednoosobowa)" },
 { value: "sp_zoo", label: "Sp. z o.o." },
 { value: "sa", label: "S.A." },
 { value: "sc", label: "Spółka cywilna" },
 { value: "osoba_fizyczna", label: "Osoba fizyczna (UoP/zlecenie)" },
];

export function JDGPanel({
 candidateId,
 initial,
}: {
 candidateId: number;
 initial: JDGPanelInitial;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const [form, setForm] = useState({
 legal_name: initial.legal_name ?? "",
 nip: initial.nip ?? "",
 regon: initial.regon ?? "",
 business_address: initial.business_address ?? "",
 business_form: initial.business_form ?? "",
 });

 const dirty =
 form.legal_name !== (initial.legal_name ?? "") ||
 form.nip !== (initial.nip ?? "") ||
 form.regon !== (initial.regon ?? "") ||
 form.business_address !== (initial.business_address ?? "") ||
 form.business_form !== (initial.business_form ?? "");

 const save = useMutation({
 mutationFn: () =>
 api.patch(`/api/candidates/${candidateId}`, {
 legal_name: form.legal_name || null,
 nip: form.nip || null,
 regon: form.regon || null,
 business_address: form.business_address || null,
 business_form: form.business_form || null,
 }),
 onSuccess: () => {
 showSuccess("Zapisano dane do umowy");
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.detail(candidateId) });
 },
 onError: () => showError("Nie udało się zapisać danych JDG"),
 });

 return (
 <Card variant="default" size="md" id="candidate-jdg-panel" className="scroll-mt-4">
 <CardHeader className="pb-2!">
 <CardTitle className="text-sm font-semibold uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-2">
 <FileSignature className="h-3.5 w-3.5" />
 Dane do umowy (JDG / firma)
 </CardTitle>
 </CardHeader>
 <CardContent className="space-y-3">
 <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
 <div>
 <Label className="text-xs">Nazwa prawna</Label>
 <Input
 value={form.legal_name}
 onChange={(e) =>
 setForm((f) => ({ ...f, legal_name: e.target.value }))
 }
 placeholder="np. Jan Kowalski JDG"
 />
 </div>
 <div>
 <Label className="text-xs">Forma działalności</Label>
 <select
 className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
 value={form.business_form}
 onChange={(e) =>
 setForm((f) => ({ ...f, business_form: e.target.value }))
 }
 >
 <option value="">— wybierz —</option>
 {BUSINESS_FORM_OPTIONS.map((opt) => (
 <option key={opt.value} value={opt.value}>
 {opt.label}
 </option>
 ))}
 </select>
 </div>
 <div>
 <Label className="text-xs">NIP</Label>
 <Input
 value={form.nip}
 onChange={(e) => setForm((f) => ({ ...f, nip: e.target.value }))}
 placeholder="np. PL5252000000"
 />
 </div>
 <div>
 <Label className="text-xs">REGON</Label>
 <Input
 value={form.regon}
 onChange={(e) =>
 setForm((f) => ({ ...f, regon: e.target.value }))
 }
 />
 </div>
 </div>
 <div>
 <Label className="text-xs">Adres siedziby</Label>
 <Textarea
 value={form.business_address}
 onChange={(e) =>
 setForm((f) => ({ ...f, business_address: e.target.value }))
 }
 placeholder="ul. Marszałkowska 1, 00-001 Warszawa"
 rows={2}
 />
 </div>
 <div className="flex justify-end">
 <Button
 size="sm"
 disabled={!dirty || save.isPending}
 onClick={() => save.mutate()}
 >
 {save.isPending ? "Zapisuję…" : "Zapisz"}
 </Button>
 </div>
 </CardContent>
 </Card>
 );
}
