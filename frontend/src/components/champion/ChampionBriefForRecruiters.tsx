"use client";

/**
 * To, co rekruter ma wiedzieć z Profilu Championa poza pytaniami
 * screeningowymi: dziedzina/certyfikaty (sekcja 4) i wiedza z rozmów
 * (sekcja 8 + „Z historii klienta”). Do 09.2026 rekruter widział z Championa
 * wyłącznie pytania — smaczki od klienta i konsultanta leżały w polach, których
 * żaden ekran pracy nie pokazywał.
 *
 * Czyta profil pod TYM SAMYM kluczem co edytor (`["champion-profile", jobId]`),
 * więc po zapisie w edytorze oba widoki są spójne. Tylko odczyt.
 */

import { useQuery } from "@tanstack/react-query";

import {
  championApi,
  type ChampionExperience,
  type ChampionProfile,
  type InsightNote,
} from "@/lib/api";
import {
  EXPERIENCE_KIND_LABEL,
  EXPERIENCE_KINDS,
  experienceItemLabel,
  hasExperience,
} from "@/lib/champion-experience";
import { INSIGHT_SOURCE_LABEL, INSIGHT_TOPIC_LABEL } from "@/lib/champion-insights";
import { cn } from "@/lib/utils";

export function useChampionProfile(jobId: number) {
  return useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
    staleTime: 60_000,
  });
}

export function ExperienceChips({
  experience,
  className,
}: {
  experience: ChampionExperience | undefined;
  className?: string;
}) {
  if (!hasExperience(experience)) return null;
  return (
    <ul
      className={cn("flex flex-wrap gap-1.5", className)}
      aria-label="Doświadczenie poza stackiem"
      data-testid="experience-chips"
    >
      {EXPERIENCE_KINDS.flatMap((kind) =>
        (experience?.[kind] ?? []).map((item) => (
          <li
            key={`${kind}:${item.name}`}
            title={EXPERIENCE_KIND_LABEL[kind]}
            className={cn(
              "inline-flex h-[26px] items-center rounded-full px-2.5 text-xs font-medium",
              item.level === "must"
                ? "border border-primary/30 bg-primary/5 text-primary"
                : "border border-dashed border-border text-muted-foreground",
            )}
          >
            {EXPERIENCE_KIND_LABEL[kind]}: {experienceItemLabel(kind, item)}
            {item.level === "nice" ? " — mile widziane" : ""}
          </li>
        )),
      )}
    </ul>
  );
}

function NoteLine({ note }: { note: InsightNote }) {
  return (
    <li className="text-[13px] text-foreground">
      <span className="text-muted-foreground">
        {INSIGHT_SOURCE_LABEL[note.source]} · {INSIGHT_TOPIC_LABEL[note.topic]}:{" "}
      </span>
      {note.text}
    </li>
  );
}

/**
 * Skrót sekcji 8: do `limit` notatek zespołu, osobno „co mówić kandydatowi”,
 * pierwsze punkty historii klienta. Pusty profil = zdanie zamiast ciszy.
 */
export function ChampionInsightsDigest({
  profile,
  limit = 5,
  historyLimit = 3,
}: {
  profile: Partial<ChampionProfile> | undefined;
  limit?: number;
  historyLimit?: number;
}) {
  const notes = (profile?.insights ?? []).filter(
    (n) => n.topic !== "ask_client" && n.text.trim(),
  );
  const team = notes.filter((n) => n.audience === "team").slice(-limit).reverse();
  const pitch = notes.filter((n) => n.audience === "candidate");
  const history = (profile?.client_history?.items ?? []).slice(0, historyLimit);

  if (team.length === 0 && pitch.length === 0 && history.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Delivery Lead nie zapisał jeszcze notatek z rozmów z klientem ani
        z konsultantem.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3" data-testid="champion-insights-digest">
      {team.length > 0 ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Tylko dla zespołu
          </p>
          <ul className="mt-1 flex flex-col gap-1">
            {team.map((note) => (
              <NoteLine key={note.id} note={note} />
            ))}
          </ul>
        </div>
      ) : null}
      {pitch.length > 0 ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
            Co mówić kandydatowi
          </p>
          <ul className="mt-1 flex flex-col gap-1">
            {pitch.map((note) => (
              <NoteLine key={note.id} note={note} />
            ))}
          </ul>
        </div>
      ) : null}
      {history.length > 0 ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Z historii klienta (AI)
          </p>
          <ul className="mt-1 flex list-disc flex-col gap-1 pl-4">
            {history.map((item, i) => (
              <li key={`${item.text}-${i}`} className="text-[13px] text-foreground">
                {item.text}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
