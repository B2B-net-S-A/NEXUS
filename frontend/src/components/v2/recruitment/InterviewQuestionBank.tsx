"use client";

/**
 * Rekrutacje → „Pytania z rozmów”. Dawny Excel z pytaniami z rozmów, tylko że
 * dopisuje się sam: każdy debrief dokłada pytania klienta, a stanowisko
 * i manager przychodzą z rekrutacji. Archiwum z Excela (0383) jest w tej samej
 * tabeli.
 *
 * Od 25.11.2026 (decyzja Artura, wariant A z makiet): najpierw lista stanowisk,
 * a po kliknięciu stanowiska jego pytania z propozycją odpowiedzi. Stanowisko
 * siedzi w adresie (`?stanowisko=<id rekrutacji>` albo `excel-<id klienta>`),
 * żeby dało się je podesłać rekruterowi linkiem.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ChevronLeft, ChevronRight, Copy, FileSpreadsheet, MessageSquareText } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useQuestionBank } from "@/lib/api/interviewCycle";
import {
  EMPTY_FILTERS,
  clientOptions,
  filterPositions,
  groupByPosition,
  isSectionHeading,
  managerOptions,
  positionAsText,
  questionCount,
  type BankQuestion,
  type Position,
  type PositionFilters,
} from "@/lib/question-bank";
import { cn } from "@/lib/utils";

const PAGE = 50;
const DATE = new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Warsaw" });
const CONTROL =
  "h-9 rounded-md border border-border bg-card px-3 text-sm text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

function countLabel(n: number): string {
  const tens = n % 100;
  const ones = n % 10;
  if (n === 1) return "1 pytanie";
  if (ones >= 2 && ones <= 4 && (tens < 12 || tens > 14)) return `${n} pytania`;
  return `${n} pytań`;
}

export function InterviewQuestionBank() {
  const query = useQuestionBank();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const selectedKey = params.get("stanowisko");
  const [filters, setFilters] = useState<PositionFilters>(EMPTY_FILTERS);
  const [limit, setLimit] = useState(PAGE);

  const positions = useMemo(() => groupByPosition(query.data?.items ?? []), [query.data]);
  const visible = useMemo(() => filterPositions(positions, filters), [positions, filters]);
  const clients = useMemo(() => clientOptions(positions), [positions]);
  const managers = useMemo(() => managerOptions(positions, filters.clientId), [positions, filters.clientId]);

  const set = (patch: Partial<PositionFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setLimit(PAGE);
  };
  const open = (key: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (key) next.set("stanowisko", key);
    else next.delete("stanowisko");
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  };

  if (query.isPending) {
    return <div className="rounded-2xl border border-border bg-card p-8 text-sm text-muted-foreground">Ładowanie pytań…</div>;
  }
  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Pytania z rozmów nie wczytały się — to nie znaczy, że ich nie ma."
        onRetry={() => query.refetch()}
      />
    );
  }

  if (selectedKey) {
    const selected = positions.find((p) => p.key === selectedKey);
    if (!selected) {
      return (
        <section className="space-y-3">
          <BackLink onClick={() => open(null)} />
          <EmptyState
            icon={MessageSquareText}
            title="Tego stanowiska nie ma na liście"
            description="Rekrutacja nie ma jeszcze pytań z rozmów albo nie jest w Twoim zakresie."
          />
        </section>
      );
    }
    // Strzałki idą po liście po filtrach; stanowisko spoza filtrów — po całej liście.
    const order = visible.some((p) => p.key === selected.key) ? visible : positions;
    const at = order.findIndex((p) => p.key === selected.key);
    return (
      <PositionDetail
        position={selected}
        onBack={() => open(null)}
        prev={at > 0 ? order[at - 1] : null}
        next={at >= 0 && at < order.length - 1 ? order[at + 1] : null}
        onOpen={open}
      />
    );
  }

  const withJob = positions.filter((p) => p.jobId != null).length;
  const totalQuestions = query.data?.items.length ?? 0;

  return (
    <section className="space-y-3" data-testid="question-bank">
      <p className="text-sm text-muted-foreground tabular-nums">
        {withJob.toLocaleString("pl-PL")} stanowisk z rekrutacji · {(positions.length - withJob).toLocaleString("pl-PL")} archiwów
        z Excela · {totalQuestions.toLocaleString("pl-PL")} pytań
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Klient
          <select
            aria-label="Klient"
            value={filters.clientId ?? ""}
            onChange={(e) => set({ clientId: e.target.value ? Number(e.target.value) : null, manager: null })}
            className={cn(CONTROL, "w-52")}
          >
            <option value="">Wszyscy ({positions.length})</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.count})
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Stanowisko
          <input
            aria-label="Stanowisko"
            value={filters.search}
            onChange={(e) => set({ search: e.target.value })}
            placeholder="nazwa albo numer"
            className={cn(CONTROL, "w-52")}
          />
        </label>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Manager
          <select
            aria-label="Manager"
            data-tour="jobs.question-bank.manager"
            value={filters.manager ?? ""}
            onChange={(e) => set({ manager: e.target.value || null })}
            className={cn(CONTROL, "w-44")}
          >
            <option value="">Wszyscy</option>
            {managers.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Pytanie zawiera
          <input
            aria-label="Pytanie zawiera"
            value={filters.text}
            onChange={(e) => set({ text: e.target.value })}
            placeholder="np. SOAP, Kafka"
            className={cn(CONTROL, "w-40")}
          />
        </label>
      </div>

      {visible.length === 0 ? (
        <EmptyState
          icon={MessageSquareText}
          title="Brak stanowisk dla tych filtrów"
          description="Zmień klienta albo wyczyść wyszukiwanie. Nowe pytania dopisują się same z każdego debriefu."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card" data-tour="jobs.question-bank.positions">
          <table className="w-full min-w-[48rem] table-fixed text-sm">
            <thead className="bg-muted/50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Stanowisko</th>
                <th className="w-36 px-3 py-2">Klient</th>
                <th className="w-40 px-3 py-2">Manager</th>
                <th className="w-16 px-3 py-2 text-right">Pytań</th>
                <th className="w-28 px-3 py-2">Ostatnio</th>
                <th className="w-8" aria-hidden />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visible.slice(0, limit).map((p) => (
                <tr
                  key={p.key}
                  className="cursor-pointer hover:bg-muted/40"
                  data-testid="position-row"
                  data-tour="jobs.question-bank.position"
                  onClick={() => open(p.key)}
                >
                  <td className="px-3 py-2">
                    <Link
                      href={`${pathname}?stanowisko=${encodeURIComponent(p.key)}`}
                      onClick={(e) => e.stopPropagation()}
                      className="block min-w-0 hover:underline"
                    >
                      <span className="block truncate font-medium text-foreground">
                        {p.jobId == null ? <FileSpreadsheet className="mr-1 inline h-3.5 w-3.5 text-muted-foreground" aria-hidden /> : null}
                        {p.name}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {[p.jobNumber, p.detail ?? (p.jobId == null ? "pytania bez przypisanej rekrutacji" : null)].filter(Boolean).join(" · ")}
                      </span>
                    </Link>
                  </td>
                  <td className="truncate px-3 py-2 text-foreground" title={p.clientName}>
                    {p.clientName}
                  </td>
                  <td className="truncate px-3 py-2 text-muted-foreground" title={p.managers.join(", ")}>
                    {p.managers.join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{questionCount(p)}</td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-muted-foreground">
                    {p.lastAskedAt ? DATE.format(new Date(p.lastAskedAt)) : "—"}
                  </td>
                  <td className="px-2 text-muted-foreground">
                    <ChevronRight className="h-4 w-4" aria-hidden />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {visible.length > limit ? (
            <div className="border-t border-border p-2 text-center">
              <Button size="sm" variant="ghost" onClick={() => setLimit((n) => n + PAGE)}>
                Pokaż kolejne {Math.min(PAGE, visible.length - limit)} z {visible.length - limit}
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
      <ArrowLeft className="h-4 w-4" aria-hidden /> Wszystkie stanowiska
    </button>
  );
}

interface PositionDetailProps {
  position: Position;
  onBack: () => void;
  prev: Position | null;
  next: Position | null;
  onOpen: (key: string) => void;
}

function PositionDetail({ position: p, onBack, prev, next, onOpen }: PositionDetailProps) {
  const { showSuccess, showError } = useToast();
  // Klucz stanowiska resetuje „Pokaż wszystkie” przy przejściu strzałką.
  const [allOpen, setAllOpen] = useState<{ key: string; open: boolean }>({ key: p.key, open: false });
  const openAll = allOpen.key === p.key && allOpen.open;
  const total = questionCount(p);
  const answered = p.questions.filter((q) => q.answer && !isSectionHeading(q)).length;

  const copy = async (withAnswers: boolean) => {
    try {
      await navigator.clipboard.writeText(positionAsText(p, withAnswers));
      showSuccess(withAnswers ? `Skopiowano ${total} pytań z odpowiedziami.` : `Skopiowano ${total} pytań.`);
    } catch {
      showError("Przeglądarka nie pozwoliła skopiować. Zaznacz pytania na stronie ręcznie.");
    }
  };

  let n = 0;
  return (
    <section className="space-y-3" data-testid="position-detail">
      <div className="flex flex-wrap items-center gap-2">
        <BackLink onClick={onBack} />
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" className="h-8" disabled={!prev} onClick={() => prev && onOpen(prev.key)} title={prev ? prev.name : undefined}>
            <ChevronLeft className="h-4 w-4" aria-hidden /> Poprzednie
          </Button>
          <Button size="sm" variant="ghost" className="h-8" disabled={!next} onClick={() => next && onOpen(next.key)} title={next ? next.name : undefined}>
            Następne <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>

      <div className="space-y-1">
        <h2 className="text-xl font-bold tracking-[-0.01em] text-foreground">{p.name}</h2>
        <p className="text-sm text-muted-foreground">
          {p.jobId != null ? (
            <Link href={`/jobs/${p.jobId}`} className="text-primary hover:underline">
              {p.jobNumber ?? `Rekrutacja #${p.jobId}`}
            </Link>
          ) : (
            "Pytania z Excela bez przypisanej rekrutacji"
          )}
          {" · "}
          {p.clientName}
          {p.managers.length ? ` · manager: ${p.managers.join(", ")}` : ""}
          {p.detail ? ` · ${p.detail}` : ""}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground tabular-nums">
          {countLabel(total)} · propozycja odpowiedzi przy {answered}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="h-8" disabled={answered === 0} onClick={() => setAllOpen({ key: p.key, open: !openAll })}>
            {openAll ? "Zwiń odpowiedzi" : "Pokaż wszystkie odpowiedzi"}
          </Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => copy(false)}>
            <Copy className="h-4 w-4" aria-hidden /> Kopiuj pytania
          </Button>
          <Button size="sm" variant="outline" className="h-8" disabled={answered === 0} onClick={() => copy(true)}>
            <Copy className="h-4 w-4" aria-hidden /> Kopiuj z odpowiedziami
          </Button>
        </div>
      </div>

      <ol className="space-y-1">
        {p.questions.map((q) => {
          if (isSectionHeading(q)) {
            return (
              <li key={q.id} className="pt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground first:pt-0">
                {q.text}
              </li>
            );
          }
          n += 1;
          return <QuestionItem key={`${p.key}-${q.id}-${openAll}`} index={n} question={q} defaultOpen={openAll} />;
        })}
      </ol>
    </section>
  );
}

function answerLabel(source: BankQuestion["answer_source"]): string {
  if (source === "ai") return "Propozycja odpowiedzi AI · do sprawdzenia przez rekrutera";
  if (source === "excel") return "Odpowiedź z Excela rekruterów";
  return "Odpowiedź";
}

function QuestionItem({ index, question: q, defaultOpen }: { index: number; question: BankQuestion; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <li className="rounded-lg border border-border bg-card px-3 py-2" data-testid="question-row">
      <div className="flex items-start gap-3">
        <span className="w-6 shrink-0 pt-0.5 text-right text-xs tabular-nums text-muted-foreground">{index}.</span>
        <p className="min-w-0 flex-1 text-sm text-foreground">{q.text}</p>
        {q.asked_count > 1 ? <span className="shrink-0 text-xs tabular-nums text-muted-foreground">padło {q.asked_count}×</span> : null}
        {q.answer ? (
          <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="shrink-0 text-xs font-medium text-primary hover:underline">
            {open ? "Ukryj odpowiedź" : "Odpowiedź"}
          </button>
        ) : (
          <span className="shrink-0 text-xs text-muted-foreground" title="Propozycje odpowiedzi dopisuje nocny przebieg AI">
            odpowiedź po nocnym przebiegu
          </span>
        )}
      </div>
      {q.answer && open ? (
        <div className="ml-9 mt-2 rounded-md bg-muted/50 px-3 py-2">
          <p className="mb-1 text-xs font-semibold text-muted-foreground">{answerLabel(q.answer_source)}</p>
          <p className="whitespace-pre-line text-sm text-foreground">{q.answer}</p>
        </div>
      ) : null}
    </li>
  );
}
