"use client"

import { CheckCircle2, Filter, Inbox, Target, Users } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  EmptyState,
  FunnelChart,
  Leaderboard,
  MatchCard,
  MatchList,
  PageHeader,
  Podium,
  StatCard,
  StatCardGrid,
  type DataTableColumn,
} from "@/components/ds"

interface Candidate {
  id: number
  name: string
  role: string
  stage: string
  me: boolean
}

const CANDIDATES: Candidate[] = [
  { id: 1, name: "Jan Kowalski", role: "Senior React Developer", stage: "Interview", me: false },
  { id: 2, name: "Marta Nowak", role: "Data Engineer", stage: "Rekomendacja", me: true },
  { id: 3, name: "Piotr Wiśniewski", role: "DevOps Engineer", stage: "Oferta", me: false },
  { id: 4, name: "Karolina Wójcik", role: "QA Automation", stage: "Weryfikacja", me: false },
]

const COLUMNS: DataTableColumn<Candidate>[] = [
  { key: "name", header: "Kandydat", render: (r) => <span className="font-medium text-foreground">{r.name}</span> },
  { key: "role", header: "Stanowisko", render: (r) => <span className="text-muted-foreground">{r.role}</span> },
  { key: "stage", header: "Etap", render: (r) => <Badge variant="soft" size="sm">{r.stage}</Badge> },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      {children}
    </section>
  )
}

export default function DsKitPreview() {
  return (
    <div className="min-h-screen bg-background app-shell-root">
      <div className="mx-auto max-w-[1120px] space-y-10 px-6 py-8">
        <PageHeader
          eyebrow="DYNAMINDS DS"
          title="Kit komponentów"
          description="Galeria komponentów warstwy ds/ — wszystkie na semantycznych tokenach NEXUSa."
          breadcrumb={[{ label: "Preview", href: "#" }, { label: "DS Kit" }]}
          actions={<Button size="sm">Akcja</Button>}
        />

        <Section title="StatCardGrid + StatCard">
          <StatCardGrid>
            <StatCard label="Weryfikacje" value={540} delta={12} sub="Ja 86 · cel 75" icon={Filter} spark={[40, 42, 38, 45, 44, 50, 52, 58]} />
            <StatCard label="Rekomendacje" value={210} delta={8} sub="Ja 31" icon={Users} spark={[22, 20, 24, 23, 26, 25, 28, 30]} />
            <StatCard label="Interviews" value={96} delta={-3} sub="Ja 14" icon={CheckCircle2} spark={[19, 18, 20, 17, 18, 16, 15, 14]} />
            <StatCard label="Placements" value={38} delta={18} sub="Ja 6" icon={Target} spark={[3, 4, 3, 5, 4, 6, 5, 6]} />
          </StatCardGrid>
        </Section>

        <Section title="FunnelChart + Podium">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
            <div className="lg:col-span-3">
              <FunnelChart
                title="Lejek rekrutacyjny"
                summary="Wer → Plac · 7,0%"
                stages={[
                  { label: "Weryfikacje", count: 540, conv: "100%" },
                  { label: "Rekomendacje", count: 210, conv: "39%" },
                  { label: "Interviews", count: 96, conv: "46%" },
                  { label: "Placements", count: 38, conv: "40%" },
                ]}
              />
            </div>
            <div className="lg:col-span-2">
              <Podium
                title="Liga Mistrzów"
                entries={[
                  { rank: 1, name: "Anna Kowalska", points: 1240 },
                  { rank: 2, name: "Piotr Zieliński", points: 1080 },
                  { rank: 3, name: "Marta Nowak", points: 960, me: true },
                ]}
              />
            </div>
          </div>
        </Section>

        <Section title="Leaderboard">
          <Leaderboard
            title="Zespół"
            metricLabel="Placements"
            rows={[
              { name: "Anna Kowalska", metric: 9 },
              { name: "Piotr Zieliński", metric: 7 },
              { name: "Marta Nowak", metric: 6, me: true },
              { name: "Tomasz Lis", metric: 4 },
            ]}
          />
        </Section>

        <Section title="DataTable">
          <DataTable
            columns={COLUMNS}
            rows={CANDIDATES}
            getRowKey={(r) => r.id}
            rowHighlighted={(r) => r.me}
          />
        </Section>

        <Section title="MatchList + MatchCard">
          <MatchList>
            <MatchCard
              name="Jan Kowalski"
              role="Senior React Developer"
              score={88}
              reasons={[
                { label: "React", ok: true },
                { label: "TypeScript", ok: true },
                { label: "AWS", ok: false },
              ]}
              actions={<Button size="sm" variant="outline">Dodaj do pipeline</Button>}
            />
            <MatchCard
              name="Marta Nowak"
              role="Data Engineer"
              score={72}
              reasons={[
                { label: "Python", ok: true },
                { label: "Spark", ok: true },
                { label: "Kafka", ok: false },
              ]}
              actions={<Button size="sm" variant="outline">Dodaj do pipeline</Button>}
            />
          </MatchList>
        </Section>

        <Section title="EmptyState">
          <div className="rounded-lg border border-border bg-card">
            <EmptyState
              icon={Inbox}
              title="Brak kandydatów"
              description="Dodaj pierwszego kandydata, aby zacząć budować pipeline."
              action={<Button size="sm">Dodaj kandydata</Button>}
            />
          </div>
        </Section>
      </div>
    </div>
  )
}
