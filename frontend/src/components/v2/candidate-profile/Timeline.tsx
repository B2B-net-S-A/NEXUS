"use client";

/**
 * Oś czasu kandydata (zakładka „Historia” → „Wszystko”) i skrót ostatniej
 * aktywności w prawej kolumnie zakładki „Profil”. Wydzielone z
 * `CandidateDetailV2.tsx`.
 */

import * as React from "react";
import { useMemo } from "react";
import {
  ArrowRight,
  Calendar,
  FileText,
  Mail,
  MessageSquare,
  Star,
  UserPlus,
} from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  activityActionLabel,
  candidateStageLabel,
  noteTypeLabel,
  userActivityLabel,
} from "@/components/v2/pages/candidate-timeline-labels";
import { unwrapNoteContent } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- payload osi czasu jest luźno typowany (import Traffit + kilka źródeł) */

const TIMELINE_LABEL: Record<string, string> = {
 note: "Notatka",
 stage_change: "Zmiana etapu",
 activity: "Aktywność",
 user_activity: "Akcja użytkownika",
};

// 0045_rejection_emails — map scheduler activity actions to Polish labels.
const REJECTION_EMAIL_ACTION_LABELS: Record<string, string> = {
 rejection_email_scheduled: "Zaplanowano email odrzucenia (wyśle się za 15 min)",
 rejection_email_sent: "Wysłano email odrzucenia do kandydata",
 rejection_email_cancelled: "Anulowano wysyłkę email odrzucenia",
 rejection_email_skipped: "Email odrzucenia pominięty — brak skrzynki MS365",
 rejection_email_failed: "Email odrzucenia — błąd wysyłki",
};

// Traffit-imported "Plik - dodany"/"Plik - usunięty" activities carry the file
// name inside a double-encoded `details.content` JSON blob
// ({"file":{"name":...},"type":{"name":...}}). Pull the name so the timeline can
// render 'Plik "<nazwa>" dodany' instead of the raw 'traffit:Plik - dodany'.
function traffitFileName(details: unknown): string | null {
 if (!details || typeof details !== "object") return null;
 const content = (details as { content?: unknown }).content;
 if (typeof content !== "string") return null;
 try {
 const parsed = JSON.parse(content);
 const name = parsed?.file?.name;
 return typeof name === "string" && name.trim() ? name : null;
 } catch {
 return null;
 }
}

export function timelineItemLabel(item: any): string {
 if (item.type === "note")
 return `Notatka${noteTypeLabel(item.note_type) ? ` — ${noteTypeLabel(item.note_type)}` :""}${item.job_title ? ` (${item.job_title})` :""}`;
 if (item.type === "stage_change")
 return `Etap: ${candidateStageLabel(item.stage)}${item.job_title ? ` (${item.job_title})` :""}`;
 if (item.type === "activity") {
 if (item.action === "applied_via_invite") {
 const owner = item.user_name ??"rekruter";
 const prev = item.previous_created_by_name;
 return prev
 ? `Przejęto opiekę: ${prev} → ${owner} (apply przez link)`
 : `Aplikacja przez link (${owner})`;
 }
 if (
 item.action === "traffit:Plik - dodany" ||
 item.action === "traffit:Plik - usunięty"
 ) {
 const verb = item.action.endsWith("usunięty") ? "usunięty" : "dodany";
 const name = traffitFileName(item.details);
 return name ? `Plik "${name}" ${verb}` : `Plik ${verb}`;
 }
 const rejectionLabel = REJECTION_EMAIL_ACTION_LABELS[item.action];
 if (rejectionLabel) return rejectionLabel;
 return activityActionLabel(item.action);
 }
 if (item.type === "user_activity") return userActivityLabel(item.action_type);
 return TIMELINE_LABEL[item.type] ?? item.type ??"Zdarzenie";
}

// ── Timeline (kandydat) — zgrupowany po dniach, czytelne karty zdarzeń ───────
// Wcześniej był to płaski strumień jednakowych wierszy (każdy z tą samą ikoną
// MessageSquare i surową etykietą typu „Etap: rejected") — nieczytelny przy
// kilkudziesięciu zdarzeniach. Teraz: nagłówek dnia + karta na zdarzenie z
// awatarem autora, czytelnym „kto co zrobił" i kolorowymi badge'ami etapów
// (Nowy → Screening), wzorem osi czasu z Traffita.

// Etap → wariant Badge, żeby przejście „Nowy → Screening" czytało się kolorem:
// info (wczesny lejek) → soft (środek) → success/danger (stany końcowe).
const STAGE_BADGE_VARIANT: Record<
  string,
  React.ComponentProps<typeof Badge>["variant"]
> = {
  new: "info",
  contacted: "info",
  prep_call: "info",
  screening: "soft",
  verified: "soft",
  interview: "soft",
  cv_sent: "soft",
  client_review: "soft",
  client_interview: "soft",
  acceptance: "success",
  negotiation: "warning",
  onboarding: "success",
  active: "success",
  hired: "success",
  rejected: "danger",
  withdrawn: "neutral",
  on_hold: "warning",
};

function StageBadge({ stage }: { stage: string }) {
  return (
    <Badge
      size="lg"
      variant={STAGE_BADGE_VARIANT[stage] ?? "neutral"}
      className="font-semibold"
    >
      {candidateStageLabel(stage)}
    </Badge>
  );
}

// Pełna etykieta dnia dla nagłówka grupy — „Środa, 24 czerwca 2026".
const TIMELINE_DAY_FMT = new Intl.DateTimeFormat("pl-PL", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});
// Na karcie pokazujemy godzinę (HH:MM) — w obrębie dnia „Xh temu" to szum.
const TIMELINE_TIME_FMT = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
});

function timelineDayKey(ts?: string | null): string {
  if (!ts) return "no-date";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "no-date";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function timelineDayLabel(ts?: string | null): string {
  if (!ts) return "Bez daty";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "Bez daty";
  const now = new Date();
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const full = TIMELINE_DAY_FMT.format(d);
  const cap = full.charAt(0).toUpperCase() + full.slice(1);
  if (sameDay(d, now)) return `Dziś · ${cap}`;
  if (sameDay(d, yesterday)) return `Wczoraj · ${cap}`;
  return cap;
}

function timelineTime(ts?: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : TIMELINE_TIME_FMT.format(d);
}

// Autor zdarzenia — napędza inicjały awatara i pogrubione imię w nagłówku.
function timelineActor(item: any): string | null {
  if (item.type === "stage_change") return item.moved_by_name ?? null;
  if (item.type === "note") return item.author_name ?? null;
  if (item.type === "activity") return item.user_name ?? null;
  return null;
}

function timelineInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Ikona w kółku dla zdarzeń systemowych/importu (bez ludzkiego autora) —
// utrzymuje skanowalność wiersza wg rodzaju zdarzenia.
function TimelineIcon({ item }: { item: any }) {
  let Icon = MessageSquare;
  if (item.type === "stage_change") Icon = ArrowRight;
  else if (item.type === "activity") {
    const action = typeof item.action === "string" ? item.action : "";
    if (action.includes("Plik")) Icon = FileText;
    else if (action.startsWith("rejection_email")) Icon = Mail;
    else if (action === "applied_via_invite") Icon = UserPlus;
  }
  return <Icon className="h-3.5 w-3.5" />;
}

// Dla każdej zmiany etapu — etap, Z którego nastąpiło przejście, wyliczony z
// chronologicznie wcześniejszej zmiany na TEJ SAMEJ rekrutacji (backend wysyła
// tylko etap docelowy). Pozwala renderować „Nowy → Screening" jak w Traffit.
function buildStageFromMap(items: any[]): Map<number, string> {
  const byJob = new Map<number | string, any[]>();
  for (const it of items) {
    if (it.type !== "stage_change") continue;
    const key = it.job_id ?? "—";
    const arr = byJob.get(key);
    if (arr) arr.push(it);
    else byJob.set(key, [it]);
  }
  const fromMap = new Map<number, string>();
  for (const group of byJob.values()) {
    const asc = [...group].sort((a, b) =>
      String(a.timestamp ?? "").localeCompare(String(b.timestamp ?? "")),
    );
    for (let i = 1; i < asc.length; i++) {
      if (asc[i].id != null) fromMap.set(asc[i].id, asc[i - 1].stage);
    }
  }
  return fromMap;
}

// Nagłówek karty: pogrubiony autor + co zrobił. Dla zmian etapu kolorowe
// badge'y „z → do" renderuje TimelineCard w osobnym wierszu.
function TimelineHeadline({
  item,
  fromStage,
}: {
  item: any;
  fromStage?: string;
}) {
  const actor = timelineActor(item);
  if (item.type === "stage_change") {
    return (
      <span className="text-sm text-foreground">
        <span className="font-semibold">{actor ?? "System"}</span>
        <span className="text-muted-foreground">
          {" · "}
          {fromStage ? "zmiana etapu" : "przypisanie do etapu"}
        </span>
      </span>
    );
  }
  if (item.type === "note") {
    return (
      <span className="text-sm text-foreground">
        {actor ? (
          <>
            <span className="font-semibold">{actor}</span>
            <span className="text-muted-foreground"> · notatka</span>
          </>
        ) : (
          <span className="font-semibold">Notatka</span>
        )}
      </span>
    );
  }
  return (
    <span className="text-sm font-medium text-foreground">
      {timelineItemLabel(item)}
    </span>
  );
}

function TimelineCard({ item, fromStage }: { item: any; fromStage?: string }) {
  const actor = timelineActor(item);
  const useAvatar =
    !!actor && (item.type === "stage_change" || item.type === "note");
  const content = item.content
    ? unwrapNoteContent(item.content_rendered ?? item.content)
    : null;
  const isStage = item.type === "stage_change";
  return (
    <div className="flex gap-3 rounded-xl border border-border bg-card px-3.5 py-3 shadow-xs transition-shadow hover:shadow-md">
      {useAvatar ? (
        <Avatar className="h-8 w-8 shrink-0">
          <AvatarFallback className="bg-primary/10 text-[11px] font-semibold text-primary">
            {timelineInitials(actor as string)}
          </AvatarFallback>
        </Avatar>
      ) : (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <TimelineIcon item={item} />
        </div>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <TimelineHeadline item={item} fromStage={fromStage} />
          </div>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {timelineTime(item.timestamp)}
          </span>
        </div>

        {isStage && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {fromStage ? (
              <>
                <StageBadge stage={fromStage} />
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                <StageBadge stage={item.stage} />
              </>
            ) : (
              <StageBadge stage={item.stage} />
            )}
          </div>
        )}

        {item.job_title && (
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {item.job_title}
          </p>
        )}

        {content && (
          <p className="mt-1.5 whitespace-pre-line text-sm text-foreground">
            {content}
          </p>
        )}

        {item.notes && (
          <p className="mt-1.5 whitespace-pre-line rounded-md bg-muted/50 px-2.5 py-1.5 text-sm italic text-muted-foreground">
            {item.notes}
          </p>
        )}

        {item.rating ? (
          <div className="mt-1.5 flex gap-0.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <Star
                key={n}
                className={cn(
                  "h-3.5 w-3.5",
                  n <= item.rating
                    ? "fill-warning text-warning"
                    : "fill-[hsl(var(--border))] text-[hsl(var(--border))]",
                )}
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function TimelineTab({ items }: { items: any[] }) {
  const { groups, fromMap } = useMemo(() => {
    const list = Array.isArray(items) ? items : [];
    const stageFrom = buildStageFromMap(list);
    const grouped: { key: string; label: string; items: any[] }[] = [];
    let cur: { key: string; label: string; items: any[] } | null = null;
    for (const item of list) {
      const key = timelineDayKey(item.timestamp);
      if (!cur || cur.key !== key) {
        cur = { key, label: timelineDayLabel(item.timestamp), items: [] };
        grouped.push(cur);
      }
      cur.items.push(item);
    }
    return { groups: grouped, fromMap: stageFrom };
  }, [items]);

  if (!Array.isArray(items) || items.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        Brak zdarzeń w timeline.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <section key={group.key} className="space-y-2">
          <div className="flex items-center gap-2">
            <Calendar className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <h4 className="text-xs font-semibold text-muted-foreground">
              {group.label}
            </h4>
            <div className="h-px flex-1 bg-border" />
          </div>
          {group.items.map((item: any, i: number) => (
            <TimelineCard
              key={`${item.type}-${item.id}-${i}`}
              item={item}
              fromStage={
                item.type === "stage_change" && item.id != null
                  ? fromMap.get(item.id)
                  : undefined
              }
            />
          ))}
        </section>
      ))}
    </div>
  );
}

/**
 * Skrót ostatniej aktywności (1–2 zdarzenia) — prawa kolumna zakładki
 * „Profil”. Pełna oś czasu żyje w zakładce „Historia”.
 */
export function RecentActivityList({ items }: { items: any[] }) {
  if (!Array.isArray(items) || items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">Brak zdarzeń.</p>
    );
  }
  return (
    <ul className="divide-y divide-border/60">
      {items.map((item: any, i: number) => {
        const content = item.content
          ? unwrapNoteContent(item.content_rendered ?? item.content)
          : "";
        return (
          <li key={`${item.type}-${item.id}-${i}`} className="py-2 first:pt-0 last:pb-0">
            <div className="flex items-baseline gap-2">
              <span className="min-w-0 truncate text-xs font-medium text-foreground">
                {timelineItemLabel(item)}
              </span>
              <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                {item.timestamp ? formatRelativeTime(item.timestamp) : ""}
              </span>
            </div>
            {content ? (
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {content}
              </p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
