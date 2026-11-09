"use client";

import { useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Briefcase, FileText, Target, Upload } from "lucide-react";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";
import {
  TalentRadarClientPicker,
  type ClientRef,
} from "@/components/talent-radar/TalentRadarClientPicker";
import { JobPicker, type JobPickerJob } from "@/components/v2/recruitment/JobPicker";
import { jobDisplayTitle } from "@/lib/job-names";
import {
  radarBudgetError,
  radarOfficeDaysError,
} from "@/components/talent-radar/run-criteria";
import type { TalentRadarInitialRequest } from "@/components/talent-radar/TalentRadarWorkspace";
import { apiErrorMessage } from "@/lib/api-error";
import { dutySearchApi } from "@/lib/duty-search-api";

/** Poniżej tego progu opis roli nie niesie sygnału (lustro radaru). */
export const REQUEST_TEXT_MIN_LENGTH = 30;

type Source = TalentRadarInitialRequest["source"];
/**
 * „Cel projektu” (09.11.2026): „Kto już to robił” — wyszukiwanie po tym, co
 * osoba ma zrobić, gdy nie znamy technologii krytycznych. Zakładka w tym oknie,
 * a nie przycisk w nagłówku listy (decyzja Artura: przycisk łamał nagłówek
 * przy 1280 px). Reguła: `docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md`.
 */
type Kind = "request" | "goal";

interface SourceTile {
  value: Source;
  title: string;
  hint: string;
  icon: typeof FileText;
}

const SOURCE_TILES: SourceTile[] = [
  { value: "text", title: "Wklej tekst", hint: "mail albo opis od klienta", icon: FileText },
  { value: "file", title: "Wgraj plik Championa", hint: "plik .docx od Delivery", icon: Upload },
  { value: "job", title: "Rekrutacja z NEXUSA", hint: "użyj zapisanego profilu", icon: Briefcase },
];

export interface RequestSearchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** „Dalej: sprawdź wymagania" — dane idą STANEM do widoku wyników. */
  onSubmit: (request: TalentRadarInitialRequest) => void;
  /** Tekst wklejony w pole wyszukiwania listy — startowa treść requestu. */
  initialText?: string;
}

/**
 * „Szukaj z requestu" (makieta A2-Request-4, 22.09.2026): jeden krok —
 * źródło wymagań + klient i twarde granice. Resztę (umiejętności, staż,
 * miasto) odczytuje radar i pokazuje do poprawy w kroku „Sprawdź wymagania".
 *
 * Klient jest wymagany (poza zapisaną rekrutacją, która ma własnego): bez
 * niego nie da się sprawdzić weta hiring managera ani konfliktów z klientem.
 */
export function RequestSearchDialog({
  open,
  onOpenChange,
  onSubmit,
  initialText = "",
}: RequestSearchDialogProps) {
  const user = useAuthStore((s) => s.user);
  const router = useRouter();
  const [kind, setKind] = useState<Kind>("request");
  const [goalText, setGoalText] = useState("");
  const canUseJobs = hasSectionAccess(user, "pipeline", "read");
  const tiles = canUseJobs ? SOURCE_TILES : SOURCE_TILES.filter((t) => t.value !== "job");
  const baseId = useId();

  const [source, setSource] = useState<Source>("text");
  const [text, setText] = useState(initialText);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<JobPickerJob | null>(null);
  const [client, setClient] = useState<ClientRef | null>(null);
  const [budget, setBudget] = useState("");
  const [officeDays, setOfficeDays] = useState("");
  const [officeCity, setOfficeCity] = useState("");
  const [touched, setTouched] = useState(false);

  // Każde otwarcie to nowy request — tekst z pola wyszukiwania wygrywa.
  useEffect(() => {
    if (!open) return;
    setTouched(false);
    if (initialText.trim()) {
      setSource("text");
      setText(initialText);
    }
  }, [open, initialText]);

  const budgetError = radarBudgetError(budget);
  const officeDaysError = radarOfficeDaysError(officeDays);
  const needsClient = kind === "goal" || source !== "job";
  const showCity = officeDays.trim() !== "" && Number(officeDays) > 0;

  const problem: string | null = (() => {
    if (kind === "goal") {
      if (goalText.trim().length < REQUEST_TEXT_MIN_LENGTH) {
        return `Opisz, co osoba ma zrobić (min. ${REQUEST_TEXT_MIN_LENGTH} znaków).`;
      }
      return client ? null : "Wybierz klienta.";
    }
    if (source === "text" && text.trim().length < REQUEST_TEXT_MIN_LENGTH) {
      return `Wklej treść requestu (min. ${REQUEST_TEXT_MIN_LENGTH} znaków).`;
    }
    if (source === "file" && !file) return "Wybierz plik profilu Championa.";
    if (source === "job" && !job) return "Wybierz rekrutację.";
    if (needsClient && !client) return "Wybierz klienta.";
    if (needsClient && (budgetError || officeDaysError)) return "Popraw liczby w formularzu.";
    return null;
  })();

  const startGoal = useMutation({
    mutationFn: () => dutySearchApi.start({ client_id: client?.id, goal: goalText.trim() }),
    onSuccess: (started) => {
      onOpenChange(false);
      router.push(`/candidates?mode=goal&run=${encodeURIComponent(started.run_id)}`);
    },
  });

  const submit = () => {
    setTouched(true);
    if (problem) return;
    if (kind === "goal") {
      startGoal.mutate();
      return;
    }
    onSubmit({
      source,
      text: source === "text" ? text.trim() : undefined,
      file: source === "file" ? file : null,
      // Talent Radar tylko pokazuje tytuł — ten z nagłówka rekrutacji (16.10.2026).
      job: source === "job" && job ? { id: job.id, title: jobDisplayTitle(job), client_name: job.client_name ?? null } : null,
      client: needsClient ? client : null,
      budget: needsClient ? budget.trim() : undefined,
      officeDays: needsClient ? officeDays.trim() : undefined,
      officeCity: needsClient && showCity ? officeCity.trim() : undefined,
    });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Szukaj z requestu</DialogTitle>
          <DialogDescription>
            {kind === "goal"
              ? "Opisz, co osoba ma zrobić. AI znajdzie, kto już robił coś takiego, i pokaże cytat z CV."
              : "Przemielimy całą bazę pod request klienta — bez zakładania rekrutacji."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[65dvh] space-y-5 overflow-y-auto">
          <div role="tablist" aria-label="Rodzaj wyszukiwania" className="inline-flex rounded-md border border-border p-0.5">
            {(
              [
                { value: "request", label: "Request klienta", icon: FileText },
                { value: "goal", label: "Cel projektu", icon: Target },
              ] as const
            ).map((item) => {
              const Icon = item.icon;
              const active = kind === item.value;
              return (
                <button
                  key={item.value}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  data-testid={`request-kind-${item.value}`}
                  data-tour={item.value === "goal" ? "candidates.request.goal-tab" : undefined}
                  onClick={() => {
                    setKind(item.value);
                    setTouched(false);
                  }}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  {item.label}
                </button>
              );
            })}
          </div>

          {kind === "goal" && (
            <div className="space-y-1.5">
              <Label htmlFor={`${baseId}-goal`}>Co osoba ma zrobić?</Label>
              <Textarea
                id={`${baseId}-goal`}
                value={goalText}
                onChange={(e) => setGoalText(e.target.value)}
                rows={6}
                maxLength={6000}
                placeholder="Np. „Mamy 40 aplikacji na VMware w serwerowni klienta. Trzeba je przenieść do AWS, przygotować sieć i konta, a na koniec wyłączyć data center”. Obowiązki, cel, skala, branża — zwykłym językiem."
              />
              <p className="text-xs text-muted-foreground">
                AI rozpisze cel na rzeczy do sprawdzenia w CV, przeczyta ok. 100 najbliższych CV i podzieli je na
                „robił to / bardzo blisko / ma klocki”. Trwa 1,5–2 min, limit 10 wyszukiwań dziennie.
              </p>
            </div>
          )}

          {kind === "request" && (
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium text-foreground">
              Skąd bierzemy wymagania?
            </legend>
            <div
              role="radiogroup"
              aria-label="Źródło wymagań"
              className={cn("grid gap-2", tiles.length === 3 ? "sm:grid-cols-3" : "sm:grid-cols-2")}
            >
              {tiles.map((tile) => {
                const active = source === tile.value;
                const Icon = tile.icon;
                return (
                  <button
                    key={tile.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setSource(tile.value)}
                    className={cn(
                      "flex flex-col items-start gap-1 rounded-lg border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active
                        ? "border-primary bg-primary/5"
                        : "border-border bg-card hover:bg-accent",
                    )}
                  >
                    <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} aria-hidden />
                    <span className="text-sm font-medium text-foreground">{tile.title}</span>
                    <span className="text-xs text-muted-foreground">{tile.hint}</span>
                  </button>
                );
              })}
            </div>
          </fieldset>
          )}

          {kind === "request" && source === "text" && (
            <div className="space-y-1.5">
              <Label htmlFor={`${baseId}-text`}>Treść requestu</Label>
              <Textarea
                id={`${baseId}-text`}
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={6}
                maxLength={20_000}
                placeholder="Wklej maila od klienta, opis stanowiska albo listę wymagań — jak leci."
              />
            </div>
          )}
          {kind === "request" && source === "file" && (
            <div className="space-y-1.5">
              <Label htmlFor={`${baseId}-file`}>Plik profilu Championa</Label>
              <input
                id={`${baseId}-file`}
                type="file"
                accept=".docx,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-sm hover:file:bg-accent"
              />
              <p className="text-xs text-muted-foreground">
                {file ? `Wybrano: ${file.name}` : "Odczytamy wymagania, stawkę i nazwę roli; przed wyszukaniem pokażemy je do sprawdzenia."}
              </p>
            </div>
          )}
          {kind === "request" && source === "job" && (
            <div className="space-y-1.5">
              <JobPicker value={job} onChange={setJob} />
              <p className="text-xs text-muted-foreground">
                Klient, hiring manager, budżet i wymagania pochodzą z zapisanej rekrutacji.
              </p>
            </div>
          )}

          {needsClient && (
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5 sm:col-span-3">
                <Label>
                  Klient <span className="text-destructive">*</span>
                </Label>
                <TalentRadarClientPicker value={client} onChange={setClient} />
              </div>
              {kind === "request" && (
              <div className="space-y-1.5">
                <Label htmlFor={`${baseId}-budget`}>Budżet (zł/h)</Label>
                <Input
                  id={`${baseId}-budget`}
                  type="number"
                  min={1}
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                  placeholder="np. 150"
                  aria-invalid={budgetError ? true : undefined}
                />
                {budgetError && <p className="text-xs text-destructive">{budgetError}</p>}
              </div>
              )}
              {kind === "request" && (
              <div className="space-y-1.5">
                <Label htmlFor={`${baseId}-days`}>Dni w biurze</Label>
                <Input
                  id={`${baseId}-days`}
                  type="number"
                  min={0}
                  max={7}
                  value={officeDays}
                  onChange={(e) => setOfficeDays(e.target.value)}
                  placeholder="0 = zdalnie"
                  aria-invalid={officeDaysError ? true : undefined}
                />
                {officeDaysError && <p className="text-xs text-destructive">{officeDaysError}</p>}
              </div>
              )}
              {kind === "request" && showCity && (
                <div className="space-y-1.5">
                  <Label htmlFor={`${baseId}-city`}>Miasto biura</Label>
                  <Input
                    id={`${baseId}-city`}
                    value={officeCity}
                    onChange={(e) => setOfficeCity(e.target.value)}
                    placeholder="np. Warszawa"
                    maxLength={200}
                  />
                </div>
              )}
            </div>
          )}

          {kind === "request" && (
          <p className="text-xs text-muted-foreground">
            Resztę (umiejętności, staż, miasto) odczytamy z treści. W następnym kroku
            możesz je poprawić.
          </p>
          )}
          {touched && problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
          {startGoal.isError && (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(startGoal.error, "Nie udało się uruchomić wyszukiwania.")}
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={startGoal.isPending}>
            {kind === "goal" ? "Szukaj, kto już to robił" : "Dalej: sprawdź wymagania"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
