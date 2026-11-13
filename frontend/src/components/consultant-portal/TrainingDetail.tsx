"use client";

/**
 * Szkolenie trenera w panelu: pasek etapów i ekran bieżącego kroku.
 * Zamówienie → Wycena (Zał. 1) → Umowa (podpis kwalifikowany) → Szkolenie → Przekazanie → Faktura.
 * Lustro `backend/app/services/trainings/core.py` (`trainer_view`).
 */
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Download, FileText, Plus, Trash2, Upload, Video } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  portalApi,
  portalKeys,
  usePortalQuery,
  type AgreementVersion,
  type DeliverableKey,
  type FeeKey,
  type PortalTraining,
  type TrainingAgendaItem,
  type TrainingHandoverItem,
} from "@/lib/api/consultant-portal";
import { safeExternalHref } from "@/lib/safe-href";
import { cn } from "@/lib/utils";

import { Fact, Failure, Loading, Panel } from "./PanelScreens";
import { saveBlob } from "./portal-model";
import {
  AGENDA_MAX,
  FEE_SHORT,
  HANDOVER_LABELS,
  STEPS,
  agendaProblem,
  agendaTotal,
  currentStep,
  feeApplies,
  feeSum,
  isEditorProject,
  minutesLabel,
  missingFees,
  moneyLabel,
  parseAmount,
  shortDay,
  warsawToday,
} from "./training-model";

const HANDOVER_TONE = {
  missing: "neutral",
  submitted: "info",
  accepted: "success",
  returned: "warning",
} as const;

function Banner({ tone = "info", children }: { tone?: "info" | "warning" | "success"; children: ReactNode }) {
  const tones = {
    info: "border-info/20 bg-info-muted text-info-muted-foreground",
    warning: "border-warning/25 bg-warning-muted text-warning-muted-foreground",
    success: "border-success/20 bg-success-muted text-success-muted-foreground",
  };
  return <div className={cn("rounded-xl border p-3 text-sm", tones[tone])}>{children}</div>;
}

function ErrorLine({ text }: { text: string | null }) {
  return text ? (
    <p role="alert" className="text-sm text-destructive">
      {text}
    </p>
  ) : null;
}

/** Przycisk z ukrytym polem pliku: jeden plik, wybór od razu wysyła. */
export function FilePick({
  label,
  accept,
  busy,
  onFile,
  variant = "outline",
}: {
  label: string;
  accept?: string;
  busy?: boolean;
  onFile: (file: File) => void;
  variant?: "outline" | "primary";
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant={variant}
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        <Upload aria-hidden className="size-3.5" /> {busy ? "Wysyłamy…" : label}
      </Button>
      <input
        ref={input}
        type="file"
        accept={accept}
        aria-label={label}
        className="sr-only"
        tabIndex={-1}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) onFile(file);
        }}
      />
    </>
  );
}

export function StepBar({ step }: { step: number }) {
  const list = useRef<HTMLOListElement>(null);
  // Na telefonie pasek się przewija: bieżący etap ma być widoczny bez szukania.
  useEffect(() => {
    const current = list.current?.querySelector<HTMLElement>('[aria-current="step"]');
    if (list.current && current) list.current.scrollLeft = Math.max(0, current.offsetLeft - 16);
  }, [step]);
  return (
    <ol ref={list} aria-label="Etapy szkolenia" className="relative flex gap-1 overflow-x-auto pb-1">
      {STEPS.map((label, index) => {
        const done = index < step;
        const current = index === step;
        return (
          <li
            key={label}
            aria-current={current ? "step" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-xs",
              done && "border-success/20 bg-success-muted text-success-muted-foreground",
              current && "border-primary bg-primary text-primary-foreground",
              !done && !current && "bg-card text-muted-foreground",
            )}
          >
            {done ? <Check aria-hidden className="size-3" /> : null}
            {label}
          </li>
        );
      })}
    </ol>
  );
}

function useTrainingUpdate(id: number) {
  const client = useQueryClient();
  return async (training: PortalTraining) => {
    client.setQueryData(portalKeys.training(id), { training });
    await Promise.all([
      client.invalidateQueries({ queryKey: portalKeys.trainings }),
      client.invalidateQueries({ queryKey: portalKeys.todo }),
    ]);
  };
}

// ── Dane zamówienia ──────────────────────────────────────────────────────────

function OrderCard({ training }: { training: PortalTraining }) {
  const { order } = training;
  const hours = order.time_from && order.time_to ? `${order.time_from}–${order.time_to}` : "do ustalenia";
  return (
    <Panel title="Dane szkolenia">
      <p className="-mt-2 mb-3 text-xs text-muted-foreground">Wpisało Talent Community, nie zmieniasz ich.</p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Termin" value={shortDay(order.session_date) || "do ustalenia"} />
        <Fact label="Godziny" value={hours} />
        <Fact
          label="Uczestnicy"
          value={order.expected_participants ? `ok. ${order.expected_participants}` : "bez limitu"}
        />
        <Fact label="Gdzie" value={`zdalnie, ${order.platform || "Teams"}`} />
      </dl>
      {order.description ? <p className="mt-3 whitespace-pre-line text-sm">{order.description}</p> : null}
      {order.participant_materials ? (
        <p className="mt-2 text-sm">
          <span className="text-muted-foreground">Materiały dla uczestników: </span>
          {order.participant_materials}
        </p>
      ) : null}
      {order.knowledge_test ? (
        <p className="mt-2 text-sm text-muted-foreground">Zamówienie obejmuje test wiedzy dla uczestników.</p>
      ) : null}
      {order.extra_terms ? (
        <p className="mt-2 whitespace-pre-line text-sm">
          <span className="text-muted-foreground">Dodatkowe ustalenia: </span>
          {order.extra_terms}
        </p>
      ) : null}
    </Panel>
  );
}

function DeliverablesCard({ training }: { training: PortalTraining }) {
  return (
    <Panel title="Pliki, które przekażesz">
      <p className="-mt-2 mb-2 text-xs text-muted-foreground">Zaznaczyło Talent Community. Format to wymóg umowy.</p>
      <ul className="divide-y text-sm">
        {training.order.deliverables.map((item) => (
          <li key={item.key} className="flex items-start justify-between gap-3 py-2 first:pt-0 last:pb-0">
            <span className="min-w-0">
              <span className="block font-medium">{item.label}</span>
              {item.format ? <span className="block text-xs text-muted-foreground">{item.format}</span> : null}
            </span>
            {item.due_days !== null ? (
              <Badge variant="neutral" className="shrink-0">
                {item.due_days === 0 ? "w dniu szkolenia" : `${item.due_days} dni po`}
              </Badge>
            ) : null}
          </li>
        ))}
      </ul>
      {training.order.deliverables.length === 0 ? (
        <p className="text-sm text-muted-foreground">Zamówienie nie obejmuje plików do przekazania.</p>
      ) : null}
    </Panel>
  );
}

// ── Wycena ───────────────────────────────────────────────────────────────────

function initialAgenda(training: PortalTraining): TrainingAgendaItem[] {
  return training.quote.agenda.length ? training.quote.agenda : [{ title: "", minutes: null }];
}

function initialAmounts(training: PortalTraining): Partial<Record<FeeKey, string>> {
  return Object.fromEntries(
    training.fees.items.map((fee) => [fee.key, fee.amount ? String(Number(fee.amount)).replace(".", ",") : ""]),
  );
}

function amountPayload(value: string | undefined): string | null {
  const parsed = parseAmount(value ?? "");
  return parsed === null ? null : parsed.toFixed(2);
}

export function QuoteForm({ training }: { training: PortalTraining }) {
  const update = useTrainingUpdate(training.id);
  const editable = training.can_quote;
  const ordered: DeliverableKey[] = training.order.deliverables.map((item) => item.key);
  const [agenda, setAgenda] = useState<TrainingAgendaItem[]>(() => initialAgenda(training));
  const [amounts, setAmounts] = useState(() => initialAmounts(training));
  const [ownMaterials, setOwnMaterials] = useState(training.quote.own_materials);
  const [thirdParty, setThirdParty] = useState(training.quote.third_party_materials);
  const [note, setNote] = useState(training.quote.quote_note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const total = agendaTotal(agenda);
  const sum = feeSum(training.fees.items, amounts, ordered);
  const has = (key: DeliverableKey) => ordered.includes(key);
  const presentation = training.order.deliverables.find((item) => item.key === "presentation");

  const setRow = (index: number, patch: Partial<TrainingAgendaItem>) =>
    setAgenda((rows) => rows.map((row, at) => (at === index ? { ...row, ...patch } : row)));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const problem = agendaProblem(agenda);
    if (problem) return setError(problem);
    const missing = missingFees(training.fees.items, amounts, ordered);
    if (missing.length) return setError(`Wpisz kwotę: ${missing.map((key) => FEE_SHORT[key]).join(", ")}.`);
    setBusy(true);
    try {
      const answer = await portalApi.saveQuote(training.id, {
        agenda: agenda
          .filter((row) => row.title.trim())
          .map((row) => ({ title: row.title.trim(), minutes: Number(row.minutes) })),
        fee_prep: amountPayload(amounts.fee_prep),
        fee_delivery: amountPayload(amounts.fee_delivery),
        fee_presentation: has("presentation") ? amountPayload(amounts.fee_presentation) : null,
        fee_audio: has("audio") ? amountPayload(amounts.fee_audio) : null,
        fee_rights: amountPayload(amounts.fee_rights),
        own_materials: ownMaterials.trim(),
        third_party_materials: thirdParty.trim(),
        quote_note: note.trim(),
      });
      await update(answer.training);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać wyceny. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-4">
        <OrderCard training={training} />
        <Panel title="Agenda">
          <p className="-mt-2 mb-3 text-xs text-muted-foreground">
            Moduły 1–{AGENDA_MAX}, czas w minutach. Z modułów powstaną rozdziały nagrania.
          </p>
          <ol className="space-y-2">
            {agenda.map((row, index) => (
              <li key={index} className="flex items-center gap-2">
                <span className="w-5 shrink-0 text-right text-xs text-muted-foreground">{index + 1}</span>
                <Input
                  aria-label={`Moduł ${index + 1}: temat`}
                  placeholder="Temat modułu"
                  value={row.title}
                  disabled={!editable}
                  onChange={(event) => setRow(index, { title: event.target.value })}
                />
                <Input
                  aria-label={`Moduł ${index + 1}: minuty`}
                  inputMode="numeric"
                  className="w-20 shrink-0 text-right"
                  placeholder="min"
                  value={row.minutes ?? ""}
                  disabled={!editable}
                  onChange={(event) => {
                    const digits = event.target.value.replace(/\D/g, "").slice(0, 3);
                    setRow(index, { minutes: digits ? Number(digits) : null });
                  }}
                />
                {editable && agenda.length > 1 ? (
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Usuń moduł ${index + 1}`}
                    onClick={() => setAgenda((rows) => rows.filter((_row, at) => at !== index))}
                  >
                    <Trash2 aria-hidden className="size-4" />
                  </Button>
                ) : null}
              </li>
            ))}
          </ol>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm">
            {editable && agenda.length < AGENDA_MAX ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setAgenda((rows) => [...rows, { title: "", minutes: null }])}
              >
                <Plus aria-hidden className="size-3.5" /> Moduł
              </Button>
            ) : (
              <span />
            )}
            <span data-testid="agenda-total" className="font-semibold">
              Razem {minutesLabel(total)}
            </span>
          </div>
          {training.order.duration_minutes ? (
            <p className="mt-1 text-right text-xs text-muted-foreground">
              Zamówienie: {minutesLabel(training.order.duration_minutes)} na żywo
            </p>
          ) : null}
        </Panel>
        <DeliverablesCard training={training} />
        <Panel title="Materiały, których nie przenosisz">
          <p className="-mt-2 mb-3 text-xs text-muted-foreground">
            Twoje materiały sprzed umowy i materiały osób trzecich zostają przy właścicielu.
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">Twoje, sprzed umowy</span>
              <Textarea
                rows={2}
                placeholder="np. grafiki z mojego kursu"
                value={ownMaterials}
                disabled={!editable}
                onChange={(event) => setOwnMaterials(event.target.value)}
              />
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">Osób trzecich</span>
              <Textarea
                rows={2}
                placeholder="Brak"
                value={thirdParty}
                disabled={!editable}
                onChange={(event) => setThirdParty(event.target.value)}
              />
            </label>
          </div>
        </Panel>
      </div>
      <div className="min-w-0 space-y-4">
        <Panel title="Wycena netto">
          <table className="w-full text-sm">
            <tbody>
              {training.fees.items.map((fee) =>
                feeApplies(fee, ordered) ? (
                  <tr key={fee.key}>
                    <td className="py-1 pr-2">
                      <label htmlFor={`fee-${fee.key}`}>{FEE_SHORT[fee.key]}</label>
                    </td>
                    <td className="w-28 py-1">
                      <Input
                        id={`fee-${fee.key}`}
                        inputMode="decimal"
                        className="text-right"
                        placeholder="zł"
                        value={amounts[fee.key] ?? ""}
                        disabled={!editable}
                        onChange={(event) => setAmounts((now) => ({ ...now, [fee.key]: event.target.value }))}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={fee.key} className="text-muted-foreground">
                    <td className="py-1 pr-2">{FEE_SHORT[fee.key]}</td>
                    <td className="py-1 text-right text-xs">nie dotyczy</td>
                  </tr>
                ),
              )}
              <tr className="border-t font-semibold">
                <td className="pt-2">Razem netto</td>
                <td data-testid="fee-sum" className="pt-2 text-right">
                  {moneyLabel(sum)}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">VAT doliczasz, jeśli jesteś jego płatnikiem.</p>
        </Panel>
        <Panel title="Co wyceniasz">
          <ul className="space-y-1.5 text-xs text-muted-foreground">
            <li>
              <span className="font-semibold text-foreground">A</span> agenda, ćwiczenia, materiały dla uczestników
            </li>
            <li>
              <span className="font-semibold text-foreground">B</span>{" "}
              {training.order.duration_minutes ? `${minutesLabel(training.order.duration_minutes)} na żywo` : "szkolenie na żywo"}
              ; liczba osób nie zmienia kwoty (§ 3 ust. 11)
            </li>
            {has("presentation") ? (
              <li>
                <span className="font-semibold text-foreground">C</span> slajdy przekazane w formacie z zamówienia
                {presentation?.format ? ` (${presentation.format})` : ""}
              </li>
            ) : null}
            {has("audio") ? (
              <li>
                <span className="font-semibold text-foreground">D</span> gotowe pliki audio z zamówienia
              </li>
            ) : null}
            <li>
              <span className="font-semibold text-foreground">E</span> przeniesienie praw z § 8, osobna kwota
            </li>
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">
            Jeśli nie wykonasz któregoś elementu, ta część wynagrodzenia nie przysługuje (§ 11). Pozycję, której nie ma
            w zamówieniu, zostawiasz pustą.
          </p>
        </Panel>
        {editable ? (
          <Panel>
            <label className="block space-y-1.5 text-sm">
              <span className="font-medium">Uwagi do wyceny</span>
              <Textarea rows={2} value={note} onChange={(event) => setNote(event.target.value)} />
            </label>
            <div className="mt-3 space-y-2">
              <ErrorLine text={error} />
              <Button type="submit" className="w-full" disabled={busy}>
                {busy ? "Wysyłamy…" : "Wyślij wycenę"}
              </Button>
            </div>
          </Panel>
        ) : null}
      </div>
    </form>
  );
}

// ── Umowa ────────────────────────────────────────────────────────────────────

function useAgreementDownload(training: PortalTraining) {
  const [error, setError] = useState<string | null>(null);
  const download = async (version: AgreementVersion) => {
    setError(null);
    try {
      const suffix = version === "draft" ? "" : version === "trainer" ? " podpisana przez Ciebie" : " podpisana";
      const number = training.agreement.number ? ` ${training.agreement.number.replaceAll("/", "-")}` : "";
      saveBlob(await portalApi.agreementPdf(training.id, version), `Umowa szkoleniowa${number}${suffix}.pdf`);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się pobrać umowy."));
    }
  };
  return { download, error };
}

export function SigningGuide() {
  return (
    <Panel title="Jak podpisać">
      <ol className="list-decimal space-y-1.5 pl-4 text-xs text-muted-foreground">
        <li>Pobierz PDF umowy z Załącznikiem nr 1 i nr 2.</li>
        <li>
          Podpisz plik kwalifikowanym podpisem elektronicznym w formacie PAdES (podpis w samym PDF), np. w mObywatelu,
          SimplySign albo Szafirze.
        </li>
        <li>Wgraj podpisany PDF tutaj. Potem podpisuje B2B Network i dostaniesz komplet.</li>
      </ol>
      <p className="mt-3 text-xs text-muted-foreground">
        Skan odręcznego podpisu ani zgoda w mailu się nie liczą: umowę zawieramy w formie elektronicznej z podpisem
        kwalifikowanym (§ 17).
      </p>
    </Panel>
  );
}

export function AgreementStep({ training }: { training: PortalTraining }) {
  const update = useTrainingUpdate(training.id);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { download, error: downloadError } = useAgreementDownload(training);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (file: File) => {
    setError(null);
    if (!file.name.toLowerCase().endsWith(".pdf")) return setError("Wgraj podpisaną umowę jako PDF.");
    const yes = await askConfirm({
      title: "Wysłać podpisaną umowę?",
      description: `${file.name}. Sprawdzimy podpis kwalifikowany, a potem umowę podpisze B2B Network.`,
      confirmLabel: "Wyślij",
      cancelLabel: "Wróć",
    });
    if (!yes) return;
    setBusy(true);
    try {
      await update((await portalApi.uploadSignature(training.id, file)).training);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać umowy. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };

  const { status, agreement } = training;
  return (
    <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-4">
        <Panel title={agreement.number ? `Umowa ${agreement.number}` : "Umowa szkoleniowa"}>
          {status === "accepted" && !training.can_sign ? (
            <p className="text-sm text-muted-foreground">
              Przyjęliśmy Twoją wycenę i przygotowujemy umowę. Damy znać mailem, gdy będzie do podpisu.
            </p>
          ) : null}
          {status === "accepted" && training.can_sign ? (
            <div className="space-y-3 text-sm">
              <p>Przyjęliśmy Twoją wycenę. Umowa z Załącznikiem nr 1 (Twoja wycena) i nr 2 (RODO) czeka na Twój podpis.</p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => download("draft")}>
                  <Download aria-hidden className="size-3.5" /> Pobierz umowę (PDF)
                </Button>
                <FilePick label="Wgraj podpisany PDF" accept=".pdf,application/pdf" busy={busy} variant="primary" onFile={upload} />
              </div>
            </div>
          ) : null}
          {status === "trainer_signed" ? (
            <div className="space-y-3 text-sm">
              <p>
                Twój podpis mamy{agreement.trainer_signed_at ? ` od ${shortDay(agreement.trainer_signed_at)}` : ""}. Umowa
                czeka na podpis B2B Network, potem dostaniesz komplet.
              </p>
              <Button size="sm" variant="outline" onClick={() => download("trainer")}>
                <Download aria-hidden className="size-3.5" /> Pobierz podpisaną przez Ciebie
              </Button>
            </div>
          ) : null}
          <div className="mt-2 space-y-1">
            <ErrorLine text={error} />
            <ErrorLine text={downloadError} />
          </div>
        </Panel>
        <OrderCard training={training} />
      </div>
      <div className="min-w-0 space-y-4">
        <SigningGuide />
        <FeesSummary training={training} />
      </div>
      {confirmDialog}
    </div>
  );
}

function FeesSummary({ training }: { training: PortalTraining }) {
  const ordered = training.order.deliverables.map((item) => item.key);
  return (
    <Panel title="Twoja wycena">
      <table className="w-full text-sm">
        <tbody>
          {training.fees.items
            .filter((fee) => feeApplies(fee, ordered))
            .map((fee) => (
              <tr key={fee.key}>
                <td className="py-0.5 pr-2">{FEE_SHORT[fee.key]}</td>
                <td className="py-0.5 text-right">{moneyLabel(fee.amount)}</td>
              </tr>
            ))}
          <tr className="border-t font-semibold">
            <td className="pt-1.5">Razem netto</td>
            <td className="pt-1.5 text-right">{moneyLabel(training.fees.total)}</td>
          </tr>
        </tbody>
      </table>
      {training.quote.agenda.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Agenda: {training.quote.agenda.length} moduły, {minutesLabel(agendaTotal(training.quote.agenda))}
        </p>
      ) : null}
    </Panel>
  );
}

function SignedAgreementCard({ training }: { training: PortalTraining }) {
  const { download, error } = useAgreementDownload(training);
  return (
    <Panel title="Umowa">
      <p className="text-sm">
        Podpisana kwalifikowanym
        {training.agreement.company_signed_at ? ` ${shortDay(training.agreement.company_signed_at)}` : ""} przez obie
        strony.
      </p>
      <p className="mt-1 text-xs text-muted-foreground">Umowa, Załącznik nr 1, Załącznik nr 2 (RODO)</p>
      <Button size="sm" variant="outline" className="mt-3" onClick={() => download("signed")}>
        <Download aria-hidden className="size-3.5" /> Pobierz PDF
      </Button>
      <div className="mt-2">
        <ErrorLine text={error} />
      </div>
      <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        Prawa do materiałów przechodzą na B2B Network z chwilą zapłaty (§ 8 ust. 3). Do tego czasu materiały służą tylko
        temu szkoleniu.
      </p>
    </Panel>
  );
}

// ── Przekazanie plików i faktura ─────────────────────────────────────────────

function HandoverRow({ training, item }: { training: PortalTraining; item: TrainingHandoverItem }) {
  const update = useTrainingUpdate(training.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const returned = item.files.find((file) => file.status === "returned");

  const upload = async (file: File) => {
    setError(null);
    if (isEditorProject(file.name)) {
      return setError("To plik projektu montażowego. Wgraj gotowy plik w formacie z zamówienia.");
    }
    setBusy(true);
    try {
      await update((await portalApi.uploadDeliverable(training.id, item.key, file)).training);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wgrać pliku. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="py-3 first:pt-0 last:pb-0" data-testid={`handover-${item.key}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0 text-sm">
          <span className="block font-medium">
            {item.label}
            {item.format ? <span className="font-normal text-muted-foreground"> · {item.format}</span> : null}
          </span>
          <span className="block break-all text-xs text-muted-foreground">
            {item.files.length
              ? item.files.map((file) => file.file_name).join(", ")
              : item.key === "audio"
                ? "Wgraj gotowy plik. Projekt montażowy (np. .drp) nie zostanie przyjęty."
                : item.due_days !== null
                  ? `Termin: ${item.due_days === 0 ? "w dniu szkolenia" : `${item.due_days} dni po szkoleniu`}`
                  : "Wgraj gotowy plik."}
          </span>
        </span>
        <span className="flex shrink-0 flex-wrap items-center gap-2">
          <Badge variant={HANDOVER_TONE[item.state]}>
            {HANDOVER_LABELS[item.state]}
            {item.state === "returned" && returned?.fix_due_on ? ` do ${shortDay(returned.fix_due_on)}` : ""}
          </Badge>
          {training.can_deliver && item.state !== "accepted" ? (
            <FilePick label={item.state === "missing" ? "Wgraj" : "Wgraj nowy"} busy={busy} onFile={upload} />
          ) : null}
        </span>
      </div>
      {item.state === "returned" && returned ? (
        <div className="mt-2">
          <Banner tone="warning">
            {returned.review_note ? <>Talent Community: „{returned.review_note}”. </> : null}
            {returned.fix_due_on
              ? `Masz czas na poprawę do ${shortDay(returned.fix_due_on)} (3 dni robocze, § 11 ust. 4).`
              : "Wgraj poprawiony plik."}
          </Banner>
        </div>
      ) : null}
      <div className="mt-1">
        <ErrorLine text={error} />
      </div>
    </li>
  );
}

export function HandoverChecklist({ training }: { training: PortalTraining }) {
  const accepted = training.handover.filter((item) => item.state === "accepted").length;
  return (
    <Panel
      title="Pliki do przekazania"
      action={
        training.handover.length ? (
          <span className="text-xs text-muted-foreground">
            Przyjęte {accepted} z {training.handover.length}
          </span>
        ) : undefined
      }
    >
      {training.handover.length === 0 ? (
        <p className="text-sm text-muted-foreground">Zamówienie nie obejmuje plików do przekazania.</p>
      ) : (
        <ul className="divide-y">
          {training.handover.map((item) => (
            <HandoverRow key={item.key} training={training} item={item} />
          ))}
        </ul>
      )}
      <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        Pozycja liczy się po przyjęciu przez Talent Community. Nowy plik zastępuje poprzedni w tej pozycji. Pliki
        projektu montażowego (np. .drp) i surowe nagrania nie zostaną przyjęte.
      </p>
    </Panel>
  );
}

const INVOICE_STATUS: Record<string, string> = {
  submitted: "Wysłana, czeka na sprawdzenie",
  accepted: "Przyjęta",
  returned: "Do poprawy",
  replaced: "Zastąpiona",
};

export function InvoiceCard({ training }: { training: PortalTraining }) {
  const update = useTrainingUpdate(training.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { payment } = training;

  const upload = async (file: File) => {
    setError(null);
    if (!file.name.toLowerCase().endsWith(".pdf")) return setError("Fakturę wgraj jako PDF.");
    setBusy(true);
    try {
      await update((await portalApi.uploadInvoice(training.id, file)).training);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać faktury. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Faktura">
      {payment.paid_at ? (
        <Banner tone="success">Zapłacone {shortDay(payment.paid_at)}. Dziękujemy za szkolenie.</Banner>
      ) : training.can_invoice ? (
        <div className="space-y-3 text-sm">
          <Banner tone="success">Możesz wystawić fakturę.</Banner>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Fact label="Kwota netto" value={moneyLabel(training.fees.total) || "według wyceny"} />
            <Fact
              label="Tytuł"
              value={`Szkolenie „${training.order.title}”${training.agreement.number ? `, umowa ${training.agreement.number}` : ""}`}
            />
            <Fact label="Termin płatności" value="14 dni" />
          </dl>
          <FilePick label="Wgraj fakturę (PDF)" accept=".pdf,application/pdf" busy={busy} variant="primary" onFile={upload} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Gdy Talent Community przyjmie wszystkie pliki, zobaczysz tu „Możesz wystawić fakturę”: kwotę, tytuł i termin
          płatności 14 dni.
        </p>
      )}
      {training.invoices.length ? (
        <ul className="mt-3 divide-y border-t pt-2 text-sm">
          {training.invoices.map((file) => (
            <li key={file.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="flex min-w-0 items-center gap-1.5 break-all">
                <FileText aria-hidden className="size-3.5 shrink-0 text-muted-foreground" /> {file.file_name}
              </span>
              <span className="text-xs text-muted-foreground">{INVOICE_STATUS[file.status] ?? file.status}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-2">
        <ErrorLine text={error} />
      </div>
    </Panel>
  );
}

// ── Ekran szkolenia ──────────────────────────────────────────────────────────

/** Dzień szkolenia: trener wchodzi tym samym linkiem co uczestnicy, jako prowadzący. */
function LeadCard({ training }: { training: PortalTraining }) {
  const { order } = training;
  const href = training.join_url ? safeExternalHref(training.join_url) : null;
  const hours = order.time_from && order.time_to ? `, ${order.time_from}–${order.time_to}` : "";
  return (
    <section className="rounded-xl border border-primary bg-primary/5 p-4">
      <p className="text-xs uppercase tracking-[0.08em] text-muted-foreground">Szkolenie</p>
      <h2 className="mt-1 text-lg font-semibold">
        {shortDay(order.session_date)}
        {hours}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {training.registrations ? `Zapisanych: ${training.registrations}. ` : ""}
        Spotkanie nagrywa się samo, nagrywania nie włączasz.
      </p>
      {href ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button asChild size="sm">
            <a href={href} target="_blank" rel="noopener noreferrer">
              <Video aria-hidden className="size-3.5" /> Dołącz jako prowadzący
            </a>
          </Button>
          <span className="text-xs text-muted-foreground">Wejdź 15 minut wcześniej, żeby sprawdzić dźwięk i ekran.</span>
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          Link do spotkania pojawi się tutaj, gdy Talent Community założy spotkanie.
        </p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">Pliki z Załącznika nr 1 przekażesz po szkoleniu.</p>
    </section>
  );
}

/** Po szkoleniu: nagranie z Teams i oceny uczestników (bez nazwisk). */
function AfterCard({ training }: { training: PortalTraining }) {
  const feedback = training.feedback;
  if (!training.recording_ready && !(feedback && feedback.count > 0)) return null;
  return (
    <Panel title="Po szkoleniu">
      {training.recording_ready ? (
        <p className="text-sm text-muted-foreground">Nagranie z Teams jest już w szkoleniu. Nie musisz go wgrywać.</p>
      ) : null}
      {feedback && feedback.count > 0 ? (
        <div className="mt-2 space-y-1">
          <p className="text-sm font-medium">
            Ocena uczestników: {feedback.average?.toFixed(1).replace(".", ",")} / 5 ({feedback.count})
          </p>
          {(feedback.comments ?? []).slice(0, 5).map((comment, index) => (
            <p key={index} className="text-xs text-muted-foreground">
              „{comment}”
            </p>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

function SubLine({ training }: { training: PortalTraining }) {
  const { order } = training;
  const parts = ["Zamówienie od Talent Community"];
  if (training.can_quote && order.quote_due_on) parts.push(`odpowiedz do ${shortDay(order.quote_due_on)}`);
  parts.push(`szkolenie zdalne w ${order.platform || "Teams"}`);
  return <p className="text-sm text-muted-foreground">{parts.join(" · ")}</p>;
}

export function TrainingDetailView({ training, today = warsawToday() }: { training: PortalTraining; today?: string }) {
  const step = currentStep(training, today);
  const { status } = training;
  return (
    <div className="min-w-0 space-y-4">
      <Link href="/konsultant/szkolenia" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft aria-hidden className="size-3.5" /> Szkolenia
      </Link>
      {status !== "cancelled" ? <StepBar step={step} /> : null}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{training.order.title}</h1>
          <Badge variant={status === "cancelled" ? "neutral" : "soft"}>{training.status_label}</Badge>
        </div>
        <SubLine training={training} />
      </div>
      {status === "returned" && training.quote.return_note ? (
        <Banner tone="warning">
          <span className="font-medium">Wycena wróciła do poprawy. </span>
          Talent Community: „{training.quote.return_note}”
        </Banner>
      ) : null}
      {status === "quoted" ? (
        <Banner>
          Wycena wysłana{training.quote.quoted_at ? ` ${shortDay(training.quote.quoted_at)}` : ""}. Czekamy na decyzję
          Talent Community i damy znać mailem.
        </Banner>
      ) : null}
      {status === "cancelled" ? (
        <Banner>To szkolenie zostało anulowane. W razie pytań napisz w zakładce Pomoc.</Banner>
      ) : null}
      {status === "ordered" || status === "returned" || status === "quoted" ? (
        <QuoteForm key={`${training.id}-${status}`} training={training} />
      ) : null}
      {status === "accepted" || status === "trainer_signed" ? <AgreementStep training={training} /> : null}
      {status === "signed" ? (
        <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-4">
            {step === 3 ? <LeadCard training={training} /> : null}
            <AfterCard training={training} />
            <HandoverChecklist training={training} />
            <InvoiceCard training={training} />
          </div>
          <div className="min-w-0 space-y-4">
            <SignedAgreementCard training={training} />
            <FeesSummary training={training} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function TrainingDetailScreen({ id }: { id: number }) {
  const query = usePortalQuery(portalKeys.training(id), () => portalApi.training(id), Number.isInteger(id));
  if (!Number.isInteger(id)) return <Failure error={null} text="Nie ma takiego szkolenia." />;
  if (query.isLoading) return <Loading />;
  if (query.isError) return <Failure error={query.error} text="Nie udało się wczytać szkolenia. Odśwież stronę." />;
  return query.data ? <TrainingDetailView training={query.data.training} /> : null;
}
