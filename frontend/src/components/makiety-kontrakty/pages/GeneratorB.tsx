"use client";
// B · Generator umów jako „jedna strona z paskiem gotowości”. Wszystkie
// sekcje umowy na jednej stronie, zwarte (pola w dwóch kolumnach zamiast
// formularza na ok. 3 ekrany), po lewej przyklejony spis sekcji z kompletnością
// („✓” albo „6 braków”), na dole przyklejony pasek: ile pól brakuje i które
// (klik przewija do sekcji), „Podgląd”, „Pobierz DOCX”, „Pobierz PDF” —
// pobieranie wyłączone do kompletu. Zakładki generatora jako zwarta druga
// nawigacja (rejestr umów nadal w trzech fazach, ale w jednym rzędzie).
//
// Te same dane i pola co w wariancie A (`GeneratorA.tsx`): osoba i klient
// z kontraktu 199 na stagingu, prefill rekrutacji, numer z `/next-number`.
// NIP, REGON, adres, e-mail i telefon celowo puste. Nic się nie zapisuje.
import { useState } from "react";
import { Check, Download, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { cn } from "@/lib/utils";
import { plural } from "../shared/format";
import {
  BRAKI,
  GEN_FIELDS,
  GEN_SECTION_INTRO,
  GEN_SECTIONS,
  missingCountLabel,
  missingIn,
  missingLabel,
  useGeneratorDraft,
  type GenDraft,
  type GenSectionKey,
} from "./GeneratorA";

const NAV_B = [
  { group: null, items: [{ key: "nowa", label: "Nowa umowa" }, { key: "aneks", label: "Nowy aneks" }] },
  {
    group: "Rejestr umów",
    items: [
      { key: "biezace", label: "Bieżące" },
      { key: "bez-projektu", label: "Bez projektu" },
      { key: "zakonczone", label: "Zakończone" },
    ],
  },
  { group: null, items: [{ key: "dokumenty", label: "Dokumenty" }, { key: "zakresy", label: "Zakresy ról" }] },
] as const;
type NavKey = (typeof NAV_B)[number]["items"][number]["key"];

const NAV_TEXT: Record<Exclude<NavKey, "nowa">, string> = {
  aneks: "Generator aneksów i rejestr aneksów — poza zakresem tej makiety.",
  biezace: "Rejestr umów bieżących (aktywne, w trakcie podpisu, anulowane) — poza zakresem tej makiety.",
  "bez-projektu": "Umowy zawieszone bez projektu — poza zakresem tej makiety.",
  zakonczone: "Umowy zakończone — poza zakresem tej makiety.",
  dokumenty: "Rozwiązania, wypowiedzenia i umowy przedwstępne — poza zakresem tej makiety.",
  zakresy: "Katalog obszarów usług z zakresem PL / EN — edytuje admin. Poza zakresem tej makiety.",
};

const sectionId = (key: GenSectionKey) => `mk-gen-b-${key}`;

function scrollToSection(key: GenSectionKey) {
  document.getElementById(sectionId(key))?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function sectionDone(d: GenDraft, key: GenSectionKey): boolean {
  return missingIn(d, key).length === 0;
}

function SectionState({ d, sectionKey }: { d: GenDraft; sectionKey: GenSectionKey }) {
  const n = missingIn(d, sectionKey).length;
  if (n === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[12px] font-medium text-success">
        <Check className="size-3.5" aria-hidden />
        komplet
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-warning-muted-foreground">
      <span aria-hidden className="size-1.5 rounded-full bg-warning" />
      {plural(n, BRAKI)}
    </span>
  );
}

function Toc({ d }: { d: GenDraft }) {
  const doneCount = GEN_SECTIONS.filter((s) => sectionDone(d, s.key)).length;
  const pct = Math.round((doneCount / GEN_SECTIONS.length) * 100);
  return (
    <nav aria-label="Sekcje umowy" className="sticky top-4 space-y-3">
      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">Sekcje umowy</p>
        <ol className="space-y-0.5">
          {GEN_SECTIONS.map((s, i) => {
            const n = missingIn(d, s.key).length;
            return (
              <li key={s.key}>
                <button
                  type="button"
                  onClick={() => scrollToSection(s.key)}
                  className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/70"
                >
                  <span
                    className={cn(
                      "-mt-px grid size-[18px] shrink-0 place-items-center rounded-full text-[10.5px] font-semibold tabular-nums",
                      n === 0
                        ? "bg-success-muted text-success-muted-foreground"
                        : "border border-warning/60 bg-card text-warning-muted-foreground",
                    )}
                  >
                    {n === 0 ? <Check className="size-3" aria-label="komplet" /> : i + 1}
                  </span>
                  <span className="min-w-0 flex-1 text-[13px] leading-4 text-foreground">{s.label}</span>
                  {n > 0 ? (
                    <span className="shrink-0 text-[11.5px] leading-4 tabular-nums text-warning-muted-foreground">
                      {plural(n, BRAKI)}
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ol>
      </div>
      <div className="border-t border-border pt-3">
        <div className="mb-1.5 flex items-baseline justify-between text-[12px]">
          <span className="text-muted-foreground">Gotowe sekcje</span>
          <span className="font-medium tabular-nums text-foreground">
            {doneCount} z {GEN_SECTIONS.length}
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-success" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </nav>
  );
}

function ReadinessBar({ d }: { d: GenDraft }) {
  const n = d.missing.length;
  const ready = n === 0;
  const nipMissing = d.missing.some((m) => m.label === "NIP");
  const blocked = ready ? undefined : `${missingCountLabel(n)}: ${missingLabel(d)}`;
  return (
    <div
      role="region"
      aria-label="Gotowość umowy"
      className="sticky bottom-3 z-20 mr-14 flex items-center gap-4 rounded-xl border border-border bg-card/95 px-4 py-2.5 shadow-lg backdrop-blur"
    >
      <div className="min-w-0 flex-1">
        {ready ? (
          <p className="flex items-center gap-1.5 text-[13px] font-semibold text-success">
            <Check className="size-4" aria-hidden />
            Wszystko uzupełnione — umowę nr {d.number} można pobrać.
          </p>
        ) : (
          <p className="line-clamp-2 text-[13px] leading-5 text-muted-foreground">
            <span className="mr-1.5 inline-flex items-center gap-1.5 font-semibold text-foreground">
              <span aria-hidden className="size-2 rounded-full bg-warning" />
              {missingCountLabel(n)}:
            </span>
            {d.missing.map((m, i) => (
              <span key={`${m.section}-${m.label}`}>
                {i > 0 ? ", " : null}
                <button
                  type="button"
                  onClick={() => scrollToSection(m.section)}
                  className="text-foreground underline decoration-border underline-offset-2 hover:decoration-foreground"
                >
                  {m.label}
                </button>
              </span>
            ))}
            .
            {nipMissing ? (
              <span className="text-[12px]"> NIP uzupełni nazwę firmy, REGON i adres z rejestru.</span>
            ) : null}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button type="button" variant="ghost" size="sm" title="Podgląd z brakami w miejscu pustych pól; nie zajmuje numeru">
          <Eye className="size-3.5" aria-hidden />
          Podgląd
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={!ready} title={blocked}>
          <Download className="size-3.5" aria-hidden />
          Pobierz DOCX
        </Button>
        <Button type="button" size="sm" disabled={!ready} title={blocked}>
          <Download className="size-3.5" aria-hidden />
          Pobierz PDF
        </Button>
      </div>
    </div>
  );
}

export function GeneratorB() {
  const d = useGeneratorDraft();
  const [kind, setKind] = useState<"b2b" | "mandate">("b2b");
  const [nav, setNav] = useState<NavKey>("nowa");

  if (d.loading) return <p className="text-sm text-muted-foreground">Ładowanie danych ze stagingu…</p>;
  if (d.error) return <p className="text-sm text-destructive">Nie udało się pobrać danych ze stagingu.</p>;

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex items-center gap-3">
          <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">Generator umów</h1>
          <SegmentedRadio<"b2b" | "mandate">
            label="Rodzaj umowy"
            size="sm"
            value={kind}
            onChange={setKind}
            options={[
              { value: "b2b", label: "Umowa B2B" },
              { value: "mandate", label: "Umowa zlecenia" },
            ]}
          />
        </div>
        <p className="text-[12.5px] text-muted-foreground">
          Umowa nr <span className="font-medium tabular-nums text-foreground">{d.number || "—"}</span> · numer zajmie się
          przy pobraniu
        </p>
      </header>

      <nav aria-label="Generator umów" className="flex flex-wrap items-center gap-x-1 gap-y-1">
        {NAV_B.map((g, gi) => (
          <div key={gi} className={cn("flex items-center gap-0.5", gi > 0 && "border-l border-border pl-2")}>
            {g.group ? <span className="mr-1 text-[11.5px] text-muted-foreground">{g.group}:</span> : null}
            {g.items.map((it) => {
              const active = it.key === nav;
              return (
                <button
                  key={it.key}
                  type="button"
                  onClick={() => setNav(it.key)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex h-7 items-center rounded-md px-2.5 text-[12.5px] transition-colors",
                    active
                      ? "bg-card font-semibold text-foreground shadow-xs ring-1 ring-border"
                      : "font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {it.label}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {nav !== "nowa" ? (
        <p className="rounded-xl border border-border bg-card p-4 text-[13px] text-muted-foreground shadow-xs">
          {NAV_TEXT[nav]}
        </p>
      ) : (
        <>
          {kind === "mandate" ? (
            <p className="rounded-lg bg-info-muted px-3 py-2 text-[12.5px] text-info-muted-foreground">
              Umowa zlecenia ma ten sam układ z krótszą listą sekcji — makieta pokazuje umowę B2B.
            </p>
          ) : null}
          <div className="grid grid-cols-[188px_minmax(0,1fr)] items-start gap-5">
            <Toc d={d} />
            <div className="space-y-3">
              {GEN_SECTIONS.map((s, i) => {
                const Fields = GEN_FIELDS[s.key];
                return (
                  <section
                    key={s.key}
                    id={sectionId(s.key)}
                    className="scroll-mt-4 rounded-xl border border-border bg-card shadow-xs"
                  >
                    <header className="flex items-baseline justify-between gap-3 border-b border-border/70 px-4 py-2">
                      <div className="flex min-w-0 items-baseline gap-2">
                        <h2 className="shrink-0 text-[13.5px] font-semibold text-foreground">
                          <span className="mr-1.5 tabular-nums text-muted-foreground">{i + 1}</span>
                          {s.label}
                        </h2>
                        <p className="truncate text-[12px] text-muted-foreground">{GEN_SECTION_INTRO[s.key]}</p>
                      </div>
                      <SectionState d={d} sectionKey={s.key} />
                    </header>
                    <div className="px-4 py-3">
                      <Fields d={d} dense={s.key === "zrodlo" || s.key === "admin"} />
                    </div>
                  </section>
                );
              })}
            </div>
          </div>
          <ReadinessBar d={d} />
        </>
      )}
    </div>
  );
}
