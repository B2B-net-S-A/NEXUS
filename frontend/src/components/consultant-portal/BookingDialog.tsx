"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, Video } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  portalApi,
  portalKeys,
  usePortalQuery,
  type PortalMe,
  type PortalTopic,
} from "@/lib/api/consultant-portal";
import { cn } from "@/lib/utils";

import { slotLabel } from "./portal-model";

/** Umów rozmowę: temat, osoba i termin, powód. Spotkanie zakłada organizator po stronie firmy. */
export function BookingDialog({
  me,
  note,
  onClose,
}: {
  me: PortalMe;
  note: string | null;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [topic, setTopic] = useState<PortalTopic>(me.topics[0]?.key ?? "invoice");
  const [pick, setPick] = useState<{ host: number; hostName: string; start: string } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hosts = usePortalQuery(portalKeys.hosts(topic), () => portalApi.hosts(topic));

  const submit = async () => {
    if (!pick) return;
    setBusy(true);
    setError(null);
    try {
      await portalApi.book({ host_user_id: pick.host, start: pick.start, topic, reason: reason.trim() });
      await client.invalidateQueries({ queryKey: portalKeys.meetings });
      await client.invalidateQueries({ queryKey: portalKeys.cases });
      onClose();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się zarezerwować rozmowy. Spróbuj inny termin."));
      await client.invalidateQueries({ queryKey: portalKeys.hosts(topic) });
      setPick(null);
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
      title="Umów rozmowę"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!pick || busy} onClick={submit}>
            Zarezerwuj
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Temat rozmowy">
          {me.topics.map((option) => (
            <button
              key={option.key}
              type="button"
              role="radio"
              aria-checked={topic === option.key}
              onClick={() => {
                setTopic(option.key);
                setPick(null);
              }}
              className={cn(
                "rounded-full border px-3 py-1 text-sm",
                topic === option.key
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "text-muted-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        {hosts.isLoading ? <p className="text-sm text-muted-foreground">Sprawdzamy kalendarze…</p> : null}
        {hosts.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(hosts.error, "Nie udało się sprawdzić terminów. Spróbuj ponownie za chwilę.")}
          </p>
        ) : null}
        {hosts.isSuccess && !hosts.data.available ? (
          <p className="text-sm text-muted-foreground">{hosts.data.message}</p>
        ) : null}
        {hosts.isSuccess && hosts.data.available && hosts.data.hosts.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nikt nie ma teraz wolnych terminów. Załóż zgłoszenie, a oddzwonimy.</p>
        ) : null}
        {hosts.isSuccess && hosts.data.available
          ? hosts.data.hosts.map((host) => (
              <div key={host.id} className="rounded-xl border bg-card p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium">{host.name}</p>
                  <span className="text-xs text-muted-foreground">{host.team}</span>
                  {host.matches_topic ? (
                    <Badge variant="success" size="sm">
                      od tego tematu
                    </Badge>
                  ) : null}
                </div>
                {host.slots.length === 0 ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {host.calendar_available ? "Brak wolnych terminów." : "Kalendarz chwilowo niedostępny."}
                  </p>
                ) : (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {host.slots.map((slot) => {
                      const active = pick?.host === host.id && pick.start === slot;
                      return (
                        <button
                          key={slot}
                          type="button"
                          aria-pressed={active}
                          onClick={() => setPick({ host: host.id, hostName: host.name, start: slot })}
                          className={cn(
                            "rounded-md border px-2.5 py-1 text-xs tabular-nums",
                            active ? "border-primary bg-primary text-primary-foreground" : "bg-background",
                          )}
                        >
                          {slotLabel(slot)}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            ))
          : null}
        <FormField label="O czym chcesz porozmawiać?" htmlFor="booking-reason">
          <Textarea
            id="booking-reason"
            rows={3}
            maxLength={1000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </FormField>
        {note ? (
          <div className="flex items-start gap-2 rounded-lg bg-info-muted px-3 py-2 text-xs text-info-muted-foreground">
            <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
            <p>{note}</p>
          </div>
        ) : null}
        {pick ? (
          <p className="inline-flex items-center gap-1.5 text-sm">
            <Video aria-hidden className="size-4 text-primary" /> {pick.hostName} · {slotLabel(pick.start)}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
