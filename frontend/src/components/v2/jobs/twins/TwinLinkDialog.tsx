"use client";

/**
 * Okno „Połącz bliźniaka” (0614, decyzje Artura z 28.10.2026, makieta
 * https://claude.ai/artifact/83ybsjjmstNhKAzHYNraFw, część 4).
 *
 * Bez wskazanej rekrutacji pierwszy krok to wybór: otwarte podobne, które
 * patrzący może połączyć, albo wyszukiwarka. Drugi krok pokazuje to, co
 * decyduje, czy to naprawdę bliźniak: budżet i tryb pracy obu stron (stawka
 * jest jedna, inna tylko przy innym trybie pracy), pary pytań „to samo
 * pytanie” z podpowiedzią serwera do poprawienia i zdanie, że osoby
 * zweryfikowane wcześniej zostają tam, gdzie są (połączenie działa od teraz).
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, Search } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { pairOf, questionsInConversation, setPair, unpairedOther } from "@/lib/job-twin-pairs";
import {
  budgetLabel,
  jobTwinsApi,
  jobTwinsKeys,
  type QuestionPair,
  twinRef,
  type TwinJobBrief,
  useLinkTwin,
  useOpenSimilarJobs,
  workModeLabel,
} from "@/lib/job-twins-api";
import { useDebouncedValue } from "@/lib/use-debounced-value";

interface SearchRow {
  id: number;
  title: string;
  client_name?: string | null;
  reference_number?: string | null;
  status?: string;
}

export interface TwinLinkDialogProps {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Rekrutacja wskazana w kaflu albo na liście HoR — bez kroku wyboru. */
  otherJobId?: number | null;
}

function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return `${n} ${one}`;
  const last = n % 10;
  const lastTwo = n % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? `${n} ${few}` : `${n} ${many}`;
}

function sameMode(a: TwinJobBrief, b: TwinJobBrief): boolean {
  return workModeLabel(a) === workModeLabel(b);
}

export function TwinLinkDialog({ jobId, open, onOpenChange, otherJobId = null }: TwinLinkDialogProps) {
  const [picked, setPicked] = useState<number | null>(otherJobId);
  useEffect(() => {
    if (open) setPicked(otherJobId);
  }, [open, otherJobId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" aria-describedby="twin-link-desc" data-testid="twin-link-dialog">
        <DialogHeader>
          <DialogTitle>Połącz bliźniaka</DialogTitle>
          <DialogDescription id="twin-link-desc">
            Bliźniak to rekrutacja o tym samym profilu kandydata. Każdą osobę weryfikujecie raz, w jednej
            rozmowie, pod obie rekrutacje.
          </DialogDescription>
        </DialogHeader>
        {picked == null ? (
          <PickStep jobId={jobId} onPick={setPicked} />
        ) : (
          <PreviewStep
            jobId={jobId}
            otherId={picked}
            onBack={otherJobId == null ? () => setPicked(null) : undefined}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function PickStep({ jobId, onPick }: { jobId: number; onPick: (id: number) => void }) {
  const open = useOpenSimilarJobs(jobId);
  const [q, setQ] = useState("");
  const term = useDebouncedValue(q.trim(), 250);
  const search = useQuery({
    queryKey: ["twin-search", jobId, term],
    enabled: term.length >= 2,
    queryFn: async () =>
      (await api.get<{ items: SearchRow[] }>(`/api/jobs/${jobId}/similar/search`, { params: { q: term } })).data
        .items,
  });
  const candidates = (open.data?.items ?? []).filter((item) => item.can_twin);
  const found = (search.data ?? []).filter((row) => row.status !== "closed");

  return (
    <DialogBody className="space-y-4">
      <section className="space-y-2" aria-label="Otwarte podobne">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Otwarte podobne</h3>
        {open.isLoading ? (
          <p className="text-sm text-muted-foreground">Szukam podobnych rekrutacji…</p>
        ) : open.isError ? (
          <p className="text-sm text-destructive">Nie udało się pobrać podobnych rekrutacji. Użyj wyszukiwarki.</p>
        ) : candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak otwartych podobnych, które możesz połączyć.</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {candidates.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    <span className="mr-1.5 font-mono text-xs">{twinRef(item)}</span>
                    {item.title}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {item.client_name ?? "—"} · {workModeLabel(item)} · {budgetLabel(item)}
                  </p>
                </div>
                <span className="text-xs tabular-nums text-muted-foreground">≈ {item.similarity}%</span>
                <Button size="sm" variant="outline" onClick={() => onPick(item.id)}>
                  Wybierz
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="space-y-2" aria-label="Inna rekrutacja">
        <label htmlFor="twin-search" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Inna otwarta rekrutacja
        </label>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <Input
            id="twin-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Numer, tytuł, klient…"
            className="pl-8"
          />
        </div>
        {found.length > 0 ? (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {found.map((row) => (
              <li key={row.id} className="flex items-center gap-3 px-3 py-2">
                <p className="min-w-0 flex-1 truncate text-sm">
                  {row.reference_number ? <span className="mr-1.5 font-mono text-xs">{row.reference_number}</span> : null}
                  {row.title} <span className="text-muted-foreground">· {row.client_name ?? "—"}</span>
                </p>
                <Button size="sm" variant="outline" onClick={() => onPick(row.id)}>
                  Wybierz
                </Button>
              </li>
            ))}
          </ul>
        ) : term.length >= 2 && search.isSuccess ? (
          <p className="text-sm text-muted-foreground">Nic nie pasuje do „{term}”.</p>
        ) : null}
      </section>
    </DialogBody>
  );
}

function PreviewStep({
  jobId,
  otherId,
  onBack,
  onDone,
}: {
  jobId: number;
  otherId: number;
  onBack?: () => void;
  onDone: () => void;
}) {
  const { showError, showSuccess } = useToast();
  const preview = useQuery({
    queryKey: jobTwinsKeys.preview(jobId, otherId),
    queryFn: () => jobTwinsApi.preview(jobId, otherId),
    retry: false,
  });
  const link = useLinkTwin(jobId);
  const [pairs, setPairs] = useState<QuestionPair[] | null>(null);
  useEffect(() => {
    if (preview.data) setPairs(preview.data.question_pairs.map(({ own, other }) => ({ own, other })));
  }, [preview.data]);

  const data = preview.data;
  const otherText = useMemo(
    () => Object.fromEntries((data?.other.questions ?? []).map((q) => [q.id, q.text])),
    [data],
  );

  if (preview.isLoading || (data && pairs == null)) {
    return (
      <DialogBody>
        <p className="text-sm text-muted-foreground">Porównuję rekrutacje…</p>
      </DialogBody>
    );
  }
  if (preview.isError || !data || pairs == null) {
    return (
      <>
        <DialogBody>
          <p className="text-sm text-destructive" role="alert">
            {apiErrorMessage(preview.error, "Nie udało się porównać rekrutacji.")}
          </p>
        </DialogBody>
        <DialogFooter>
          {onBack ? (
            <Button variant="outline" onClick={onBack}>
              Wróć
            </Button>
          ) : null}
        </DialogFooter>
      </>
    );
  }

  const { job, other } = data;
  const asked = questionsInConversation(job.questions.length, other.questions.length, pairs);
  const onlyOther = unpairedOther(
    pairs,
    other.questions.map((q) => q.id),
  );

  const submit = async () => {
    try {
      const result = await link.mutateAsync({ otherId, pairs });
      showSuccess(
        result.linked_now
          ? `Połączono z ${twinRef(other)}. Zespoły obu rekrutacji dostały powiadomienie.`
          : `Zapisano pary pytań z ${twinRef(other)}.`,
      );
      onDone();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się połączyć rekrutacji."));
    }
  };

  return (
    <>
      <DialogBody className="space-y-4">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm" data-testid="twin-compare">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1 pr-3 font-semibold" />
                <th className="py-1 pr-3 font-semibold">
                  {twinRef(job)} · ta rekrutacja
                </th>
                <th className="py-1 font-semibold">{twinRef(other)} · bliźniak</th>
              </tr>
            </thead>
            <tbody className="align-top">
              <tr>
                <td className="py-1 pr-3 text-muted-foreground">Klient · DL</td>
                <td className="py-1 pr-3">
                  {job.client_name ?? "—"} · {job.delivery_lead_name ?? "bez DL"}
                </td>
                <td className="py-1">
                  {other.client_name ?? "—"} · {other.delivery_lead_name ?? "bez DL"}
                </td>
              </tr>
              <tr>
                <td className="py-1 pr-3 text-muted-foreground">Tryb pracy</td>
                <td className="py-1 pr-3">{workModeLabel(job)}</td>
                <td className="py-1">{workModeLabel(other)}</td>
              </tr>
              <tr>
                <td className="py-1 pr-3 text-muted-foreground">Budżet</td>
                <td className="py-1 pr-3 tabular-nums">{budgetLabel(job)}</td>
                <td className="py-1 tabular-nums">{budgetLabel(other)}</td>
              </tr>
              <tr>
                <td className="py-1 pr-3 text-muted-foreground">Osoby</td>
                <td className="py-1 pr-3 tabular-nums">{job.people_count}</td>
                <td className="py-1 tabular-nums">{other.people_count}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-sm text-muted-foreground" data-testid="twin-rate-rule">
          {sameMode(job, other)
            ? "Ten sam tryb pracy — w screeningu jedna stawka dla obu, najwyżej do niższego budżetu."
            : "Inny tryb pracy — w screeningu możesz podać osobną stawkę dla każdej rekrutacji, zawsze w jej budżecie."}
        </p>

        <section className="space-y-2" aria-label="Te same pytania">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">Te same pytania</h3>
            <span className="text-xs text-muted-foreground">
              W rozmowie: {plural(asked, "pytanie", "pytania", "pytań")} zamiast{" "}
              {job.questions.length + other.questions.length}
            </span>
          </div>
          {job.questions.length === 0 || other.questions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {job.questions.length === 0 ? twinRef(job) : twinRef(other)} nie ma jeszcze pytań w Profilu Championa.
              Pary ustawisz tu później, z chipu bliźniaka.
            </p>
          ) : (
            <ul className="space-y-2" data-testid="twin-question-pairs">
              {job.questions.map((q) => {
                const value = pairOf(pairs, q.id);
                return (
                  <li key={q.id} className="grid gap-1.5 rounded-lg border border-border p-2 sm:grid-cols-2">
                    <p className="text-xs">
                      <span className="mr-1 font-mono font-semibold text-primary">{q.id}</span>
                      {q.text}
                    </p>
                    <div className="space-y-1">
                      <select
                        aria-label={`Para dla pytania ${q.id}`}
                        className="w-full rounded-md border border-border bg-card px-2 py-1 text-xs"
                        value={value ?? ""}
                        onChange={(e) => setPairs(setPair(pairs, q.id, e.target.value || null))}
                      >
                        <option value="">Tylko w {twinRef(job)}</option>
                        {other.questions.map((oq) => (
                          <option key={oq.id} value={oq.id}>
                            = {oq.id}: {oq.text.slice(0, 70)}
                            {oq.text.length > 70 ? "…" : ""}
                          </option>
                        ))}
                      </select>
                      {value ? <p className="text-xs text-muted-foreground">{otherText[value]}</p> : null}
                    </div>
                  </li>
                );
              })}
              {onlyOther.length > 0 ? (
                <li className="text-xs text-muted-foreground">
                  Tylko w {twinRef(other)}: {onlyOther.join(", ")}
                </li>
              ) : null}
            </ul>
          )}
        </section>

        <p className="text-sm text-muted-foreground" data-testid="twin-no-copy">
          Połączenie działa od teraz.{" "}
          {data.verified_not_in_other > 0
            ? `${plural(data.verified_not_in_other, "osoba zweryfikowana", "osoby zweryfikowane", "osób zweryfikowanych")} wcześniej w ${twinRef(job)} zostaje tylko tam.`
            : null}
        </p>
      </DialogBody>
      <DialogFooter className="items-center">
        {onBack ? (
          <Button variant="ghost" onClick={onBack} className="mr-auto">
            Wróć
          </Button>
        ) : null}
        <Button onClick={submit} disabled={link.isPending} data-testid="twin-link-submit">
          <ArrowLeftRight className="h-4 w-4" aria-hidden="true" />
          {link.isPending
            ? "Łączę…"
            : data.already_twin
              ? "Zapisz pary pytań"
              : "Połącz i powiadom zespół"}
        </Button>
      </DialogFooter>
    </>
  );
}
