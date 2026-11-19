"use client";
// B · „Nowy kontrakt” na jednej stronie: po lewej zwarty formularz w trzech
// sekcjach (Strony umowy, Okres, Stawki) + zwinięte „Zaawansowane”, po prawej
// przyklejona karta „Podsumowanie”, która na bieżąco mówi, co powstanie:
// kto → u kogo, od kiedy, stawki, marża na godzinę i w miesiącu i co stanie
// się po kliknięciu („szkic — aktywujesz po podpisaniu umowy”). Dla osób,
// które znają formularz i chcą widzieć całość naraz (admin, Finanse).
//
// Dane jak w wariancie A: para z kontraktu 738 na stagingu, stawki
// z rekrutacji. Nic się nie zapisuje.
import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronRight, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { fmtDate, fmtNum, fmtPln, relDays } from "../shared/format";
import {
  CONTRACT_TYPE_OPTIONS,
  CREATE_AS_OPTIONS,
  FieldLabel,
  MarginStrip,
  MORE_OPTIONS_TITLE,
  MoreOptionsFields,
  PageIntro,
  PickerButton,
  RateInput,
  RecruitmentSelect,
  WORK_MODE_OPTIONS,
  moreOptionsSummary,
  rateToInput,
  useNewContractDraft,
  type ContractTypeKey,
  type CreateAsKey,
  type NewDraft,
  type WorkModeKey,
} from "./NewA";

function Section({
  n,
  title,
  note,
  children,
}: {
  n: number;
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-[132px_minmax(0,1fr)] gap-5 px-5 py-4">
      <div>
        <h2 className="flex items-baseline gap-1.5 text-[13.5px] font-semibold text-foreground">
          <span className="tabular-nums text-muted-foreground">{n}</span>
          {title}
        </h2>
        <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">{note}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function SummaryRow({ label, children, strong }: { label: string; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[13px] leading-5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("text-right tabular-nums text-foreground", strong && "font-semibold")}>{children}</dd>
    </div>
  );
}

function SummaryCard({ d }: { d: NewDraft }) {
  const m = d.margin;
  const type = CONTRACT_TYPE_OPTIONS.find((o) => o.value === d.contractType)?.label ?? "B2B";
  const mode = WORK_MODE_OPTIONS.find((o) => o.value === d.workMode)?.label;
  const later = [!d.lineManager.trim() ? "line manager" : null, !mode ? "tryb pracy" : null].filter(Boolean);
  const end = d.contractType === "b2b" ? "bezterminowo" : d.endDate ? fmtDate(d.endDate) : "bez daty końca";
  const status = CREATE_AS_OPTIONS.find((o) => o.value === d.createAs)?.label ?? "Szkic";
  const cta = d.createAs === "draft" ? "Utwórz szkic" : `Utwórz jako ${status.toLowerCase()}`;
  return (
    <section aria-label="Podsumowanie" className="rounded-xl border border-border bg-card shadow-xs">
      <header className="flex items-center justify-between gap-2 border-b border-border/70 px-4 py-2">
        <h2 className="text-[13.5px] font-semibold text-foreground">Podsumowanie</h2>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-foreground">
          <span
            aria-hidden
            className={cn(
              "size-1.5 rounded-full",
              d.createAs === "draft" ? "bg-info" : d.createAs === "active" ? "bg-success" : "bg-muted-foreground/50",
            )}
          />
          {status}
        </span>
      </header>
      <div className="space-y-2.5 px-4 py-3">
        <div>
          <p className="text-[15px] font-semibold leading-5 text-foreground">{d.candidateName || "—"}</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-[13px] leading-5 text-foreground">
            <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
            {d.clientName || "—"}
          </p>
          <p className="mt-0.5 line-clamp-2 text-[12px] leading-4 text-muted-foreground" title={d.recruitment?.job_title}>
            {d.recruitment ? d.recruitment.job_title : "bez rekrutacji"} · {type}
          </p>
        </div>
        <dl className="border-t border-border/60 pt-2">
          <SummaryRow label="Okres">
            od {fmtDate(d.startDate)} <span className="text-muted-foreground">({relDays(d.startDate)})</span> · {end}
          </SummaryRow>
        </dl>
        <dl className="space-y-0.5 border-t border-border/60 pt-2">
          <SummaryRow label="Klient płaci">{d.clientRateNum != null ? `${fmtNum(d.clientRateNum)} zł/h` : "—"}</SummaryRow>
          <SummaryRow label="Konsultant dostaje">
            {d.candidateRateNum != null ? `${fmtNum(d.candidateRateNum)} zł/h` : "—"}
          </SummaryRow>
          <SummaryRow label="Marża" strong>
            {m ? (
              <span className={m.perHour < 0 ? "text-destructive" : "text-success"}>
                {fmtNum(m.perHour)} zł/h · {m.pct}
              </span>
            ) : (
              "—"
            )}
          </SummaryRow>
        </dl>
        <div className="rounded-lg bg-muted/60 px-3 py-1.5">
          <p className="mb-1 text-[11.5px] font-medium text-muted-foreground">Miesięcznie ({d.hoursNum} h)</p>
          <dl className="space-y-0.5">
            <SummaryRow label="Przychód">{m ? fmtPln(m.revenue) : "—"}</SummaryRow>
            <SummaryRow label="Koszt">{m ? fmtPln(m.cost) : "—"}</SummaryRow>
            <SummaryRow label="Marża" strong>
              {m ? `≈ ${fmtPln(m.monthly)}` : "—"}
            </SummaryRow>
          </dl>
        </div>
        <p className="flex gap-2 text-[12px] leading-[17px] text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            {d.createAs === "draft" ? (
              <>
                <span className="font-medium text-foreground">Po utworzeniu: szkic</span> — aktywujesz po podpisaniu
                umowy.
              </>
            ) : (
              <>
                <span className="font-medium text-foreground">Po utworzeniu: {status.toLowerCase()}</span> — wpis umowy
                już podpisanej, wymaga kompletu stawek.
              </>
            )}
            {later.length > 0 ? ` Później uzupełnisz: ${later.join(", ")}.` : ""}
          </span>
        </p>
        <div className="space-y-1.5">
          <Button type="submit" className="w-full">
            {cta}
          </Button>
          <Button asChild variant="ghost" size="sm" className="w-full">
            <Link href="/contracts?status=active&status=ending">Anuluj</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

export function NewB() {
  const d = useNewContractDraft();
  const [advancedOpen, setAdvancedOpen] = useState(false);

  if (d.loading) return <p className="text-sm text-muted-foreground">Ładowanie danych ze stagingu…</p>;
  if (d.error) return <p className="text-sm text-destructive">Nie udało się pobrać kontraktu ze stagingu.</p>;

  const b2b = d.contractType === "b2b";
  const rateNote = [d.recClientRateBy, d.recClientRateAt ? fmtDate(d.recClientRateAt) : null].filter(Boolean).join(", ");

  return (
    <form className="space-y-3.5" onSubmit={(e) => e.preventDefault()} noValidate>
      <PageIntro subtitle="Trzy sekcje po lewej; podsumowanie po prawej liczy marżę na bieżąco i mówi, co powstanie." />
      <div className="grid grid-cols-[minmax(0,1fr)_310px] items-start gap-5">
        <div className="divide-y divide-border/70 rounded-xl border border-border bg-card shadow-xs">
          <Section n={1} title="Strony umowy" note="Kandydat i klient są wymagane, reszta pomaga później.">
            <div className="grid grid-cols-2 gap-x-3.5 gap-y-3">
              <div>
                <FieldLabel htmlFor="mk-b-cand" required>
                  Kandydat
                </FieldLabel>
                <PickerButton id="mk-b-cand" value={d.candidateName} placeholder="Wybierz kandydata…" />
              </div>
              <div>
                <FieldLabel htmlFor="mk-b-client" required>
                  Klient
                </FieldLabel>
                <PickerButton id="mk-b-client" value={d.clientName} placeholder="Wybierz klienta…" />
              </div>
              <div className="col-span-2">
                <FieldLabel htmlFor="mk-b-job" optional>
                  Rekrutacja
                </FieldLabel>
                <RecruitmentSelect d={d} id="mk-b-job" />
              </div>
              <div>
                <FieldLabel htmlFor="mk-b-lm" optional>
                  Line manager
                </FieldLabel>
                <Input
                  id="mk-b-lm"
                  value={d.lineManager}
                  onChange={(e) => d.setLineManager(e.target.value)}
                  placeholder="Osoba po stronie klienta"
                  className="h-9"
                />
              </div>
              <div>
                <FieldLabel htmlFor="mk-b-mode" optional>
                  Tryb pracy
                </FieldLabel>
                <Select value={d.workMode ?? "none"} onValueChange={(v) => d.setWorkMode(v === "none" ? null : (v as WorkModeKey))}>
                  <SelectTrigger id="mk-b-mode" className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Nie podano</SelectItem>
                    {WORK_MODE_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </Section>

          <Section n={2} title="Okres" note="Od kiedy osoba pracuje u klienta.">
            <div className="grid grid-cols-2 gap-x-3.5 gap-y-2">
              <div>
                <FieldLabel htmlFor="mk-b-type">Typ umowy</FieldLabel>
                <Select value={d.contractType} onValueChange={(v) => d.setContractType(v as ContractTypeKey)}>
                  <SelectTrigger id="mk-b-type" className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CONTRACT_TYPE_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <FieldLabel htmlFor="mk-b-start" required>
                  Data startu
                </FieldLabel>
                <Input
                  id="mk-b-start"
                  type="date"
                  value={d.startDate}
                  onChange={(e) => d.setStartDate(e.target.value)}
                  className="h-9 tabular-nums"
                />
              </div>
              {b2b ? (
                <p className="col-span-2 text-[12px] leading-4 text-muted-foreground">
                  Bez daty końca — umowa B2B jest bezterminowa. Koniec wpisuje okno „Zakończ współpracę” na stronie
                  kontraktu.
                </p>
              ) : (
                <div className="col-start-2">
                  <FieldLabel htmlFor="mk-b-end" optional>
                    Data końca
                  </FieldLabel>
                  <Input
                    id="mk-b-end"
                    type="date"
                    value={d.endDate}
                    onChange={(e) => d.setEndDate(e.target.value)}
                    className="h-9 tabular-nums"
                  />
                </div>
              )}
            </div>
          </Section>

          <Section n={3} title="Stawki" note="Netto za godzinę. Podpowiedzi z rekrutacji.">
            <div className="grid grid-cols-2 gap-x-3.5">
              <RateInput
                id="mk-b-rate-client"
                label="Klient płaci"
                value={d.clientRateText}
                onChange={d.setClientRate}
                current={d.clientRateNum}
                fromRecruitment={d.recClientRate}
                note={rateNote}
                onUseRecruitment={() => d.setClientRate(rateToInput(d.recClientRate))}
              />
              <RateInput
                id="mk-b-rate-cand"
                label="Konsultant dostaje"
                value={d.candidateRateText}
                onChange={d.setCandidateRate}
                current={d.candidateRateNum}
                fromRecruitment={d.recCandidateRate}
                note={d.recCandidateRateAt ? fmtDate(d.recCandidateRateAt) : "karta kandydata"}
                onUseRecruitment={() => d.setCandidateRate(rateToInput(d.recCandidateRate))}
              />
            </div>
            {d.margin && d.margin.perHour < 0 ? <MarginStrip d={d} className="mt-2.5" /> : null}
          </Section>

          <div>
            <button
              type="button"
              aria-expanded={advancedOpen}
              onClick={() => setAdvancedOpen((v) => !v)}
              title={`${MORE_OPTIONS_TITLE} Tu też status przy utworzeniu (szkic / aktywny / zakończony).`}
              className="flex w-full items-center gap-2 px-5 py-2.5 text-left"
            >
              <ChevronRight
                className={cn("size-4 shrink-0 text-muted-foreground transition-transform", advancedOpen && "rotate-90")}
                aria-hidden
              />
              <span className="shrink-0 text-[13px] font-medium text-foreground">Zaawansowane</span>
              <span className="min-w-0 truncate text-[12px] text-muted-foreground">{moreOptionsSummary(d)}</span>
            </button>
            {advancedOpen ? (
              <div className="space-y-4 border-t border-border/70 px-5 py-4">
                <MoreOptionsFields d={d} />
                <div className="border-t border-border/60 pt-3">
                  <FieldLabel>Status przy utworzeniu</FieldLabel>
                  <SegmentedRadio<CreateAsKey>
                    label="Status przy utworzeniu"
                    size="sm"
                    value={d.createAs}
                    onChange={d.setCreateAs}
                    options={CREATE_AS_OPTIONS}
                  />
                  <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">
                    Zwykle szkic. „Aktywny” i „Zakończony” tylko przy wpisie umowy już podpisanej.
                  </p>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <aside className="sticky top-4">
          <SummaryCard d={d} />
        </aside>
      </div>
    </form>
  );
}
