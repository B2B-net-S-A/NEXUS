"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { portalApi, portalKeys, type PortalMe, type PortalTopic } from "@/lib/api/consultant-portal";

export function NewCaseDialog({ me, onClose }: { me: PortalMe; onClose: () => void }) {
  const client = useQueryClient();
  const [topic, setTopic] = useState<PortalTopic>(me.topics[0]?.key ?? "invoice");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = title.trim().length >= 3 && body.trim().length >= 3;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.newCase({ topic, title: title.trim(), body: body.trim() });
      await client.invalidateQueries({ queryKey: portalKeys.cases });
      onClose();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się założyć zgłoszenia. Spróbuj ponownie za chwilę."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Nowe zgłoszenie"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!ready || busy} onClick={submit}>
            Wyślij
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Czego dotyczy" htmlFor="case-topic">
          <Select value={topic} onValueChange={(value) => setTopic(value as PortalTopic)}>
            <SelectTrigger id="case-topic">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {me.topics.map((option) => (
                <SelectItem key={option.key} value={option.key}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Temat" htmlFor="case-title">
          <Input
            id="case-title"
            maxLength={120}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </FormField>
        <FormField label="Opis" htmlFor="case-body">
          <Textarea
            id="case-body"
            rows={5}
            maxLength={5000}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
