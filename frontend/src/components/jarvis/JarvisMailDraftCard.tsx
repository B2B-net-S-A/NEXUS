"use client";

/** Szkic maila od Jarvisa — wysyła człowiek z okna maila NEXUSA (27.10.2026).
 *  Treść to zwykły tekst od modelu: pokazujemy ją jako tekst, nie markdown. */

import { useState } from "react";
import { Copy, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { JarvisMailDraft } from "@/lib/jarvis/types";

interface Recipient {
  name: string;
  email: string;
}

async function loadRecipient(candidateId: number): Promise<Recipient> {
  const { data } = await api.get<{ candidate?: { name?: string; lastname?: string; email?: string | null } }>(
    `/api/candidates/${candidateId}/quick-view`,
  );
  const person = data.candidate ?? {};
  return {
    name: [person.name, person.lastname].filter(Boolean).join(" ").trim(),
    email: (person.email ?? "").trim(),
  };
}

export function JarvisMailDraftCard({ draft }: { draft: JarvisMailDraft }) {
  const [recipient, setRecipient] = useState<Recipient | null>(
    draft.email ? { name: draft.candidate_name ?? "", email: draft.email } : null,
  );
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function openCompose() {
    setError(null);
    if (recipient?.email) {
      setOpen(true);
      return;
    }
    setBusy(true);
    try {
      const loaded = await loadRecipient(draft.candidate_id);
      if (!loaded.email) {
        setError("Kandydat nie ma adresu e-mail w profilu.");
        return;
      }
      setRecipient(loaded);
      setOpen(true);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się wczytać adresu kandydata."));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`);
      setCopied(true);
    } catch {
      setError("Nie udało się skopiować — zaznacz treść i skopiuj ręcznie.");
    }
  }

  const to = recipient?.name || draft.candidate_name || `Kandydat #${draft.candidate_id}`;
  return (
    <div className="rounded-lg border border-primary/30 bg-card p-3 shadow-xs" data-testid="jarvis-mail-draft">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-primary">Szkic maila — nic nie wysłano</div>
      <p className="text-xs text-muted-foreground">
        Do: <span className="font-medium text-foreground">{to}</span>
        {recipient?.email ? ` <${recipient.email}>` : ""}
      </p>
      <p className="mt-1 text-sm font-semibold text-foreground">{draft.subject}</p>
      <pre className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 px-2 py-1.5 font-sans text-xs text-foreground">
        {draft.body}
      </pre>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button size="sm" loading={busy} disabled={busy} onClick={() => void openCompose()}>
          <Mail className="mr-1 h-3.5 w-3.5" aria-hidden />
          Otwórz w oknie maila
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void copy()}>
          <Copy className="mr-1 h-3.5 w-3.5" aria-hidden />
          {copied ? "Skopiowane" : "Kopiuj treść"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-1.5 text-xs text-destructive">
          {error}
        </p>
      )}
      {recipient && (
        <SendEmailV2
          open={open}
          onOpenChange={setOpen}
          candidateId={draft.candidate_id}
          candidateName={recipient.name || to}
          candidateEmail={recipient.email}
          defaultSubject={draft.subject}
          defaultBody={draft.body}
        />
      )}
    </div>
  );
}
