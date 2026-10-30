"use client";

// Ustawienia → Zespół i dostęp → „Nowości — kto już umie” — kontener:
// react-query i przypomnienia. Widok: `components/settings/novelties`.
// Dostęp: admin i Head of Recruitment (middleware `/settings/nowosci`
// + `HeadOfRecruitmentPlus` w `backend/app/api/novelties.py`).

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import {
  NoveltiesAdoptionView,
  type AdoptionLoad,
} from "@/components/settings/novelties/NoveltiesAdoptionView";
import { apiErrorMessage } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import {
  adoptionKey,
  remindNovelty,
  setStartGate,
  startKey,
  useNoveltiesAdoption,
  useStartStatus,
} from "@/lib/novelties/api";
import { isForbiddenError } from "@/lib/view-state";

export default function NoveltiesAdoptionPage() {
  const query = useNoveltiesAdoption();
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [remindingId, setRemindingId] = useState<string | null>(null);

  let load: AdoptionLoad;
  if (query.isSuccess) {
    load = { status: "success", items: query.data };
  } else if (query.isError) {
    const forbidden = isForbiddenError(query.error);
    load = {
      status: "error",
      forbidden,
      message: forbidden
        ? "Panel nowości widzą administrator i Head of Recruitment."
        : apiErrorMessage(query.error, "Nie udało się wczytać nowości."),
    };
  } else {
    load = { status: "loading" };
  }

  const onRemind = async (noveltyId: string, userIds: number[]) => {
    setRemindingId(noveltyId);
    try {
      const reminded = await remindNovelty(noveltyId, userIds);
      showSuccess(
        reminded === 0
          ? "Nikomu nie trzeba było przypominać."
          : `Przypomniano ${reminded} ${reminded === 1 ? "osobie" : "osobom"} — karta wróci przy kropce.`,
      );
      await queryClient.invalidateQueries({ queryKey: adoptionKey });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać przypomnienia."));
    } finally {
      setRemindingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <StartGateSwitch />
      <NoveltiesAdoptionView
        load={load}
        onRetry={() => void query.refetch()}
        onRemind={onRemind}
        remindingId={remindingId}
      />
    </div>
  );
}

/**
 * Wyłącznik blokady „Start w NEXUSIE” dla całej firmy (30.10.2026). Na wypadek,
 * gdyby rano przeklikanie kogoś zatrzymało — bez deployu, jednym kliknięciem.
 */
function StartGateSwitch() {
  const status = useStartStatus(true);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [saving, setSaving] = useState(false);
  if (!status) return null;

  const toggle = async () => {
    setSaving(true);
    try {
      const on = await setStartGate(!status.gate_on);
      showSuccess(
        on
          ? "Blokada Startu włączona — kto nie przeklikał, zobaczy listę Startu."
          : "Blokada Startu wyłączona — nikt nie jest zatrzymywany.",
      );
      await queryClient.invalidateQueries({ queryKey: startKey });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić blokady Startu."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-4"
      aria-label="Blokada Start w NEXUSIE"
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          Start w NEXUSIE: blokada {status.gate_on ? "włączona" : "wyłączona"}
        </p>
        <p className="text-xs text-muted-foreground">
          {status.gate_on
            ? "Kto nie przeklikał najważniejszych funkcji swojej roli, widzi tylko pulpit i listę Startu. Postęp osób jest niżej, przy pozycjach „Start”."
            : "Lista Startu jest dostępna, ale nikogo nie zatrzymuje."}
        </p>
      </div>
      <Button
        size="sm"
        variant={status.gate_on ? "outline" : "primary"}
        disabled={saving}
        onClick={() => void toggle()}
      >
        {status.gate_on ? "Wyłącz blokadę" : "Włącz blokadę"}
      </Button>
    </section>
  );
}
