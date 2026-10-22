"use client";

/**
 * „Porównaj” w zakładce „Podobni” (22.10.2026): dwie kolumny obok siebie,
 * żeby rekruter sam ocenił, czy podobieństwo jest prawdziwe. Fakty obu osób
 * liczy serwer tą samą regułą (`SimilarPerson`), umiejętności to nazwy
 * kanoniczne (wspólne i tylko u jednej osoby). Porównanie nie mówi, czy osoba
 * pasuje do rekrutacji — to sprawdza „Przypisz”.
 */

import type { ReactNode } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, ExternalLink, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { AvailabilityPill } from "@/components/ds/AvailabilityPill";
import {
  SIMILARITY_LEVEL_LABEL,
  type SimilarCandidate,
  type SimilarPerson,
} from "@/lib/api/similarCandidates";
import {
  personFirstName,
  personName,
  prettySkill,
  rateText,
  sharedSkillsText,
} from "@/lib/similar-candidates-view";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";
import { formatDate } from "@/lib/utils";

interface SimilarCompareSheetProps {
  source: SimilarPerson;
  person: SimilarCandidate;
  position: number;
  total: number;
  dictionary: Map<string, string>;
  onPrev?: () => void;
  onNext?: () => void;
  onClose: () => void;
  onAssign?: () => void;
}

function placeText(p: SimilarPerson): string {
  return formatCandidateLocation(p.city) ?? formatCandidateLocation(p.location) ?? "—";
}

function availabilityDate(p: SimilarPerson): string {
  return p.availability_date ? `od ${formatDate(p.availability_date)}` : "nie ustalono";
}

function processText(p: SimilarPerson): string {
  if (p.active_processes === 0) return "nie";
  return p.active_processes === 1 ? "1 rekrutacja" : `${p.active_processes} rekrutacje`;
}

function SkillChips({
  skills,
  dictionary,
  tone,
}: {
  skills: string[];
  dictionary: Map<string, string>;
  tone: "shared" | "only";
}) {
  if (skills.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {skills.map((skill) => (
        <span
          key={skill}
          className={
            tone === "shared"
              ? "inline-flex h-5 items-center rounded-md border border-primary/25 bg-primary/5 px-1.5 text-[11px] text-primary"
              : "inline-flex h-5 items-center rounded-md border border-dashed border-border px-1.5 text-[11px] text-muted-foreground"
          }
        >
          {prettySkill(skill, dictionary)}
        </span>
      ))}
    </div>
  );
}

function Row({ label, left, right }: { label: string; left: ReactNode; right: ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)_minmax(0,1fr)] gap-3 border-t border-border py-2 text-sm first:border-t-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="min-w-0">{left}</div>
      <div className="min-w-0">{right}</div>
    </div>
  );
}

export function SimilarCompareSheet({
  source,
  person,
  position,
  total,
  dictionary,
  onPrev,
  onNext,
  onClose,
  onAssign,
}: SimilarCompareSheetProps) {
  const sourceFirst = personFirstName(source);
  const first = personFirstName(person);
  const rateDiffers =
    source.rate_hourly != null &&
    person.rate_hourly != null &&
    Math.round(source.rate_hourly) !== Math.round(person.rate_hourly);
  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent side="right" size="xl">
        <SheetHeader>
          <div className="flex items-center justify-between gap-2 pr-8">
            <SheetTitle>Porównanie</SheetTitle>
            <div className="flex items-center gap-1.5">
              <Button size="sm" variant="outline" onClick={onPrev} disabled={!onPrev} aria-label="Poprzednia osoba">
                <ChevronLeft className="h-4 w-4" aria-hidden />
              </Button>
              <span className="text-xs text-muted-foreground">
                {position + 1} z {total}
              </span>
              <Button size="sm" variant="outline" onClick={onNext} disabled={!onNext} aria-label="Następna osoba">
                <ChevronRight className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>
          <SheetDescription>
            <strong className="text-foreground">{SIMILARITY_LEVEL_LABEL[person.level]}.</strong>{" "}
            {first} i {sourceFirst}: {sharedSkillsText(person.shared_skills.length)}
            {person.title ? `; ostatnie stanowisko: ${person.title}` : ""}.
          </SheetDescription>
        </SheetHeader>
        <SheetBody>
          <div className="grid grid-cols-[7.5rem_minmax(0,1fr)_minmax(0,1fr)] gap-3 pb-2 text-sm font-semibold">
            <span />
            <span className="truncate">{personName(source)}</span>
            <span className="truncate">{personName(person)}</span>
          </div>
          <Row label="Ostatnie stanowisko" left={source.title ?? "—"} right={person.title ?? "—"} />
          <Row
            label="Doświadczenie"
            left={source.years_it_experience != null ? `${source.years_it_experience} lat` : "—"}
            right={person.years_it_experience != null ? `${person.years_it_experience} lat` : "—"}
          />
          <Row
            label="Kategoria"
            left={source.competence_category ?? "—"}
            right={person.competence_category ?? "—"}
          />
          <Row
            label={`Wspólne · ${person.shared_skills.length}`}
            left={<SkillChips skills={person.shared_skills} dictionary={dictionary} tone="shared" />}
            right={<span className="text-xs text-muted-foreground">te same co obok</span>}
          />
          <Row
            label="Tylko u jednej osoby"
            left={<SkillChips skills={person.only_source_skills} dictionary={dictionary} tone="only" />}
            right={<SkillChips skills={person.only_candidate_skills} dictionary={dictionary} tone="only" />}
          />
          <Row
            label="Stawka od"
            left={rateText(source.rate_hourly, source.rate_currency)}
            right={
              <span className={rateDiffers ? "font-medium text-warning-muted-foreground" : undefined}>
                {rateText(person.rate_hourly, person.rate_currency)}
              </span>
            }
          />
          <Row
            label="Dostępność"
            left={
              <div className="space-y-0.5">
                <AvailabilityPill status={source.availability_status} appearance="text" />
                <div>{availabilityDate(source)}</div>
              </div>
            }
            right={
              <div className="space-y-0.5">
                <AvailabilityPill status={person.availability_status} appearance="text" />
                <div>{availabilityDate(person)}</div>
              </div>
            }
          />
          <Row label="Miejsce" left={placeText(source)} right={placeText(person)} />
          <Row label="W procesie" left={processText(source)} right={processText(person)} />
          <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
            Podobieństwo nie mówi, czy {first} pasuje do którejś rekrutacji — to sprawdza „Przypisz
            do rekrutacji”.
          </p>
        </SheetBody>
        <SheetFooter className="flex-wrap gap-2 sm:justify-start">
          {onAssign ? (
            <Button onClick={onAssign}>
              <UserPlus className="h-4 w-4" aria-hidden />
              Przypisz do rekrutacji…
            </Button>
          ) : null}
          <Button variant="outline" asChild>
            <Link href={`/candidates/${person.id}`} target="_blank" rel="noopener noreferrer">
              Otwórz profil
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </Link>
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
