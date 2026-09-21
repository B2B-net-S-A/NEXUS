"use client";

/**
 * „Napisz" z panelu propozycji — szablon pierwszej wiadomości do kandydata.
 *
 * Przeniesione ze strony rekrutacji (dawna zakładka „AI Matching"). Treść
 * szablonu bez zmian: temat „Oferta pracy: …" zostaje, bo odbiorcą jest
 * kandydat, nie rekruter (CLAUDE.md „Rekrutacja, nie Oferta").
 *
 * Panel propozycji zna tylko `candidateId` (tożsamość węższa niż profil, bez
 * kontaktu), więc adres dociągamy tutaj — tym samym kluczem co profil
 * kandydata, czyli zwykle z cache'u.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Mail } from "lucide-react";

import { candidatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { copyTextToClipboard } from "@/lib/clipboard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export interface EmailTemplateJob {
  title: string;
  reference_number?: string | null;
}

interface CandidateContact {
  name?: string | null;
  lastname?: string | null;
  email?: string | null;
}

export function buildEmailTemplate(candidate: CandidateContact, job: EmailTemplateJob) {
  // Numer referencyjny w temacie i treści: kandydat może go zacytować,
  // a skrzynka rekrutera wątkuje po stałym identyfikatorze.
  const refSuffix = job.reference_number ? ` [${job.reference_number}]` : "";
  const refLine = job.reference_number ? `\n\nNumer referencyjny: ${job.reference_number}` : "";
  const subject = `Oferta pracy: ${job.title}${refSuffix}`;
  const body = `Dzień dobry ${candidate.name ?? ""},\n\nZwracam się do Pana/Pani w imieniu B2B.net S.A. z ofertą stanowiska:\n\n**${job.title}**${refLine}\n\nNa podstawie Pana/Pani profilu uważam, że ta rola idealnie odpowiada Pana/Pani kompetencjom.\n\nCzy byłby Pan/Pani zainteresowany/a rozmową wstępną?\n\nPozdrawiam,\nZespół Rekrutacji B2B.net`;
  return { subject, body };
}

export function EmailTemplateModal({
  candidateId,
  job,
  onClose,
}: {
  candidateId: number;
  job: EmailTemplateJob;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const query = useQuery<CandidateContact>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data as CandidateContact),
    staleTime: 60_000,
  });
  const candidate = query.data;
  const fullName = candidate
    ? `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim() || `Kandydat #${candidateId}`
    : `Kandydat #${candidateId}`;
  const template = candidate ? buildEmailTemplate(candidate, job) : null;

  const handleCopy = async () => {
    if (!template) return;
    // „Skopiowano" tylko po UDANYM zapisie do schowka.
    const ok = await copyTextToClipboard(`Temat: ${template.subject}\n\n${template.body}`);
    if (!ok) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Wyślij wiadomość do {fullName}</DialogTitle>
          <DialogDescription>Szablon pierwszej wiadomości — skopiuj albo otwórz w programie pocztowym.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {query.isLoading ? (
            <p className="text-sm text-muted-foreground">Wczytywanie danych kandydata…</p>
          ) : query.isError || !template ? (
            <p role="alert" className="text-sm text-destructive-muted-foreground">
              Nie udało się wczytać danych kandydata: {apiErrorMessage(query.error, "błąd serwera")}.
            </p>
          ) : (
            <>
              <div>
                <p className="text-xs font-semibold uppercase text-muted-foreground">Temat</p>
                <p className="mt-1 rounded bg-muted p-2 text-sm">{template.subject}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase text-muted-foreground">Treść</p>
                <pre className="mt-1 whitespace-pre-wrap rounded bg-muted p-3 font-sans text-sm">{template.body}</pre>
              </div>
            </>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Zamknij</Button>
          {template ? (
            <Button variant="outline" onClick={() => void handleCopy()}>
              {copied ? <Check className="size-4 text-success" aria-hidden /> : <Copy className="size-4" aria-hidden />}
              {copied ? "Skopiowano" : "Kopiuj"}
            </Button>
          ) : null}
          {template && candidate?.email ? (
            <Button asChild>
              <a
                href={`mailto:${candidate.email}?subject=${encodeURIComponent(template.subject)}&body=${encodeURIComponent(template.body)}`}
              >
                <Mail className="size-4" aria-hidden />
                Otwórz w kliencie email
              </a>
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
