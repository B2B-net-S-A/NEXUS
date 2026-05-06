"use client";

import * as React from"react";
import { useState, useEffect } from"react";
import { useMutation, useQuery } from"@tanstack/react-query";
import { AlertCircle, CheckCircle2, Mail, Send } from"lucide-react";
import api from"@/lib/api";
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
import { FormField } from"@/components/ui/form-field";
import { Input } from"@/components/ui/input";
import { Textarea } from"@/components/ui/textarea";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";

type EmailCategory =
 |"application_received"
 |"screening_invite"
 |"interview_invite"
 |"rejection"
 |"offer"
 |"general";

interface EmailTemplate {
 id: number;
 name: string;
 subject: string;
 body: string;
 category: EmailCategory;
 is_default: boolean;
}

const CATEGORY_LABELS: Record<EmailCategory, string> = {
 application_received:"Potwierdzenie aplikacji",
 screening_invite:"Zaproszenie na screening",
 interview_invite:"Zaproszenie na rozmowę",
 rejection:"Odrzucenie",
 offer:"Oferta współpracy",
 general:"Ogólna wiadomość",
};

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 candidateId: number;
 candidateName: string;
 candidateEmail: string;
 onSent?: () => void;
}

export function SendEmailV2({
 open,
 onOpenChange,
 candidateId,
 candidateName,
 candidateEmail,
 onSent,
}: Props) {
 const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
 const [toEmail, setToEmail] = useState(candidateEmail);
 const [subject, setSubject] = useState("");
 const [body, setBody] = useState("");
 const [error, setError] = useState("");
 const [sent, setSent] = useState(false);

 // Reset on open
 useEffect(() => {
 if (open) {
 setToEmail(candidateEmail);
 setSent(false);
 setError("");
 }
 }, [open, candidateEmail]);

 const { data: templates = [] } = useQuery<EmailTemplate[]>({
 queryKey: ["email-templates"],
 queryFn: () => api.get("/api/email-templates").then((r) => r.data),
 enabled: open,
 });

 const { data: preview } = useQuery({
 queryKey: ["email-preview", selectedTemplateId, candidateId],
 queryFn: () =>
 api
 .post("/api/emails/preview", {
 template_id: Number(selectedTemplateId),
 candidate_id: candidateId,
 })
 .then((r) => r.data),
 enabled: !!selectedTemplateId && open,
 });

 useEffect(() => {
 if (preview) {
 setSubject(preview.subject);
 setBody(preview.body);
 }
 }, [preview]);

 const sendMut = useMutation({
 mutationFn: () =>
 api.post("/api/emails/send", {
 to_email: toEmail,
 subject,
 body,
 candidate_id: candidateId,
 template_id: selectedTemplateId ? Number(selectedTemplateId) : undefined,
 }),
 onSuccess: () => {
 setSent(true);
 onSent?.();
 },
 onError: () => setError("Błąd podczas wysyłania emaila. Spróbuj ponownie."),
 });

 const handleSend = () => {
 setError("");
 if (!toEmail.trim() || !subject.trim() || !body.trim()) {
 setError("Uzupełnij adres, temat i treść wiadomości.");
 return;
 }
 sendMut.mutate();
 };

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="lg">
 {sent ? (
 <>
 <DialogHeader>
 <div className="flex items-center gap-2">
 <CheckCircle2 className="h-5 w-5 text-[#1d5e31]" />
 <DialogTitle>Email wysłany</DialogTitle>
 </div>
 <DialogDescription>
 Wiadomość została wysłana do {candidateName} ({toEmail}).
 </DialogDescription>
 </DialogHeader>
 <DialogFooter>
 <Button variant="primary" onClick={() => onOpenChange(false)}>
 Zamknij
 </Button>
 </DialogFooter>
 </>
 ) : (
 <>
 <DialogHeader>
 <div className="flex items-center gap-2">
 <Mail className="h-4 w-4 text-primary" />
 <DialogTitle>Wyślij email do {candidateName}</DialogTitle>
 </div>
 <DialogDescription>
 Wybierz szablon lub napisz wiadomość od zera.
 </DialogDescription>
 </DialogHeader>

 <DialogBody>
 <div className="space-y-3">
 {error && (
 <div
 role="alert"
 className="inline-flex items-center gap-2 text-sm text-primary bg-primary/10 px-3 py-2 rounded-md w-full"
 >
 <AlertCircle className="h-4 w-4 shrink-0" />
 <span>{error}</span>
 </div>
 )}

 <FormField label="Szablon (opcjonalny)" htmlFor="email-template">
 <Select
 value={selectedTemplateId ||"_blank"}
 onValueChange={(v) =>
 setSelectedTemplateId(v ==="_blank" ?"" : v)
 }
 >
 <SelectTrigger id="email-template">
 <SelectValue placeholder="Brak szablonu — piszę od zera" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="_blank">Brak szablonu</SelectItem>
 {templates.map((t) => (
 <SelectItem key={t.id} value={String(t.id)}>
 {t.name} · {CATEGORY_LABELS[t.category]}
 {t.is_default ?"(default)" :""}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 </FormField>

 <FormField label="Do" htmlFor="email-to" required>
 <Input
 id="email-to"
 type="email"
 value={toEmail}
 onChange={(e) => setToEmail(e.target.value)}
 />
 </FormField>

 <FormField label="Temat" htmlFor="email-subject" required>
 <Input
 id="email-subject"
 value={subject}
 onChange={(e) => setSubject(e.target.value)}
 />
 </FormField>

 <FormField label="Treść" htmlFor="email-body" required>
 <Textarea
 id="email-body"
 value={body}
 onChange={(e) => setBody(e.target.value)}
 rows={10}
 placeholder="Dzień dobry, …"
 />
 </FormField>
 </div>
 </DialogBody>

 <DialogFooter>
 <Button variant="ghost" onClick={() => onOpenChange(false)}>
 Anuluj
 </Button>
 <Button variant="primary" onClick={handleSend} loading={sendMut.isPending}>
 <Send className="h-4 w-4" />
 Wyślij email
 </Button>
 </DialogFooter>
 </>
 )}
 </DialogContent>
 </Dialog>
 );
}
