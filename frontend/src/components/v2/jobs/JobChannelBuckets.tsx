"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import {
  CHANNEL_LABELS,
  channelBuckets,
  fetchJobNewProfiles,
  fetchUnassignedWorkers,
  jobNewProfilesKey,
  joinChannel,
  newProfilesText,
  parsePlanInput,
  planShortfall,
  setChannelPlan,
  setRecruiterChannel,
  unassignedWorkersKey,
  type ChannelPlan,
  type RecruiterChannel,
} from "@/lib/job-channels";
import { assignedByCaption, type JobRecruiter } from "@/lib/job-team";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChannelBadge } from "./ChannelBadge";
import { RecruiterChips } from "./RecruiterChips";
import type { RecruiterActions } from "./useRecruiterActions";

const LINK = "hit-area text-[11px] font-medium text-primary hover:underline disabled:pointer-events-none disabled:opacity-50";

const OTHER: Record<RecruiterChannel, RecruiterChannel> = { base: "linkedin", linkedin: "base" };

const JOIN_LABEL: Record<RecruiterChannel, string> = {
  base: "Dołącz do bazy",
  linkedin: "Dołącz do LinkedIna",
};

const MOVE_LABEL: Record<RecruiterChannel, string> = {
  base: "→ Baza",
  linkedin: "→ LinkedIn",
};

export interface JobChannelBucketsProps {
  jobId: number;
  /** Pracujący (bez propozycji automatu) — `workingRecruiters(recruitersOf(job))`. */
  working: readonly JobRecruiter[];
  plan: ChannelPlan;
  /** Olaf / Delivery Lead / admin: przenosi każdego i ustawia plan. */
  canStaff: boolean;
  /** Zalogowana osoba może dołączyć do zespołu (rola rekrutera, nie jest w zespole). */
  canJoin: boolean;
  meId: number | null;
  run: RecruiterActions["run"];
  pending: string | null;
  onRemove: (person: JobRecruiter) => void;
  canRemove: (person: JobRecruiter) => boolean;
}

/**
 * Zespół rekrutacji w dwóch koszykach: „Baza” i „LinkedIn” (decyzja Artura
 * 06.11.2026, wariant B). Pusty koszyk z planem świeci na bursztynowo; osoby
 * bez wybranego koszyka stoją pod spodem z przyciskami wyboru. Rekruter
 * spoza zespołu, który rusza karty, jest tu tylko ostrzeżeniem — bez blokady.
 */
export function JobChannelBuckets({
  jobId,
  working,
  plan,
  canStaff,
  canJoin,
  meId,
  run,
  pending,
  onRemove,
  canRemove,
}: JobChannelBucketsProps) {
  const buckets = channelBuckets(working);
  const canMove = (person: JobRecruiter) => canStaff || person.user_id === meId;

  const move = (person: JobRecruiter, channel: RecruiterChannel) =>
    run(`channel:${person.user_id}`, () => setRecruiterChannel(jobId, person.user_id, channel), {
      done:
        person.user_id === meId
          ? `Pracujesz teraz w koszyku „${CHANNEL_LABELS[channel]}”.`
          : `${person.name}: koszyk „${CHANNEL_LABELS[channel]}”.`,
      failed: "Nie udało się zmienić koszyka.",
    });

  const caption = (person: JobRecruiter, target: RecruiterChannel[]): ReactNode => {
    const note = assignedByCaption(person);
    const moves = canMove(person) ? target : [];
    if (!note && moves.length === 0) return null;
    return (
      <span className="inline-flex flex-wrap items-center gap-x-2">
        {note}
        {moves.map((channel) => (
          <button
            key={channel}
            type="button"
            className={LINK}
            disabled={pending != null}
            aria-label={`Przenieś ${person.name} do koszyka ${CHANNEL_LABELS[channel]}`}
            onClick={() => void move(person, channel)}
          >
            {MOVE_LABEL[channel]}
          </button>
        ))}
      </span>
    );
  };

  return (
    <div className="space-y-2" data-testid="job-channel-buckets">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(["base", "linkedin"] as const).map((channel) => {
          const people = buckets[channel];
          const missing = planShortfall(plan[channel], people.length);
          return (
            <section
              key={channel}
              aria-label={`Koszyk ${CHANNEL_LABELS[channel]}`}
              data-testid={`channel-bucket-${channel}`}
              className={cn(
                "min-w-0 space-y-1.5 rounded-md border p-2",
                missing > 0 ? "border-warning/40 bg-warning-muted" : "border-border",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <ChannelBadge channel={channel} />
                {plan[channel] != null ? (
                  <span
                    className={cn(
                      "text-[11px]",
                      missing > 0 ? "font-semibold text-warning-muted-foreground" : "text-muted-foreground",
                    )}
                  >
                    {people.length} z {plan[channel]}
                  </span>
                ) : null}
              </div>
              {people.length > 0 ? (
                <RecruiterChips
                  people={people}
                  size="sm"
                  label={`Koszyk ${CHANNEL_LABELS[channel]}`}
                  caption={(person) => caption(person, [OTHER[channel]])}
                  onRemove={onRemove}
                  canRemove={canRemove}
                />
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  {missing > 0 ? `Brakuje: ${countPl(missing, "osoba", "osoby", "osób")}.` : "Nikt."}
                </p>
              )}
              {canJoin && meId != null ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  loading={pending === `join:${channel}`}
                  disabled={pending != null}
                  onClick={() =>
                    void run(`join:${channel}`, () => joinChannel(jobId, meId, channel), {
                      done: `Dołączono do koszyka „${CHANNEL_LABELS[channel]}”.`,
                      failed: "Nie udało się dołączyć do rekrutacji.",
                    })
                  }
                >
                  {JOIN_LABEL[channel]}
                </Button>
              ) : null}
            </section>
          );
        })}
      </div>

      <NewProfilesNote jobId={jobId} />

      {buckets.none.length > 0 ? (
        <section aria-label="Bez koszyka" className="space-y-1" data-testid="channel-bucket-none">
          <p className="text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
            Bez koszyka
          </p>
          <RecruiterChips
            people={buckets.none}
            size="sm"
            label="Bez koszyka"
            caption={(person) => caption(person, ["base", "linkedin"])}
            onRemove={onRemove}
            canRemove={canRemove}
          />
        </section>
      ) : null}

      {canStaff ? <PlanEditor jobId={jobId} plan={plan} run={run} pending={pending} /> : null}
      <UnassignedNotice jobId={jobId} canStaff={canStaff} run={run} pending={pending} />
    </div>
  );
}

function NewProfilesNote({ jobId }: { jobId: number }) {
  const { data, isSuccess } = useQuery({
    queryKey: jobNewProfilesKey(jobId),
    queryFn: () => fetchJobNewProfiles(jobId),
    staleTime: 60_000,
  });
  // Pomiar jest dodatkiem: przy błędzie nie pokazujemy „0”, tylko nic.
  if (!isSuccess) return null;
  return (
    <p
      className="text-[11px] text-muted-foreground"
      data-testid="job-new-profiles"
      title="Profile założone przez rekrutera pod tę rekrutację (najwyżej dzień przed dodaniem karty), bez portali i poleceń."
    >
      {newProfilesText(data.added, data.reached_cv)}
    </p>
  );
}

function PlanEditor({
  jobId,
  plan,
  run,
  pending,
}: {
  jobId: number;
  plan: ChannelPlan;
  run: RecruiterActions["run"];
  pending: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [base, setBase] = useState("");
  const [linkedin, setLinkedin] = useState("");
  const basePlanInput = parsePlanInput(base);
  const liPlanInput = parsePlanInput(linkedin);
  const invalid = basePlanInput === "invalid" || liPlanInput === "invalid";

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setBase(plan.base == null ? "" : String(plan.base));
          setLinkedin(plan.linkedin == null ? "" : String(plan.linkedin));
        }
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <button type="button" className={LINK} disabled={pending != null}>
          {plan.base == null && plan.linkedin == null ? "Ustaw plan koszyków" : "Zmień plan koszyków"}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 space-y-2">
        <p className="text-xs text-muted-foreground">Ile osób ma pracować w każdym koszyku. Puste = bez planu.</p>
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1 text-xs font-medium">
            <span>Baza</span>
            <Input
              id={`plan-base-${jobId}`}
              inputMode="numeric"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              aria-invalid={basePlanInput === "invalid"}
            />
          </label>
          <label className="space-y-1 text-xs font-medium">
            <span>LinkedIn</span>
            <Input
              id={`plan-linkedin-${jobId}`}
              inputMode="numeric"
              value={linkedin}
              onChange={(e) => setLinkedin(e.target.value)}
              aria-invalid={liPlanInput === "invalid"}
            />
          </label>
        </div>
        {invalid ? (
          <p className="text-[11px] text-destructive">Wpisz liczbę od 0 do 20 albo zostaw puste.</p>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="primary"
          disabled={invalid || pending != null}
          loading={pending === "plan"}
          onClick={() => {
            if (invalid) return;
            setOpen(false);
            void run(
              "plan",
              () =>
                setChannelPlan(jobId, {
                  base: basePlanInput as number | null,
                  linkedin: liPlanInput as number | null,
                }),
              { done: "Zapisano plan koszyków.", failed: "Nie udało się zapisać planu koszyków." },
            );
          }}
        >
          Zapisz plan
        </Button>
      </PopoverContent>
    </Popover>
  );
}

function UnassignedNotice({
  jobId,
  canStaff,
  run,
  pending,
}: {
  jobId: number;
  canStaff: boolean;
  run: RecruiterActions["run"];
  pending: string | null;
}) {
  const { data, isSuccess } = useQuery({
    queryKey: unassignedWorkersKey(jobId),
    queryFn: () => fetchUnassignedWorkers(jobId),
    staleTime: 60_000,
  });
  // Ostrzeżenie jest dodatkiem: przy błędzie zapytania nic nie pokazujemy,
  // bo pusta lista nie wygląda tu jak „nikogo nie ma” — po prostu nie ma ramki.
  if (!isSuccess || data.length === 0) return null;
  return (
    <section
      aria-label="Pracują bez przypisania"
      data-testid="unassigned-workers"
      className="space-y-1 rounded-md border border-warning/40 bg-warning-muted p-2 text-xs text-warning-muted-foreground"
    >
      <p className="flex items-center gap-1 font-semibold">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
        Pracują bez przypisania
      </p>
      <ul className="space-y-1">
        {data.map((worker) => (
          <li key={worker.user_id} className="flex flex-wrap items-center gap-x-2">
            <span className="font-medium text-foreground">{worker.name}</span>
            <span>
              {countPl(worker.cards, "karta", "karty", "kart")} w 30 dni
            </span>
            {canStaff
              ? (["base", "linkedin"] as const).map((channel) => (
                  <button
                    key={channel}
                    type="button"
                    className={LINK}
                    disabled={pending != null}
                    onClick={() =>
                      void run(`unassigned:${worker.user_id}`, () => joinChannel(jobId, worker.user_id, channel), {
                        done: `${worker.name}: dodano do koszyka „${CHANNEL_LABELS[channel]}”.`,
                        failed: "Nie udało się dodać osoby do rekrutacji.",
                      })
                    }
                  >
                    {channel === "base" ? "Do bazy" : "Do LinkedIna"}
                  </button>
                ))
              : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
