"use client"

import * as React from "react"
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  BriefcaseBusiness,
  CalendarClock,
  ExternalLink,
  FileText,
  Linkedin,
  Mail,
  MapPin,
  MessageSquareText,
  Phone,
  ShieldCheck,
  Sparkles,
  WalletCards,
  X,
} from "lucide-react"

import {
  EntityHeader,
  KeyFacts,
  MatchScoreBadge,
  TabbedNav,
  type KeyFact,
} from "@/components/ds"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { TabsContent } from "@/components/ui/tabs"

import {
  CANDIDATE_PREVIEW_ACTIVITIES,
  CANDIDATE_PREVIEW_FIXTURES,
  CANDIDATE_PREVIEW_RECOMMENDATIONS,
} from "./fixtures"

const PROFILE_TABS = [
  { value: "summary", label: "Podsumowanie" },
  { value: "recruitments", label: "Rekrutacje", count: 2 },
  { value: "activity", label: "Aktywność", count: 12 },
  { value: "matching", label: "Dopasowanie", count: 2 },
  { value: "documents", label: "Pliki i umowy", count: 3 },
]

const candidate = CANDIDATE_PREVIEW_FIXTURES[0]

const FACTS: KeyFact[] = [
  { id: "availability", label: "Dostępność", value: candidate.availability, icon: CalendarClock },
  { id: "rate", label: "Oczekiwana stawka", value: candidate.rate, icon: WalletCards },
  { id: "location", label: "Lokalizacja", value: candidate.location, icon: MapPin },
  { id: "source", label: "Źródło", value: "Polecenie · Anna Kowalska" },
  { id: "owner", label: "Opiekun", value: "Marta Nowak" },
  { id: "contact", label: "Ostatni kontakt", value: "Dzisiaj, 09:42" },
]

function CandidateIdentity({ compact = false }: { compact?: boolean }) {
  return (
    <EntityHeader
      density={compact ? "compact" : "default"}
      headingLevel={compact ? 2 : 1}
      avatar={
        <Avatar size={compact ? "lg" : "xl"}>
          <AvatarFallback>{candidate.initials}</AvatarFallback>
        </Avatar>
      }
      title={candidate.name}
      subtitle={candidate.title}
      badges={
        <>
          <Badge variant="success">Aktywny</Badge>
          <Badge variant="success"><ShieldCheck aria-hidden className="size-3" />Niskie ryzyko</Badge>
        </>
      }
      metadata={
        <>
          <a href={`mailto:${candidate.email}`} className="flex items-center gap-1.5 hover:text-foreground"><Mail aria-hidden className="size-3.5" />{candidate.email}</a>
          <a href={`tel:${candidate.phone.replace(/\s/g, "")}`} className="flex items-center gap-1.5 hover:text-foreground"><Phone aria-hidden className="size-3.5" />{candidate.phone}</a>
          <a href="#linkedin" className="flex items-center gap-1.5 text-brand-linkedin hover:underline"><Linkedin aria-hidden className="size-3.5" />LinkedIn</a>
        </>
      }
      actions={<Button size="sm">Przypisz do rekrutacji</Button>}
    />
  )
}

function Recommendations({ limit = 2 }: { limit?: number }) {
  return (
    <div className="space-y-3">
      {CANDIDATE_PREVIEW_RECOMMENDATIONS.slice(0, limit).map((recommendation) => (
        <article key={recommendation.id} className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-foreground">{recommendation.title}</h3>
              <p className="mt-1 text-xs text-muted-foreground">{recommendation.location} · {recommendation.rate}</p>
            </div>
            <MatchScoreBadge score={recommendation.score} size="sm" />
          </div>
          <dl className="mt-3 space-y-2 text-xs">
            <div><dt className="font-medium text-success-muted-foreground">Mocna strona</dt><dd className="mt-0.5 text-muted-foreground">{recommendation.strength}</dd></div>
            <div><dt className="font-medium text-warning-muted-foreground">Do weryfikacji</dt><dd className="mt-0.5 text-muted-foreground">{recommendation.gap}</dd></div>
          </dl>
          <Button variant="outline" size="sm" className="mt-3">Przypisz do rekrutacji</Button>
        </article>
      ))}
    </div>
  )
}

function Activities() {
  return (
    <ol className="divide-y divide-border rounded-lg border border-border bg-card">
      {CANDIDATE_PREVIEW_ACTIVITIES.map((activity) => (
        <li key={activity.id} className="flex gap-3 p-4">
          <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"><Activity aria-hidden className="size-3.5" /></span>
          <div><p className="text-sm font-medium text-foreground">{activity.title}</p><p className="mt-0.5 text-xs text-muted-foreground">{activity.meta}</p></div>
        </li>
      ))}
    </ol>
  )
}

function QuickViewPreview({ onClose }: { onClose: () => void }) {
  return (
    <section aria-label="Szybki podgląd kandydata" className="ml-auto max-w-3xl overflow-hidden rounded-xl border border-border bg-background shadow-lg">
      <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label="Poprzedni kandydat"><ArrowLeft aria-hidden className="size-4" /></Button>
          <span className="px-2 text-xs tabular-nums text-muted-foreground">1 z 53 783</span>
          <Button variant="ghost" size="icon-sm" aria-label="Następny kandydat"><ArrowRight aria-hidden className="size-4" /></Button>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm">Pełny profil <ExternalLink aria-hidden className="size-3.5" /></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Zamknij szybki podgląd" onClick={onClose}>
            <X aria-hidden className="size-4" />
          </Button>
        </div>
      </div>

      <div className="space-y-6 p-4 sm:p-6">
        <CandidateIdentity compact />
        <KeyFacts facts={FACTS} columns={3} density="compact" />

        <section aria-labelledby="quick-skills">
          <h2 id="quick-skills" className="text-sm font-semibold text-foreground">Kluczowe umiejętności</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">{candidate.skills.map((skill) => <Badge key={skill} variant="neutral">{skill}</Badge>)}</div>
          <p className="mt-3 line-clamp-3 text-sm leading-6 text-muted-foreground">{candidate.summary}</p>
        </section>

        <section aria-labelledby="quick-recruitments">
          <div className="mb-2 flex items-center justify-between"><h2 id="quick-recruitments" className="text-sm font-semibold text-foreground">Aktywne rekrutacje</h2><Badge variant="neutral">2</Badge></div>
          <div className="rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium text-foreground">{candidate.recruitment}</p><p className="mt-1 text-xs text-muted-foreground">{candidate.stage} · zmiana wczoraj</p></div>
        </section>

        <section aria-labelledby="quick-activity"><h2 id="quick-activity" className="mb-2 text-sm font-semibold text-foreground">Ostatnia aktywność</h2><Activities /></section>

        <section aria-labelledby="quick-matches">
          <div className="mb-2 flex items-center gap-2"><Sparkles aria-hidden className="size-4 text-primary" /><h2 id="quick-matches" className="text-sm font-semibold text-foreground">Sugerowane rekrutacje</h2></div>
          <Recommendations />
        </section>
      </div>
    </section>
  )
}

function FullProfilePreview() {
  const [tab, setTab] = React.useState("summary")

  return (
    <section aria-label="Pełny profil kandydata" className="overflow-hidden rounded-xl border border-border bg-background">
      <div className="border-b border-border p-4 sm:p-6"><CandidateIdentity /></div>
      <div className="border-b border-border p-3 md:hidden">
        <label htmlFor="preview-profile-section" className="mb-1 block text-xs font-medium text-muted-foreground">Sekcja profilu</label>
        <select
          id="preview-profile-section"
          value={tab}
          onChange={(event) => setTab(event.target.value)}
          className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm text-foreground"
        >
          {PROFILE_TABS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </div>
      <TabbedNav tabs={PROFILE_TABS} value={tab} onValueChange={setTab} ariaLabel="Sekcje profilu kandydata" overflow="scroll" listClassName="hidden px-3 sm:px-5 md:flex">
        <TabsContent value="summary" className="mt-0 p-4 sm:p-6">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="space-y-6">
              <Card><CardHeader><CardTitle>Najważniejsze informacje</CardTitle></CardHeader><CardContent><KeyFacts facts={FACTS} columns={3} /></CardContent></Card>
              <Card><CardHeader><CardTitle>Podsumowanie AI</CardTitle></CardHeader><CardContent><p className="text-sm leading-6 text-muted-foreground">{candidate.summary}</p><div className="mt-4 flex flex-wrap gap-1.5">{candidate.skills.map((skill) => <Badge key={skill} variant="neutral">{skill}</Badge>)}</div></CardContent></Card>
              <Card><CardHeader><CardTitle>Dane handlowe i administracyjne</CardTitle></CardHeader><CardContent><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm">Dodaj stawkę</Button><Button variant="outline" size="sm">Dodaj konflikt</Button></div></CardContent></Card>
            </div>
            <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start">
              <Card><CardHeader><CardTitle>CV</CardTitle></CardHeader><CardContent><p className="flex items-center gap-2 text-sm text-foreground"><FileText aria-hidden className="size-4 text-muted-foreground" />{candidate.cvName}</p><Button variant="outline" size="sm" className="mt-3">Otwórz CV</Button></CardContent></Card>
              <Card><CardHeader><CardTitle>Ostatnia aktywność</CardTitle></CardHeader><CardContent><Activities /></CardContent></Card>
            </aside>
          </div>
        </TabsContent>
        <TabsContent value="recruitments" className="mt-0 p-4 sm:p-6"><Card><CardHeader><CardTitle>Aktywne procesy</CardTitle></CardHeader><CardContent><p className="flex items-center gap-2 text-sm font-medium text-foreground"><BriefcaseBusiness aria-hidden className="size-4" />{candidate.recruitment}</p><p className="mt-1 text-sm text-muted-foreground">{candidate.stage}</p></CardContent></Card></TabsContent>
        <TabsContent value="activity" className="mt-0 p-4 sm:p-6"><div className="mb-4 flex flex-wrap gap-2"><Button size="sm">Historia</Button><Button variant="outline" size="sm">Notatki</Button><Button variant="outline" size="sm">Rozmowy</Button><Button variant="outline" size="sm"><MessageSquareText aria-hidden className="size-4" />Czat</Button></div><Activities /></TabsContent>
        <TabsContent value="matching" className="mt-0 p-4 sm:p-6"><div className="mb-4"><h2 className="text-lg font-semibold text-foreground">Sugerowane rekrutacje</h2><p className="mt-1 text-sm text-muted-foreground">Dopasowanie oparte na profilu i wymaganiach otwartych procesów.</p></div><div className="grid gap-4 lg:grid-cols-2"><Recommendations /></div></TabsContent>
        <TabsContent value="documents" className="mt-0 p-4 sm:p-6"><div className="grid gap-4 lg:grid-cols-2"><Card><CardHeader><CardTitle>Pliki</CardTitle></CardHeader><CardContent><p className="flex items-center gap-2 text-sm text-foreground"><FileText aria-hidden className="size-4" />{candidate.cvName}</p></CardContent></Card><Card><CardHeader><CardTitle>Umowy</CardTitle></CardHeader><CardContent><p className="text-sm text-muted-foreground">Brak aktywnej umowy.</p></CardContent></Card></div></TabsContent>
      </TabbedNav>
    </section>
  )
}

export function CandidateProfilePreview() {
  const [mode, setMode] = React.useState<"full" | "quick">("full")

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2" aria-label="Wariant podglądu">
        <Button variant={mode === "full" ? "primary" : "outline"} size="sm" aria-pressed={mode === "full"} onClick={() => setMode("full")}>Pełny profil</Button>
        <Button variant={mode === "quick" ? "primary" : "outline"} size="sm" aria-pressed={mode === "quick"} onClick={() => setMode("quick")}>Quick view</Button>
      </div>
      {mode === "full" ? <FullProfilePreview /> : <QuickViewPreview onClose={() => setMode("full")} />}
    </div>
  )
}
