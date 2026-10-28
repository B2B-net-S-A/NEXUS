"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { ACTIVITY_KIND_LABELS, useUpdateActivity, type Activity, type ActivityKind } from "@/lib/api/sales";

import { localInputToIso } from "./ActivityTimeline";
import { SalesSelect } from "./SalesSelect";

const KINDS: ActivityKind[] = ["note", "call", "meeting", "email", "task"];

/** ISO → wartość pola `datetime-local` w czasie lokalnym. */
function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

interface ActivityEditDialogProps {
  activity: Activity;
  onClose: () => void;
}

/** Poprawka wpisu historii (autor albo admin; uprawnienie sprawdza też API). */
export function ActivityEditDialog({ activity, onClose }: ActivityEditDialogProps) {
  const update = useUpdateActivity(activity.id);
  const { showError, showSuccess } = useToast();
  const [kind, setKind] = useState<ActivityKind>(activity.kind);
  const [subject, setSubject] = useState(activity.subject ?? "");
  const [body, setBody] = useState(activity.body ?? "");
  const [due, setDue] = useState(isoToLocalInput(activity.due_at));
  const hasDue = kind === "task" || kind === "call";

  const save = () =>
    update.mutate(
      {
        kind,
        subject: subject.trim() || null,
        body: body.trim() || null,
        due_at: hasDue ? localInputToIso(due) : null,
      },
      {
        onSuccess: () => {
          showSuccess("Zapisano zmiany wpisu.");
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać wpisu.")),
      },
    );

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Popraw wpis"
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={save} loading={update.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <div className="space-y-1">
          <Label htmlFor="sales-activity-kind">Rodzaj</Label>
          <SalesSelect
            id="sales-activity-kind"
            value={kind}
            onValueChange={(value) => setKind(value as ActivityKind)}
            options={KINDS.map((value) => ({ value, label: ACTIVITY_KIND_LABELS[value] }))}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-activity-subject">Temat</Label>
          <Input id="sales-activity-subject" value={subject} onChange={(event) => setSubject(event.target.value)} />
        </div>
        {hasDue && (
          <div className="space-y-1">
            <Label htmlFor="sales-activity-due">Termin</Label>
            <Input
              id="sales-activity-due"
              type="datetime-local"
              value={due}
              onChange={(event) => setDue(event.target.value)}
            />
          </div>
        )}
        <div className="space-y-1">
          <Label htmlFor="sales-activity-body">Treść</Label>
          <Textarea id="sales-activity-body" rows={6} value={body} onChange={(event) => setBody(event.target.value)} />
        </div>
      </div>
    </AppModal>
  );
}
