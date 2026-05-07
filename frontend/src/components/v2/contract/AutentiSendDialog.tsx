"use client";

import * as React from "react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

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
import { FormField } from "@/components/ui/form-field";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import {
  autentiApi,
  type AutentiSendRequest,
  type AutentiSignatureType,
} from "@/lib/api";

interface SignatureTypeOption {
  value: AutentiSignatureType;
  title: string;
  description: string;
  badge?: string;
}

const SIGNATURE_TYPE_OPTIONS: SignatureTypeOption[] = [
  {
    value: "SES",
    title: "Zwykły e-podpis (SES)",
    description:
      "Podstawowy podpis Autenti — wystarczający do większości umów B2B z JDG. Najszybsza ścieżka, kandydat klika i podpisuje na ekranie.",
    badge: "Domyślny",
  },
  {
    value: "AdES",
    title: "Zaawansowany e-podpis (AdES)",
    description:
      "Z weryfikacją SMS — kandydat dostaje kod jednorazowy przed podpisem. Wymaga numeru telefonu w profilu kandydata.",
  },
  {
    value: "QES",
    title: "Kwalifikowany podpis (QES, eIDAS)",
    description:
      "Równoważny własnoręcznemu (eIDAS). Kandydat musi posiadać profil zaufany / mObywatela albo certyfikat kwalifikowany. Friction wyższe — wybierz tylko gdy klient lub prawo wymaga.",
  },
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: number;
  candidateName: string;
  candidatePhone: string | null;
}

export function AutentiSendDialog({
  open,
  onOpenChange,
  contractId,
  candidateName,
  candidatePhone,
}: Props) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const [signatureType, setSignatureType] =
    useState<AutentiSignatureType>("SES");
  const [expiresInDays, setExpiresInDays] = useState<number>(14);
  const [messagePl, setMessagePl] = useState<string>("");

  const requiresPhone = signatureType === "AdES";
  const phoneMissing = requiresPhone && !candidatePhone;

  const mutation = useMutation({
    mutationFn: (payload: AutentiSendRequest) =>
      autentiApi.send(contractId, payload).then((r) => r.data),
    onSuccess: () => {
      showSuccess("Wysłano do podpisu — status pojawi się za chwilę");
      queryClient.invalidateQueries({
        queryKey: ["autenti-signatures", contractId],
      });
      onOpenChange(false);
      // Reset form
      setSignatureType("SES");
      setExpiresInDays(14);
      setMessagePl("");
    },
    onError: (error: unknown) => {
      const axiosError = error as AxiosError<{
        detail?: string | { message?: string };
      }>;
      const detail = axiosError.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : (detail?.message ?? "Nie udało się wysłać do podpisu.");
      showError(`Błąd wysyłki: ${message}`);
    },
  });

  const submit = () => {
    if (phoneMissing) return;
    mutation.mutate({
      signature_type: signatureType,
      expires_in_days: expiresInDays,
      message_pl: messagePl.trim() || null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Wyślij umowę do podpisu (Autenti)</DialogTitle>
          <DialogDescription>
            Kontrakt zostanie przesłany jako PDF do{" "}
            <span className="font-semibold">{candidateName}</span>. Status
            będzie aktualizowany automatycznie po podpisaniu lub odrzuceniu.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-5">
          <FormField label="Typ podpisu">
            <RadioGroup
              value={signatureType}
              onValueChange={(v) =>
                setSignatureType(v as AutentiSignatureType)
              }
              className="gap-3"
            >
              {SIGNATURE_TYPE_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  htmlFor={`sigtype-${opt.value}`}
                  className="flex gap-3 rounded-md border border-border p-3 hover:border-primary cursor-pointer has-[:checked]:border-primary has-[:checked]:bg-accent/40"
                >
                  <RadioGroupItem
                    id={`sigtype-${opt.value}`}
                    value={opt.value}
                    className="mt-0.5"
                  />
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-foreground">
                        {opt.title}
                      </span>
                      {opt.badge && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-primary/15 text-primary">
                          {opt.badge}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {opt.description}
                    </p>
                  </div>
                </label>
              ))}
            </RadioGroup>
          </FormField>

          {phoneMissing && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              Brak numeru telefonu kandydata. AdES wymaga SMS-OTP — uzupełnij
              telefon w profilu albo wybierz inny typ podpisu.
            </div>
          )}

          <FormField label="Termin wygaśnięcia">
            <input
              type="number"
              min="1"
              max="90"
              value={expiresInDays}
              onChange={(e) =>
                setExpiresInDays(Number.parseInt(e.target.value, 10) || 14)
              }
              className="w-32 h-10 px-3 rounded-md border border-border bg-card focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <span className="ml-2 text-xs text-muted-foreground">
              dni od wysłania (1–90)
            </span>
          </FormField>

          <FormField label="Wiadomość dla kandydata (opcjonalnie)">
            <Textarea
              value={messagePl}
              onChange={(e) => setMessagePl(e.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="np. Cześć Anna, oto umowa którą omawialiśmy w piątek. Pozdrawiam, Marta"
              className="resize-none"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {messagePl.length}/2000 znaków
            </p>
          </FormField>
        </DialogBody>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Anuluj
          </Button>
          <Button
            onClick={submit}
            disabled={mutation.isPending || phoneMissing}
          >
            {mutation.isPending ? "Wysyłam…" : "Wyślij do podpisu"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
