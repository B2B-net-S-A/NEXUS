"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { LEAVE_TYPE_LABELS } from "@/components/hr/leave/leave-format";
import { CATEGORY_LABELS } from "@/components/hr/payroll/payroll-format";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import type { BonusCategory } from "@/lib/api/hr-payroll";
import type { LeaveType } from "@/lib/api/hr-leave";
import {
  usePaymentSettings,
  useSavePaymentSettings,
  type PaymentSettings,
} from "@/lib/api/hr-payments";
import { resolveViewState } from "@/lib/view-state";

const LEAVE_ORDER = Object.keys(LEAVE_TYPE_LABELS) as LeaveType[];
const BONUS_ORDER = Object.keys(CATEGORY_LABELS) as BonusCategory[];
const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;

/** Suma kontrolna IBAN (mod 97) dla rachunku w Polsce — jak na serwerze. */
export function isValidPlAccount(raw: string): boolean {
  let value = raw.replace(/[\s-]+/g, "").toUpperCase();
  if (value.startsWith("PL")) value = value.slice(2);
  if (!/^\d{26}$/.test(value)) return false;
  const rearranged = `${value.slice(2)}2521${value.slice(0, 2)}`;
  let remainder = 0;
  for (let start = 0; start < rearranged.length; start += 7) {
    remainder = Number(`${remainder}${rearranged.slice(start, start + 7)}`) % 97;
  }
  return remainder === 1;
}

/**
 * Formularz → ciało `PUT /api/hr/payments/settings` albo zdanie błędu.
 * Serwer sprawdza to samo (422) — tu, żeby błąd był widać przed zapisem.
 */
export function paymentSettingsPayload(
  form: PaymentSettings,
): { payload: PaymentSettings } | { error: string } {
  const day = Number(form.payout_day);
  if (!Number.isInteger(day) || day < 1 || day > 31) {
    return { error: "Dzień wypłaty: liczba od 1 do 31." };
  }
  const account = (form.transfer_batch.sender_account ?? "").trim();
  if (account && !isValidPlAccount(account)) {
    return { error: "Rachunek nadawcy: 26 cyfr z poprawną sumą kontrolną (opcjonalnie z PL)." };
  }
  // Puste pole = zostaje zapisany rachunek (serwer pokazuje tylko jego 4 cyfry).
  const hasAccount = Boolean(account || form.transfer_batch.sender_account_last4);
  if (form.transfer_batch.enabled && (!hasAccount || !form.transfer_batch.sender_name.trim())) {
    return { error: "Paczka przelewów wymaga rachunku i nazwy nadawcy (firmy)." };
  }
  if (!TIME.test(form.symfonia.work_start) || Number(form.symfonia.work_start.slice(0, 2)) > 15) {
    return { error: "Początek dnia pracy: GG:MM, najpóźniej 15:59." };
  }
  if (!form.symfonia.contract_kind.trim() || !form.symfonia.payment_form.trim()) {
    return { error: "Rodzaj umowy i forma płatności są potrzebne w pliku rozliczeń zleceń." };
  }
  const trimmed = (names: Record<string, string>) =>
    Object.fromEntries(
      Object.entries(names)
        .map(([key, value]) => [key, value.trim()])
        .filter(([, value]) => value),
    );
  return {
    payload: {
      payout_day: day,
      transfer_batch: {
        enabled: form.transfer_batch.enabled,
        format: form.transfer_batch.format,
        sender_account: account || null,
        sender_name: form.transfer_batch.sender_name.trim(),
      },
      symfonia: {
        ...form.symfonia,
        overtime_event: form.symfonia.overtime_event.trim(),
        contract_kind: form.symfonia.contract_kind.trim(),
        payment_form: form.symfonia.payment_form.trim(),
        leave_events: trimmed(form.symfonia.leave_events),
        bonus_components: trimmed(form.symfonia.bonus_components),
      },
    },
  };
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
      {children}
    </h3>
  );
}

/**
 * Ustawienia → Płace → „Płatności i Symfonia” (etap 4, R5 i R9): dzień
 * wypłaty zlecenia i UoP (termin rozliczenia), paczka przelewów (opcja,
 * domyślnie wyłączona) i słowniki do paczki dla Symfonii. Puste pole nazwy =
 * ten rodzaj nie trafia do pliku i jest na liście „do zrobienia ręcznie”.
 */
export function PaymentSettingsCard() {
  const settings = usePaymentSettings();
  const save = useSavePaymentSettings();
  const { showToast } = useToast();
  const [form, setForm] = useState<PaymentSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const state = resolveViewState({
    isLoading: settings.isLoading,
    isError: settings.isError,
    error: settings.error,
    isSuccess: settings.isSuccess,
  });
  if (state === "forbidden" || state === "not_found") return null;
  const current = form ?? settings.data ?? null;

  const update = (change: (value: PaymentSettings) => PaymentSettings) => {
    if (current) setForm(change(current));
  };

  const submit = () => {
    if (!current) return;
    const parsed = paymentSettingsPayload(current);
    if ("error" in parsed) {
      setError(parsed.error);
      return;
    }
    setError(null);
    save.mutate(parsed.payload, {
      onSuccess: () => {
        setForm(null);
        showToast("Ustawienia płatności zapisane", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać ustawień.")),
    });
  };

  return (
    <Card className="space-y-5 p-5">
      <div>
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Płatności i Symfonia
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Termin wypłaty zlecenia i UoP, paczka przelewów do banku i nazwy z Symfonii do
          paczki importu. Przelewy domyślnie robią Finanse w eBI24 albo w banku.
        </p>
      </div>
      {state === "loading" || !current ? (
        state === "error" ? (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            Nie udało się wczytać ustawień.
            <Button size="sm" variant="ghost" onClick={() => settings.refetch()}>
              Spróbuj ponownie
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Wczytywanie ustawień…</p>
        )
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <FormField label="Dzień wypłaty zlecenia i UoP (następny miesiąc)">
              <Input
                inputMode="numeric"
                className="h-8 w-24"
                value={String(current.payout_day)}
                onChange={(event) =>
                  update((value) => ({
                    ...value,
                    payout_day: Number(event.target.value.replace(/\D/g, "")) || 0,
                  }))
                }
              />
            </FormField>
          </div>

          <div className="space-y-3">
            <SectionTitle>Paczka przelewów</SectionTitle>
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={current.transfer_batch.enabled}
                onCheckedChange={(checked) =>
                  update((value) => ({
                    ...value,
                    transfer_batch: { ...value.transfer_batch, enabled: checked },
                  }))
                }
                aria-label="Paczka przelewów do banku"
              />
              Płace pobierają paczkę przelewów faktur B2B do banku
            </label>
            {current.transfer_batch.enabled ? (
              <div className="grid gap-3 md:grid-cols-3">
                <FormField label="Format pliku">
                  <div className="flex gap-1">
                    {(["elixir", "csv"] as const).map((format) => (
                      <Button
                        key={format}
                        size="sm"
                        variant={current.transfer_batch.format === format ? "secondary" : "ghost"}
                        aria-pressed={current.transfer_batch.format === format}
                        onClick={() =>
                          update((value) => ({
                            ...value,
                            transfer_batch: { ...value.transfer_batch, format },
                          }))
                        }
                      >
                        {format === "elixir" ? "Elixir-O" : "CSV"}
                      </Button>
                    ))}
                  </div>
                </FormField>
                <FormField
                  label="Rachunek firmy (nadawca)"
                  description={
                    current.transfer_batch.sender_account_last4
                      ? `Zapisany rachunek •• ${current.transfer_batch.sender_account_last4} — wpisz nowy, żeby go zmienić.`
                      : undefined
                  }
                >
                  <Input
                    className="h-8"
                    value={current.transfer_batch.sender_account ?? ""}
                    placeholder="PL00 0000 0000 0000 0000 0000 0000"
                    onChange={(event) =>
                      update((value) => ({
                        ...value,
                        transfer_batch: {
                          ...value.transfer_batch,
                          sender_account: event.target.value,
                        },
                      }))
                    }
                  />
                </FormField>
                <FormField label="Nazwa i adres nadawcy">
                  <Input
                    className="h-8"
                    maxLength={140}
                    value={current.transfer_batch.sender_name}
                    onChange={(event) =>
                      update((value) => ({
                        ...value,
                        transfer_batch: { ...value.transfer_batch, sender_name: event.target.value },
                      }))
                    }
                  />
                </FormField>
              </div>
            ) : null}
          </div>

          <div className="space-y-3">
            <SectionTitle>Symfonia — nieobecności i nadgodziny</SectionTitle>
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={current.symfonia.export_sick_leave}
                onCheckedChange={(checked) =>
                  update((value) => ({
                    ...value,
                    symfonia: { ...value.symfonia, export_sick_leave: checked },
                  }))
                }
                aria-label="Eksport zwolnień lekarskich"
              />
              Płace nie pobierają e-ZLA z PUE ZUS — dołączaj L4 do pliku zdarzeń
            </label>
            <div className="grid gap-3 md:grid-cols-3">
              <FormField label="Zdarzenie nadgodzin">
                <Input
                  className="h-8"
                  value={current.symfonia.overtime_event}
                  onChange={(event) =>
                    update((value) => ({
                      ...value,
                      symfonia: { ...value.symfonia, overtime_event: event.target.value },
                    }))
                  }
                />
              </FormField>
              <FormField label="Początek dnia pracy (koniec normy po 8 h)">
                <Input
                  className="h-8 w-24"
                  value={current.symfonia.work_start}
                  onChange={(event) =>
                    update((value) => ({
                      ...value,
                      symfonia: { ...value.symfonia, work_start: event.target.value },
                    }))
                  }
                />
              </FormField>
            </div>
            <div className="grid gap-x-4 gap-y-2 md:grid-cols-2">
              {LEAVE_ORDER.map((type) => (
                <FormField key={type} label={LEAVE_TYPE_LABELS[type]}>
                  <Input
                    className="h-8"
                    aria-label={`Zdarzenie w Symfonii: ${LEAVE_TYPE_LABELS[type]}`}
                    placeholder="nazwa z Definicji zdarzeń"
                    value={current.symfonia.leave_events[type] ?? ""}
                    onChange={(event) =>
                      update((value) => ({
                        ...value,
                        symfonia: {
                          ...value.symfonia,
                          leave_events: {
                            ...value.symfonia.leave_events,
                            [type]: event.target.value,
                          },
                        },
                      }))
                    }
                  />
                </FormField>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <SectionTitle>Symfonia — premie i zlecenia</SectionTitle>
            <div className="grid gap-x-4 gap-y-2 md:grid-cols-2">
              {BONUS_ORDER.map((category) => (
                <FormField key={category} label={`Premia: ${CATEGORY_LABELS[category]}`}>
                  <Input
                    className="h-8"
                    aria-label={`Kolumna premii: ${CATEGORY_LABELS[category]}`}
                    value={current.symfonia.bonus_components[category] ?? ""}
                    onChange={(event) =>
                      update((value) => ({
                        ...value,
                        symfonia: {
                          ...value.symfonia,
                          bonus_components: {
                            ...value.symfonia.bonus_components,
                            [category]: event.target.value,
                          },
                        },
                      }))
                    }
                  />
                </FormField>
              ))}
              <FormField label="Rodzaj umowy w pliku rozliczeń">
                <Input
                  className="h-8"
                  value={current.symfonia.contract_kind}
                  onChange={(event) =>
                    update((value) => ({
                      ...value,
                      symfonia: { ...value.symfonia, contract_kind: event.target.value },
                    }))
                  }
                />
              </FormField>
              <FormField label="Forma płatności w pliku rozliczeń">
                <Input
                  className="h-8"
                  value={current.symfonia.payment_form}
                  onChange={(event) =>
                    update((value) => ({
                      ...value,
                      symfonia: { ...value.symfonia, payment_form: event.target.value },
                    }))
                  }
                />
              </FormField>
            </div>
          </div>

          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button onClick={submit} disabled={save.isPending || form === null}>
              {save.isPending ? "Zapisywanie…" : "Zapisz ustawienia"}
            </Button>
            {form !== null ? (
              <Button variant="ghost" onClick={() => setForm(null)}>
                Odrzuć zmiany
              </Button>
            ) : null}
          </div>
        </>
      )}
    </Card>
  );
}
