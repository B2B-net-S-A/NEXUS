"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Mail,
  X,
  Loader2,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

type EmailCategory =
  | "application_received"
  | "screening_invite"
  | "interview_invite"
  | "rejection"
  | "offer"
  | "general";

interface EmailTemplate {
  id: number;
  name: string;
  subject: string;
  body: string;
  category: EmailCategory;
  is_default: boolean;
}

interface SendEmailModalProps {
  candidateId: number;
  candidateName: string;
  candidateEmail: string;
  onClose: () => void;
}

// ── Constants ────────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<EmailCategory, string> = {
  application_received: "Potwierdzenie aplikacji",
  screening_invite: "Zaproszenie na screening",
  interview_invite: "Zaproszenie na rozmowę",
  rejection: "Odrzucenie",
  offer: "Oferta współpracy",
  general: "Ogólna wiadomość",
};

// ── Component ─────────────────────────────────────────────────────────────────

export function SendEmailModal({
  candidateId,
  candidateName,
  candidateEmail,
  onClose,
}: SendEmailModalProps) {
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | "">("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [toEmail, setToEmail] = useState(candidateEmail);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  // ── Fetch templates ────────────────────────────────────────────────────────

  const { data: templates = [], isLoading: templatesLoading } = useQuery<EmailTemplate[]>({
    queryKey: ["email-templates"],
    queryFn: () => api.get("/api/email-templates").then((r) => r.data),
  });

  // ── Load template preview when selected ───────────────────────────────────

  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ["email-preview", selectedTemplateId, candidateId],
    queryFn: () =>
      api
        .post("/api/emails/preview", {
          template_id: selectedTemplateId,
          candidate_id: candidateId,
        })
        .then((r) => r.data),
    enabled: !!selectedTemplateId,
  });

  useEffect(() => {
    if (preview) {
      setSubject(preview.subject);
      setBody(preview.body);
    }
  }, [preview]);

  // ── Send mutation ──────────────────────────────────────────────────────────

  const sendMutation = useMutation({
    mutationFn: () =>
      api.post("/api/emails/send", {
        to_email: toEmail,
        subject,
        body,
        candidate_id: candidateId,
        template_id: selectedTemplateId || undefined,
      }),
    onSuccess: () => {
      setSent(true);
    },
    onError: () => {
      setError("Błąd podczas wysyłania emaila. Spróbuj ponownie.");
    },
  });

  const handleSend = () => {
    setError("");
    if (!toEmail.trim() || !subject.trim() || !body.trim()) {
      setError("Uzupełnij adres email, temat i treść wiadomości.");
      return;
    }
    sendMutation.mutate();
  };

  // ── Render: Success ────────────────────────────────────────────────────────

  if (sent) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md p-8 text-center">
          <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <CheckCircle2 className="w-8 h-8 text-emerald-600" />
          </div>
          <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">Email zarejestrowany!</h3>
          <p className="text-sm text-gray-500 mb-2">
            Email zostanie wysłany do <strong>{toEmail}</strong>
          </p>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 mb-6">
            <p className="text-xs text-amber-700 font-medium flex items-center gap-1 justify-center">
              <Info className="w-3.5 h-3.5" />
              Tryb symulacji — email nie został fizycznie wysłany (SMTP w przygotowaniu)
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-full px-4 py-2.5 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition-colors"
          >
            Zamknij
          </button>
        </div>
      </div>
    );
  }

  // ── Render: Main ───────────────────────────────────────────────────────────

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <Mail className="w-5 h-5 text-blue-500" />
            <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Wyślij email</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Simulation notice */}
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 flex items-center gap-2">
            <Info className="w-4 h-4 text-amber-500 flex-shrink-0" />
            <p className="text-xs text-amber-700">
              <strong>Email zostanie wysłany</strong> — tryb symulacji aktywny. Wiadomość zostanie
              zarejestrowana w systemie, ale nie wyślemy jej przez SMTP.
            </p>
          </div>

          {/* Candidate info */}
          <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Kandydat</p>
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{candidateName}</p>
          </div>

          {/* Template selector */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
              Szablon emaila (opcjonalnie)
            </label>
            <div className="relative">
              <select
                value={selectedTemplateId}
                onChange={(e) =>
                  setSelectedTemplateId(e.target.value ? Number(e.target.value) : "")
                }
                className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent appearance-none bg-white dark:bg-gray-700 pr-8"
                disabled={templatesLoading}
              >
                <option value="">— Wybierz szablon (opcjonalnie) —</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({CATEGORY_LABELS[t.category]})
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            </div>
            {previewLoading && selectedTemplateId && (
              <p className="text-xs text-gray-400 mt-1 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" /> Ładowanie szablonu...
              </p>
            )}
          </div>

          {/* To email */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
              Do *
            </label>
            <input
              type="email"
              value={toEmail}
              onChange={(e) => setToEmail(e.target.value)}
              className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Subject */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
              Temat *
            </label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Temat wiadomości..."
              className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Body */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
              Treść *
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Treść wiadomości..."
              rows={10}
              className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-2xl">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl hover:bg-gray-50 transition-colors"
          >
            Anuluj
          </button>
          <button
            onClick={handleSend}
            disabled={sendMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {sendMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Mail className="w-4 h-4" />
            )}
            Wyślij email
          </button>
        </div>
      </div>
    </div>
  );
}
