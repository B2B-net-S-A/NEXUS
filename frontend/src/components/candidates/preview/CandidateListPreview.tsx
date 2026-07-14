"use client"

import * as React from "react"
import {
  BriefcaseBusiness,
  Columns3,
  FileText,
  Filter,
  Mail,
  MapPin,
  MoreHorizontal,
  Phone,
} from "lucide-react"

import { EntityHeader, FilterBar, MatchScoreBadge } from "@/components/ds"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import {
  CANDIDATE_PREVIEW_FIXTURES,
  type CandidatePreviewFixture,
} from "./fixtures"

function statusVariant(status: CandidatePreviewFixture["status"]) {
  if (status === "Aktywny") return "success" as const
  if (status === "W procesie") return "warning" as const
  return "neutral" as const
}

export function CandidateListPreview() {
  const [search, setSearch] = React.useState("")
  const normalizedSearch = search.trim().toLocaleLowerCase("pl")
  const candidates = CANDIDATE_PREVIEW_FIXTURES.filter((candidate) =>
    `${candidate.name} ${candidate.title} ${candidate.location}`
      .toLocaleLowerCase("pl")
      .includes(normalizedSearch),
  )

  return (
    <div className="space-y-4">
      <FilterBar
        variant="sticky"
        search={{
          value: search,
          onChange: setSearch,
          onClear: () => setSearch(""),
          onSubmit: () => undefined,
          placeholder: "Szukaj kandydata, stanowiska lub lokalizacji…",
        }}
        filters={
          <Button variant="outline" size="sm">
            <Filter aria-hidden className="size-4" />
            Filtry
          </Button>
        }
        actions={
          <Button variant="outline" size="sm">
            <Columns3 aria-hidden className="size-4" />
            Kolumny
          </Button>
        }
        resultCount={candidates.length}
        chips={[
          { id: "status", label: "Status: Aktywny", onRemove: () => undefined },
          { id: "availability", label: "Dostępność: do 30 dni", onRemove: () => undefined },
        ]}
        onClearAll={() => undefined}
      />

      <div className="hidden overflow-hidden rounded-lg border border-border bg-card lg:block">
        <div className="overflow-x-auto">
          <table className="min-w-[1100px] w-full border-collapse">
            <thead className="bg-muted/60">
              <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
                <th className="sticky left-0 z-10 min-w-[250px] bg-muted px-4 py-3">Kandydat</th>
                <th className="min-w-[220px] px-4 py-3">Kontakt i CV</th>
                <th className="min-w-[180px] px-4 py-3">Status i dostępność</th>
                <th className="min-w-[220px] px-4 py-3">Proces</th>
                <th className="min-w-[140px] px-4 py-3">Stawka</th>
                <th className="min-w-[200px] px-4 py-3">Ostatnia aktywność</th>
                <th className="w-12 px-3 py-3"><span className="sr-only">Akcje</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {candidates.map((candidate) => (
                <tr key={candidate.id} className="group transition-colors hover:bg-accent/60">
                  <td className="sticky left-0 z-10 bg-card px-4 py-3 group-hover:bg-accent">
                    <div className="flex items-center gap-3">
                      <Avatar size="sm">
                        <AvatarFallback>{candidate.initials}</AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <button type="button" className="block max-w-[190px] truncate text-left text-sm font-semibold text-foreground hover:underline">
                          {candidate.name}
                        </button>
                        <p className="max-w-[190px] truncate text-xs text-muted-foreground">{candidate.title}</p>
                        <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                          <MapPin aria-hidden className="size-3" /> {candidate.location}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    <p className="flex items-center gap-1.5"><Mail aria-hidden className="size-3.5" />{candidate.email}</p>
                    <p className="mt-1 flex items-center gap-1.5"><Phone aria-hidden className="size-3.5" />{candidate.phone}</p>
                    <p className="mt-1 flex items-center gap-1.5"><FileText aria-hidden className="size-3.5" />{candidate.cvName ?? "Brak CV"}</p>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(candidate.status)}>{candidate.status}</Badge>
                    <p className="mt-1.5 text-xs text-muted-foreground">{candidate.availability}</p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="flex items-center gap-1.5 text-sm font-medium text-foreground"><BriefcaseBusiness aria-hidden className="size-3.5" />{candidate.recruitment}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{candidate.stage}</p>
                  </td>
                  <td className="px-4 py-3 text-sm font-medium text-foreground">{candidate.rate}</td>
                  <td className="px-4 py-3">
                    <p className="text-xs text-muted-foreground">{candidate.lastActivity}</p>
                    {typeof candidate.score === "number" ? <MatchScoreBadge score={candidate.score} size="sm" className="mt-1.5" /> : null}
                  </td>
                  <td className="px-3 py-3">
                    <Button variant="ghost" size="icon-sm" aria-label={`Akcje: ${candidate.name}`}>
                      <MoreHorizontal aria-hidden className="size-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid gap-3 lg:hidden">
        {candidates.map((candidate) => (
          <article key={candidate.id} className="rounded-lg border border-border bg-card p-4">
            <EntityHeader
              density="compact"
              headingLevel={2}
              avatar={<Avatar><AvatarFallback>{candidate.initials}</AvatarFallback></Avatar>}
              title={candidate.name}
              subtitle={candidate.title}
              badges={<Badge variant={statusVariant(candidate.status)}>{candidate.status}</Badge>}
              metadata={<span className="flex items-center gap-1"><MapPin aria-hidden className="size-3.5" />{candidate.location}</span>}
            />
            <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
              <div><dt className="text-muted-foreground">Dostępność</dt><dd className="mt-0.5 font-medium text-foreground">{candidate.availability}</dd></div>
              <div><dt className="text-muted-foreground">Stawka</dt><dd className="mt-0.5 font-medium text-foreground">{candidate.rate}</dd></div>
              <div className="col-span-2"><dt className="text-muted-foreground">Proces</dt><dd className="mt-0.5 font-medium text-foreground">{candidate.recruitment} · {candidate.stage}</dd></div>
            </dl>
            <div className={cn("mt-4 flex items-center", typeof candidate.score === "number" ? "justify-between" : "justify-end")}>
              {typeof candidate.score === "number" ? <MatchScoreBadge score={candidate.score} size="sm" /> : null}
              <Button variant="outline" size="sm">Podgląd</Button>
            </div>
          </article>
        ))}
      </div>

      {candidates.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-card px-6 py-12 text-center">
          <p className="font-medium text-foreground">Brak kandydatów</p>
          <p className="mt-1 text-sm text-muted-foreground">Zmień wyszukiwanie lub wyczyść filtry.</p>
        </div>
      ) : null}
    </div>
  )
}
