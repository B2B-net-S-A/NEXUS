"use client";

import { useState } from "react";
import Link from "next/link";
import { CalendarClock, CheckCircle2, FileText, Sparkles, Star } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useStaffMeeting,
  useStaffMeetings,
  type StaffMeeting,
} from "@/lib/api/portal-staff";
import { cn } from "@/lib/utils";

import { TRANSCRIPT_LABELS, formatWhen } from "./portal-tabs-model";

function Stars({ value }: { value: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`Ocena ${value} z 5`}>
      {[1, 2, 3, 4, 5].map((index) => (
        <Star
          key={index}
          aria-hidden
          className={cn("size-3", index <= value ? "fill-warning text-warning" : "text-border")}
        />
      ))}
    </span>
  );
}

function MeetingBadge({ meeting }: { meeting: StaffMeeting }) {
  if (meeting.status === "cancelled") return <Badge variant="neutral" size="sm">odwołana</Badge>;
  if (new Date(meeting.start_at) > new Date()) return <Badge variant="info" size="sm">umówiona</Badge>;
  return meeting.rating ? <Stars value={meeting.rating.score} /> : null;
}

function MeetingDetail({ id }: { id: number }) {
  const detail = useStaffMeeting(id);
  if (detail.isLoading) return <p className="p-4 text-sm text-muted-foreground">Wczytujemy rozmowę…</p>;
  if (detail.isError || !detail.data) {
    return (
      <p role="alert" className="p-4 text-sm text-destructive">
        {apiErrorMessage(detail.error, "Nie udało się wczytać rozmowy.")}
      </p>
    );
  }
  const meeting = detail.data;
  return (
    <section className="min-w-0 rounded-xl border bg-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">
            {[meeting.consultant, meeting.client].filter(Boolean).join(" · ") || "Rozmowa"}
          </h3>
          <p className="text-xs text-muted-foreground">
            {formatWhen(meeting.start_at)} · Teams · prowadzi {meeting.host ?? "—"} · z portalu konsultanta
          </p>
        </div>
        <Badge variant="info" size="sm">
          transkrypt, bez nagrania wideo
        </Badge>
      </header>
      <div className="grid gap-0 lg:grid-cols-[1fr_240px]">
        <div className="min-w-0 space-y-3 p-4 lg:border-r">
          {meeting.summary ? (
            <div className="rounded-lg bg-muted p-3 text-sm">
              <p className="mb-1 inline-flex items-center gap-1.5 text-xs font-semibold text-primary">
                <Sparkles aria-hidden className="size-3.5" /> Podsumowanie z transkryptu (AI)
              </p>
              <p>{meeting.summary}</p>
              {meeting.action_items.length > 0 ? (
                <>
                  <p className="mt-2 text-xs font-medium">Do zrobienia</p>
                  <ul className="mt-1 space-y-1 text-xs">
                    {meeting.action_items.map((item, index) => (
                      <li key={index} className="flex items-start gap-1.5">
                        <CheckCircle2 aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                        {item.who ? `${item.who}: ` : ""}
                        {item.what}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {meeting.summary_status === "failed"
                ? "Nie udało się przygotować podsumowania. Transkrypt jest poniżej."
                : "Podsumowania jeszcze nie ma."}
            </p>
          )}
          <div>
            <p className="mb-1.5 inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <FileText aria-hidden className="size-3.5" /> Transkrypt
            </p>
            {meeting.transcript ? (
              <pre className="max-h-[50dvh] overflow-auto whitespace-pre-wrap font-sans text-sm">
                {meeting.transcript}
              </pre>
            ) : (
              <p className="text-sm text-muted-foreground">
                {meeting.transcript_purged
                  ? "Transkrypt usunięty po terminie przechowywania."
                  : (TRANSCRIPT_LABELS[meeting.transcript_status] ?? "Transkryptu jeszcze nie ma.")}
              </p>
            )}
          </div>
        </div>
        <aside className="space-y-4 p-4 text-sm">
          <div>
            <p className="text-xs font-semibold text-muted-foreground">Powód podany przy rezerwacji</p>
            <p className="mt-1">{meeting.reason ? `„${meeting.reason}”` : "Nie podano."}</p>
          </div>
          {meeting.case_id ? (
            <Link className="block text-primary underline-offset-2 hover:underline" href={`/people/cases/${meeting.case_id}`}>
              Sprawa #{meeting.case_id}
            </Link>
          ) : null}
          {meeting.rating ? (
            <div>
              <p className="text-xs font-semibold text-muted-foreground">Ocena konsultanta</p>
              <div className="mt-1 flex items-center gap-2">
                <Stars value={meeting.rating.score} />
                <span className="font-medium">{meeting.rating.score}/5</span>
              </div>
              {meeting.rating.comment ? (
                <p className="mt-1 text-xs text-muted-foreground">„{meeting.rating.comment}”</p>
              ) : null}
              {meeting.rating.resolved != null ? (
                <p className="mt-1 text-xs">
                  Sprawa załatwiona: <span className="font-medium">{meeting.rating.resolved ? "tak" : "nie"}</span>
                </p>
              ) : null}
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

/** Zakładka „Rozmowy”: rezerwacje z portalu, transkrypt i podsumowanie. */
export function TalksTab() {
  const meetings = useStaffMeetings();
  const [selected, setSelected] = useState<number | null>(null);
  if (meetings.isLoading) return <p className="text-sm text-muted-foreground">Wczytujemy rozmowy…</p>;
  if (meetings.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(meetings.error, "Nie udało się wczytać rozmów.")}
        onRetry={() => meetings.refetch()}
      />
    );
  }
  const items = meetings.data?.items ?? [];
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">Nie ma jeszcze rozmów z portalu konsultanta.</p>;
  }
  const active = selected ?? items[0].id;
  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <ul className="space-y-2">
        {items.map((meeting) => (
          <li key={meeting.id}>
            <button
              type="button"
              aria-pressed={meeting.id === active}
              onClick={() => setSelected(meeting.id)}
              className={cn(
                "w-full rounded-lg border bg-card p-3 text-left",
                meeting.id === active && "border-primary ring-1 ring-primary",
              )}
            >
              <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <CalendarClock aria-hidden className="size-3" /> {formatWhen(meeting.start_at)}
                </span>
                <MeetingBadge meeting={meeting} />
              </span>
              <span className="mt-1 block text-sm font-medium">
                {meeting.consultant ?? "Konsultant"}{" "}
                <span className="font-normal text-muted-foreground">→ {meeting.host ?? "—"}</span>
              </span>
              <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                {meeting.reason ? `„${meeting.reason}”` : meeting.topic_label}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <MeetingDetail id={active} />
    </div>
  );
}
