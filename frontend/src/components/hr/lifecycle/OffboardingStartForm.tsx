"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { usePeople } from "@/lib/api/hr";
import {
  EXIT_INITIATOR_LABELS,
  EXIT_REASON_LABELS,
  useCreateOffboarding,
  useLifecycleTemplates,
  type ExitInitiator,
  type ExitReason,
} from "@/lib/api/hr-lifecycle";
import { formatWeekdayDayPl } from "@/lib/date-pl";

const AUTO = "auto";
const NONE = "none";

export function OffboardingStartForm({
  userId,
  defaultManagerId,
}: {
  userId: number;
  defaultManagerId: number | null;
}) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const directory = usePeople();
  const templates = useLifecycleTemplates("offboarding");
  const create = useCreateOffboarding();
  const [lastDay, setLastDay] = useState("");
  const [initiator, setInitiator] = useState<string>(NONE);
  const [reason, setReason] = useState<string>(NONE);
  const [note, setNote] = useState("");
  const [managerId, setManagerId] = useState(
    defaultManagerId == null ? NONE : String(defaultManagerId),
  );
  const [templateId, setTemplateId] = useState(AUTO);
  const [error, setError] = useState<string | null>(null);

  const managers = (directory.data?.items ?? []).filter((row) => row.user_id !== userId);
  const activeTemplates = (templates.data ?? []).filter(
    // Ścieżki konsultanta wiszą przy kontrakcie — nie dla osoby z kontem.
    (t) => t.is_active && (t.audience ?? "team") === "team",
  );

  const submit = async (start: boolean) => {
    setError(null);
    if (!lastDay) {
      setError("Podaj ostatni dzień pracy.");
      return;
    }
    if (start) {
      const ok = await askConfirm({
        title: "Rozpocząć odejście?",
        description: `Przełożony, Kadry, recepcja i IT dostaną zadania. Praca przejdzie na przejmujących ${formatWeekdayDayPl(lastDay)} o 18:00, konto wyłączy się następnego dnia. Do tego czasu można cofnąć odejście.`,
        confirmLabel: "Rozpocznij",
      });
      if (!ok) return;
    }
    create.mutate(
      {
        user_id: userId,
        last_working_day: lastDay,
        exit_initiator: initiator === NONE ? null : (initiator as ExitInitiator),
        exit_reason: reason === NONE ? null : (reason as ExitReason),
        exit_note: note.trim() || null,
        manager_user_id: managerId === NONE ? null : Number(managerId),
        template_id: templateId === AUTO ? null : Number(templateId),
        start,
      },
      {
        onSuccess: () =>
          showToast(start ? "Odejście rozpoczęte" : "Szkic odejścia zapisany", "success"),
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się założyć sprawy odejścia.")),
      },
    );
  };

  return (
    <Card className="max-w-3xl space-y-4 p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Ostatni dzień pracy" htmlFor="off-last-day" required>
          <Input
            id="off-last-day"
            type="date"
            value={lastDay}
            onChange={(event) => setLastDay(event.target.value)}
          />
        </FormField>
        <FormField label="Przełożony" htmlFor="off-manager" description="Domyślnie przejmuje pracę.">
          <Select value={managerId} onValueChange={setManagerId}>
            <SelectTrigger id="off-manager">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Bez przełożonego</SelectItem>
              {managers.map((row) => (
                <SelectItem key={row.user_id} value={String(row.user_id)}>
                  {row.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Kto zakończył współpracę" htmlFor="off-initiator">
          <Select value={initiator} onValueChange={setInitiator}>
            <SelectTrigger id="off-initiator">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nie podano</SelectItem>
              {(Object.keys(EXIT_INITIATOR_LABELS) as ExitInitiator[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {EXIT_INITIATOR_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Powód" htmlFor="off-reason">
          <Select value={reason} onValueChange={setReason}>
            <SelectTrigger id="off-reason">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nie podano</SelectItem>
              {(Object.keys(EXIT_REASON_LABELS) as ExitReason[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {EXIT_REASON_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Lista zadań" htmlFor="off-template">
          <Select value={templateId} onValueChange={setTemplateId}>
            <SelectTrigger id="off-template">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTO}>Dobierz do formy i działu</SelectItem>
              {activeTemplates.map((t) => (
                <SelectItem key={t.id} value={String(t.id)}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField
          label="Notatka"
          htmlFor="off-note"
          description="Widzą ją Kadry i przełożony. Bez informacji o zdrowiu."
          className="sm:col-span-2"
        >
          <Textarea
            id="off-note"
            rows={2}
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" disabled={create.isPending} onClick={() => void submit(false)}>
          Zapisz szkic
        </Button>
        <Button disabled={create.isPending} onClick={() => void submit(true)}>
          Rozpocznij odejście
        </Button>
      </div>
      {confirmDialog}
    </Card>
  );
}
