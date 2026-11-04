"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/Toast";
import { UserMultiSelect } from "@/components/v2/filters/UserMultiSelect";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ESIGN_SETTINGS_KEY,
  b2bEsignApi,
  type EsignMode,
} from "@/lib/api/b2bEsign";

const MODES: { value: EsignMode; label: string; hint: string }[] = [
  { value: "off", label: "Wyłączony", hint: "Wszystko jak dotąd — mail i „Oznacz jako podpisaną”." },
  {
    value: "pilot",
    label: "Pilotaż",
    hint: "„W NEXUSIE” widzą tylko wybrane osoby; reszta działa jak dotąd.",
  },
  {
    value: "all",
    label: "Dla wszystkich",
    hint: "Każdy, kto wysyła umowy, może wybrać „W NEXUSIE”. Droga zwykła zostaje.",
  },
];

/** Ustawienia → Integracje → „Podpis umów B2B w NEXUSIE” (admin). */
export function EsignSettingsCard() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ESIGN_SETTINGS_KEY, queryFn: b2bEsignApi.settings });
  const [mode, setMode] = useState<EsignMode>("off");
  const [pilot, setPilot] = useState<number[]>([]);
  const [signers, setSigners] = useState<number[]>([]);

  useEffect(() => {
    if (!settings.data) return;
    setMode(settings.data.mode);
    setPilot(settings.data.pilot_user_ids ?? []);
    setSigners(settings.data.company_signers.map((p) => p.id));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      b2bEsignApi.saveSettings({ mode, pilot_user_ids: pilot, company_signer_ids: signers }),
    onSuccess: (data) => {
      queryClient.setQueryData(ESIGN_SETTINGS_KEY, data);
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      toast.showSuccess("Ustawienia podpisu w NEXUSIE zapisane.");
    },
  });

  if (settings.isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytuję ustawienia…
      </p>
    );
  }
  if (settings.isError) {
    return (
      <Alert
        variant="error"
        title="Nie udało się wczytać ustawień"
        description={apiErrorMessage(settings.error, "Spróbuj ponownie za chwilę.")}
      />
    );
  }

  const needsSigner = mode !== "off" && signers.length === 0;
  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-foreground">Zakres</legend>
        {MODES.map((option) => (
          <label
            key={option.value}
            className="flex cursor-pointer items-start gap-2 rounded-lg border border-border p-3 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5"
          >
            <input
              type="radio"
              name="b2b-esign-mode"
              className="mt-0.5 accent-primary"
              checked={mode === option.value}
              onChange={() => setMode(option.value)}
            />
            <span>
              <span className="font-medium text-foreground">{option.label}</span>
              <span className="block text-xs text-muted-foreground">{option.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {mode === "pilot" ? (
        <div className="space-y-1">
          <Label>Kto wysyła w pilotażu</Label>
          <UserMultiSelect
            value={pilot}
            onChange={setPilot}
            placeholder="Wybierz osoby"
            searchPlaceholder="Szukaj osoby…"
            triggerWidthClass="w-full sm:w-80"
            ariaLabel="Kto wysyła w pilotażu"
          />
        </div>
      ) : null}
      <div className="space-y-1">
        <Label>Kto podpisuje za B2B Network</Label>
        <UserMultiSelect
          value={signers}
          onChange={setSigners}
          placeholder="Wybierz reprezentantów"
          searchPlaceholder="Szukaj osoby…"
          triggerWidthClass="w-full sm:w-80"
          ariaLabel="Kto podpisuje za B2B Network"
        />
        <p className="text-xs text-muted-foreground">
          Imienni reprezentanci z podpisem kwalifikowanym. Pierwsza osoba jest domyślna
          w oknie wysyłki.
        </p>
      </div>
      {needsSigner ? (
        <Alert
          variant="warning"
          title="Brak reprezentanta"
          description="Bez osoby podpisującej za B2B Network nikt nie wyśle umowy w NEXUSIE."
        />
      ) : null}
      {save.isError ? (
        <Alert
          variant="error"
          title="Nie udało się zapisać"
          description={apiErrorMessage(save.error, "Spróbuj ponownie.")}
        />
      ) : null}
      <Button onClick={() => save.mutate()} disabled={save.isPending}>
        {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        Zapisz
      </Button>
    </div>
  );
}
