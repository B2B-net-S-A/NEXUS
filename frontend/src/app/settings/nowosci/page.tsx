"use client";

// Ustawienia → Zespół i dostęp → „Nowości — kto już umie” — kontener:
// react-query i przypomnienia. Widok: `components/settings/novelties`.
// Dostęp: admin i Head of Recruitment (middleware `/settings/nowosci`
// + `HeadOfRecruitmentPlus` w `backend/app/api/novelties.py`).

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { KtoZnaNexus } from "@/components/settings/novelties/KtoZnaNexus";
import { LessonStruggles } from "@/components/settings/novelties/LessonStruggles";
import {
  NoveltiesAdoptionView,
  type AdoptionLoad,
} from "@/components/settings/novelties/NoveltiesAdoptionView";
import { apiErrorMessage } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import {
  adoptionKey,
  dailyKey,
  remindNovelty,
  setDailyGate,
  setPoligonGate,
  setStartGate,
  startKey,
  useDailyStatus,
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
          : `Przypomniano ${reminded} ${reminded === 1 ? "osobie" : "osobom"} — nowość czeka w ich porannej porcji.`,
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
      <DailyGateSwitch />
      <StartGateSwitch />
      <PoligonGateSwitch />
      <KtoZnaNexus />
      <LessonStruggles />
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
          ? "Włączone — Start w NEXUSIE znów obowiązuje."
          : "Wyłączone — nikt nie jest zatrzymywany przez Start.",
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
          Start w NEXUSIE:{" "}
          {status.gate_on ? "włączone" : "wyłączone"}
        </p>
        <p className="text-xs text-muted-foreground">
          {status.gate_on
            ? "Kto nie przeklikał najważniejszych funkcji swojej roli, widzi tylko pulpit i listę Startu. Każdy dostaje tylko to, do czego ma dostęp. Postęp osób jest niżej."
            : "Start jest dostępny, ale nikogo nie zatrzymuje."}
        </p>
      </div>
      <Button
        size="sm"
        variant={status.gate_on ? "outline" : "primary"}
        disabled={saving}
        onClick={() => void toggle()}
      >
        {status.gate_on ? "Wyłącz obowiązek" : "Włącz obowiązek"}
      </Button>
    </section>
  );
}

/**
 * Wyłącznik porannej porcji nowości (18.11.2026), osobny od Startu: przy
 * pierwszym wejściu dnia każdy przeklikuje to, co weszło do jego roli. Gdyby
 * rano coś zablokowało ludzi, admin albo HoR zdejmuje porcję bez deployu.
 */
function DailyGateSwitch() {
  const status = useDailyStatus(true);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [saving, setSaving] = useState(false);
  if (!status) return null;
  const on = status.gate_on;

  const toggle = async () => {
    setSaving(true);
    try {
      const next = await setDailyGate(!on);
      showSuccess(
        next
          ? "Włączone — rano każdy najpierw przeklikuje nowości swojej roli."
          : "Wyłączone — nowości czekają na liście, ale nikogo nie zatrzymują.",
      );
      await queryClient.invalidateQueries({ queryKey: dailyKey });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić porannej porcji."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-4"
      aria-label="Poranna porcja nowości"
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          Poranna porcja nowości: {on ? "obowiązkowa" : "wyłączona"}
        </p>
        <p className="text-xs text-muted-foreground">
          {on
            ? "Przy pierwszym wejściu dnia każdy przeklikuje na rekrutacji ćwiczebnej wszystko, co weszło do jego roli i czego jeszcze nie przeszedł. Potem do jutra nic nie wyskakuje."
            : "Lista nowości na dziś jest dostępna, ale nikogo nie zatrzymuje."}
        </p>
      </div>
      <Button
        size="sm"
        variant={on ? "outline" : "primary"}
        disabled={saving}
        onClick={() => void toggle()}
      >
        {on ? "Wyłącz porcję" : "Włącz porcję"}
      </Button>
    </section>
  );
}

/**
 * Wyłącznik blokady Poligonu NEXUSA (15.11.2026), osobny od Startu: nowa osoba
 * stoi na poligonie, dopóki nie zaliczy ćwiczeń. Gdyby ćwiczenie przestało się
 * zaliczać, admin albo HoR zdejmuje blokadę bez deployu.
 */
function PoligonGateSwitch() {
  const status = useStartStatus(true);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [saving, setSaving] = useState(false);
  if (!status || status.poligon_gate_on === undefined) return null;
  const on = status.poligon_gate_on;

  const toggle = async () => {
    setSaving(true);
    try {
      const next = await setPoligonGate(!on);
      showSuccess(
        next
          ? "Włączone — nowa osoba znów przechodzi Poligon, zanim zacznie pracę."
          : "Wyłączone — Poligon jest dostępny, ale nikogo nie zatrzymuje.",
      );
      await queryClient.invalidateQueries({ queryKey: startKey });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić blokady Poligonu."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-4"
      aria-label="Blokada Poligonu NEXUSA"
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          Poligon NEXUSA dla nowych osób: {on ? "obowiązkowy" : "wyłączony"}
        </p>
        <p className="text-xs text-muted-foreground">
          {on
            ? "Nowy rekruter widzi tylko Poligon, dopóki nie zaliczy wszystkich ćwiczeń; dzień onboardingu nie liczy się do jego statystyk. Wyłącz, gdyby ćwiczenie przestało się zaliczać."
            : "Poligon jest dostępny, ale nikogo nie zatrzymuje."}
        </p>
      </div>
      <Button
        size="sm"
        variant={on ? "outline" : "primary"}
        disabled={saving}
        data-tour="settings.nowosci.poligon-gate"
        onClick={() => void toggle()}
      >
        {on ? "Wyłącz blokadę" : "Włącz blokadę"}
      </Button>
    </section>
  );
}
