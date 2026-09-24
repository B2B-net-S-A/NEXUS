"use client";

import { useState } from "react";
import { ArrowRight, CheckCircle2, Copy, Phone } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { TraineeItem } from "@/lib/api/trainee";
import {
  AVAILABILITY_OPTIONS,
  B2B_OPTIONS,
  OPEN_TO_OFFERS_OPTIONS,
  OUTCOME_LABEL,
  RATE_UNIT_OPTIONS,
  REMOTE_MODE_OPTIONS,
  WANTS_MAX,
  WORK_TIME_OPTIONS,
  YES_NO_CALL_OPTIONS,
  isClosed,
  isEmploymentOnly,
  lastContactLabel,
  missingLabel,
  profileRateLabel,
  telHref,
  toggleInList,
  toggleValue,
  whyThisPerson,
  type CallFormValidation,
  type TraineeCallForm,
} from "@/lib/trainee-call";
import { cn } from "@/lib/utils";

import { ToggleGroup } from "./ToggleGroup";

export interface TraineeStatusMessage {
  text: string;
  /** Pozycja, którą można jeszcze przekazać rekruterowi (po zapisanej rozmowie). */
  handoverItemId?: number;
  handoverName?: string;
}

export type TraineeNoCallAction = "noanswer" | "later" | "wrong" | "declined";

interface TraineeCallCardProps {
  item: TraineeItem;
  form: TraineeCallForm;
  onFormChange: (next: TraineeCallForm) => void;
  errors: CallFormValidation["errors"];
  status: TraineeStatusMessage | null;
  actionError: string | null;
  busy: boolean;
  onSave: () => void;
  onNoCall: (action: TraineeNoCallAction) => void;
  onHandover: (itemId: number) => void;
  now?: Date;
}

const LABEL = "text-sm font-medium text-foreground";
const INPUT =
  "h-11 rounded-lg border border-border bg-card px-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-hidden disabled:opacity-50";

function StatusBanner({
  status,
  onHandover,
}: {
  status: TraineeStatusMessage;
  onHandover: (itemId: number) => void;
}) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-success/20 bg-success-muted px-3 py-2 text-sm text-success-muted-foreground"
    >
      <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{status.text}</span>
      {status.handoverItemId != null ? (
        <button
          type="button"
          onClick={() => onHandover(status.handoverItemId as number)}
          className="inline-flex min-h-10 items-center gap-1 rounded-md px-2 text-sm font-semibold underline-offset-4 hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          Przekaż {status.handoverName ?? "tę osobę"} rekruterowi
          <ArrowRight className="h-4 w-4" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

function PhoneBlock({ phone }: { phone: string | null }) {
  const [copied, setCopied] = useState(false);
  const tel = telHref(phone);
  if (!phone) {
    return <span className="text-sm text-muted-foreground">Brak numeru telefonu</span>;
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(phone);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-lg font-semibold tabular-nums text-foreground">{phone}</span>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Skopiowano numer" : "Kopiuj numer"}
        title={copied ? "Skopiowano" : "Kopiuj numer"}
        className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-border text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        {copied ? <CheckCircle2 className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
      </button>
      {tel ? (
        <a
          href={tel}
          className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <Phone className="h-4 w-4" aria-hidden />
          Zadzwoń
        </a>
      ) : null}
    </div>
  );
}

function FieldError({ id, text }: { id: string; text: string | undefined }) {
  if (!text) return null;
  return (
    <p id={id} role="alert" className="text-xs font-medium text-destructive">
      {text}
    </p>
  );
}

/**
 * Środkowa karta: kim jest osoba, dlaczego do niej dzwonimy, formularz
 * rozmowy (dwa zestawy pól z makiety) i wyniki bez rozmowy.
 */
export function TraineeCallCard({
  item,
  form,
  onFormChange,
  errors,
  status,
  actionError,
  busy,
  onSave,
  onNoCall,
  onHandover,
  now,
}: TraineeCallCardProps) {
  const set = <K extends keyof TraineeCallForm>(key: K, value: TraineeCallForm[K]) =>
    onFormChange({ ...form, [key]: value });
  const employmentOnly = isEmploymentOnly(form);
  const closed = isClosed(item);
  const subtitle = [item.role, item.company, item.city].filter(Boolean).join(" · ");

  return (
    <section
      aria-label="Rozmowa"
      className="flex min-w-0 flex-col gap-4 rounded-xl border border-border bg-card p-4 md:p-5"
    >
      {status ? <StatusBanner status={status} onHandover={onHandover} /> : null}

      <div className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-foreground">{item.name}</h2>
          {subtitle ? <p className="text-sm text-muted-foreground">{subtitle}</p> : null}
          <p className="mt-1 text-xs text-muted-foreground">
            {item.in_base_since ? `W bazie od ${item.in_base_since} · ` : ""}
            ostatni kontakt z nami: {lastContactLabel(item.last_contact_at, now)}
          </p>
        </div>
        <PhoneBlock phone={item.phone} />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg bg-muted px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Dlaczego ta osoba
          </span>
          <p className="mt-1 text-sm text-foreground">{whyThisPerson(item.reasons)}</p>
        </div>
        <div className="rounded-lg bg-muted px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Czego brakuje w profilu
          </span>
          <p className="mt-1 flex flex-wrap gap-1">
            {item.reasons.missing.length === 0 ? (
              <span className="text-sm text-muted-foreground">Profil jest kompletny.</span>
            ) : (
              item.reasons.missing.map((code) => (
                <span
                  key={code}
                  className="rounded border border-warning/25 bg-warning-muted px-1.5 py-0.5 text-xs text-warning-muted-foreground"
                >
                  {missingLabel(code)}
                </span>
              ))
            )}
          </p>
        </div>
      </div>

      {closed ? (
        <div className="flex flex-col gap-3 rounded-lg border border-border px-4 py-3">
          <p className="text-sm text-foreground">
            Pozycja zamknięta:{" "}
            <b className="font-semibold">{item.outcome ? OUTCOME_LABEL[item.outcome] : "wynik zapisany"}</b>
            {item.later_date ? ` (telefon ${item.later_date.split("-").reverse().join(".")})` : ""}.
          </p>
          {item.outcome === "call" ? (
            <div>
              <Button variant="outline" size="lg" onClick={() => onHandover(item.id)}>
                Przekaż rekruterowi
                <ArrowRight className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          ) : null}
        </div>
      ) : (
        <>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              onSave();
            }}
            noValidate
          >
            <fieldset className="grid gap-x-6 gap-y-4 rounded-xl border border-border px-4 pb-4 pt-3 md:grid-cols-2">
              <legend className="px-1 text-sm font-semibold text-foreground">
                Pieniądze · B2B netto
              </legend>
              <div className="flex flex-col gap-2 md:col-span-2">
                <span id={`b2b-${item.id}`} className={LABEL}>
                  Współpraca na B2B <span className="text-destructive">*</span>
                </span>
                <ToggleGroup
                  labelledBy={`b2b-${item.id}`}
                  options={B2B_OPTIONS}
                  isPressed={(v) => form.b2b === v}
                  onToggle={(v) => set("b2b", toggleValue(form.b2b, v))}
                />
                <FieldError id={`b2b-err-${item.id}`} text={errors.b2b} />
                {employmentOnly ? (
                  <div
                    role="status"
                    className="rounded-lg border border-destructive/20 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground"
                  >
                    Nie pracujemy na umowę o pracę, więc ta osoba wypadnie z list telefonów i z
                    wyszukiwarki AI. Stawki i biura nie trzeba już pytać — zapisz rozmowę.
                  </div>
                ) : null}
              </div>
              {!employmentOnly ? (
                <>
                  <div className="flex flex-col gap-2">
                    <label htmlFor={`rate-${item.id}`} className={LABEL}>
                      Minimalna stawka B2B netto
                    </label>
                    <div className="flex gap-2">
                      <input
                        id={`rate-${item.id}`}
                        type="text"
                        inputMode="decimal"
                        placeholder="np. 135"
                        value={form.rateValue}
                        onChange={(e) => set("rateValue", e.target.value)}
                        aria-invalid={errors.rate ? true : undefined}
                        aria-describedby={errors.rate ? `rate-err-${item.id}` : undefined}
                        className={cn(INPUT, "w-28 min-w-0")}
                      />
                      <select
                        aria-label="Jednostka stawki"
                        value={form.rateUnit}
                        onChange={(e) => set("rateUnit", e.target.value as TraineeCallForm["rateUnit"])}
                        className={cn(INPUT, "min-w-0 flex-1")}
                      >
                        {RATE_UNIT_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      W profilu: {profileRateLabel(item)}
                    </span>
                    <FieldError id={`rate-err-${item.id}`} text={errors.rate} />
                  </div>
                  <div className="flex flex-col gap-2">
                    <span id={`below-${item.id}`} className={LABEL}>
                      Oferta poniżej tej stawki — dzwonić mimo to?
                    </span>
                    <ToggleGroup
                      labelledBy={`below-${item.id}`}
                      options={YES_NO_CALL_OPTIONS}
                      isPressed={(v) => form.acceptsBelowMin === v}
                      onToggle={(v) => set("acceptsBelowMin", toggleValue(form.acceptsBelowMin, v))}
                    />
                    <span className="text-xs text-muted-foreground">
                      „Nie” = wyszukiwarka chowa go przy każdym budżecie poniżej minimum.
                    </span>
                  </div>
                </>
              ) : null}
            </fieldset>

            {!employmentOnly ? (
              <>
                <fieldset className="grid gap-x-6 gap-y-4 rounded-xl border border-border px-4 pb-4 pt-3 md:grid-cols-2">
                  <legend className="px-1 text-sm font-semibold text-foreground">
                    Praca i biuro
                  </legend>
                  <div className="flex flex-col gap-2">
                    <span id={`mode-${item.id}`} className={LABEL}>
                      Tryb pracy
                    </span>
                    <div className="flex flex-wrap items-center gap-2">
                      <ToggleGroup
                        labelledBy={`mode-${item.id}`}
                        options={REMOTE_MODE_OPTIONS}
                        isPressed={(v) => form.remoteModes.includes(v)}
                        onToggle={(v) => set("remoteModes", toggleInList(form.remoteModes, v))}
                      />
                      <label htmlFor={`days-${item.id}`} className="text-xs text-muted-foreground">
                        maks. dni w biurze
                      </label>
                      <input
                        id={`days-${item.id}`}
                        type="text"
                        inputMode="numeric"
                        placeholder="0–5"
                        value={form.maxOnsiteDays}
                        onChange={(e) => set("maxOnsiteDays", e.target.value)}
                        aria-invalid={errors.maxOnsiteDays ? true : undefined}
                        className={cn(INPUT, "w-16")}
                      />
                    </div>
                    <FieldError id={`days-err-${item.id}`} text={errors.maxOnsiteDays} />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label htmlFor={`city-${item.id}`} className={LABEL}>
                      Gdzie może dojeżdżać
                    </label>
                    <input
                      id={`city-${item.id}`}
                      type="text"
                      placeholder={`np. ${item.city ?? "Warszawa"}; zdalnie z całej Polski`}
                      value={form.officeCities}
                      onChange={(e) => set("officeCities", e.target.value)}
                      className={INPUT}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <span id={`office-${item.id}`} className={LABEL}>
                      Projekt wymaga więcej dni w biurze niż podał — dzwonić?
                    </span>
                    <ToggleGroup
                      labelledBy={`office-${item.id}`}
                      options={YES_NO_CALL_OPTIONS}
                      isPressed={(v) => form.acceptsMoreOfficeDays === v}
                      onToggle={(v) =>
                        set("acceptsMoreOfficeDays", toggleValue(form.acceptsMoreOfficeDays, v))
                      }
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <span id={`time-${item.id}`} className={LABEL}>
                      Wymiar pracy
                    </span>
                    <ToggleGroup
                      labelledBy={`time-${item.id}`}
                      options={WORK_TIME_OPTIONS}
                      isPressed={(v) => form.workTime === v}
                      onToggle={(v) => set("workTime", toggleValue(form.workTime, v))}
                    />
                  </div>
                </fieldset>

                <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
                  <div className="flex flex-col gap-2">
                    <span id={`avail-${item.id}`} className={LABEL}>
                      Od kiedy może zacząć
                    </span>
                    <ToggleGroup
                      labelledBy={`avail-${item.id}`}
                      options={AVAILABILITY_OPTIONS}
                      isPressed={(v) => form.availability === v}
                      onToggle={(v) => set("availability", toggleValue(form.availability, v))}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <span id={`open-${item.id}`} className={LABEL}>
                      Czy szuka projektu
                    </span>
                    <ToggleGroup
                      labelledBy={`open-${item.id}`}
                      options={OPEN_TO_OFFERS_OPTIONS}
                      isPressed={(v) => form.openToOffers === v}
                      onToggle={(v) => set("openToOffers", toggleValue(form.openToOffers, v))}
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <label htmlFor={`wants-${item.id}`} className={LABEL}>
                    Czego szuka, czego nie chce
                  </label>
                  <textarea
                    id={`wants-${item.id}`}
                    rows={2}
                    maxLength={WANTS_MAX}
                    placeholder="np. tylko Java/Kotlin, bez utrzymania starych systemów, nie bankowość"
                    value={form.wants}
                    onChange={(e) => set("wants", e.target.value)}
                    className="min-h-16 rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-hidden"
                  />
                  <FieldError id={`wants-err-${item.id}`} text={errors.wants} />
                </div>
              </>
            ) : null}

            {actionError ? (
              <p
                role="alert"
                className="rounded-lg border border-destructive/20 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground"
              >
                {actionError}
              </p>
            ) : null}

            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
              <Button type="submit" size="lg" loading={busy} disabled={busy} className="min-h-11">
                Zapisz rozmowę
              </Button>
              <span className="text-xs text-muted-foreground">albo wynik bez rozmowy:</span>
              {(
                [
                  ["noanswer", "Nie odbiera"],
                  ["later", "Prosi o telefon innego dnia"],
                  ["wrong", "Zły numer"],
                  ["declined", "Niezainteresowany"],
                ] as Array<[TraineeNoCallAction, string]>
              ).map(([action, label]) => (
                <Button
                  key={action}
                  type="button"
                  variant="outline"
                  size="lg"
                  className="min-h-11 px-3"
                  disabled={busy}
                  onClick={() => onNoCall(action)}
                >
                  {label}
                </Button>
              ))}
            </div>
          </form>
        </>
      )}
    </section>
  );
}
