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
import {
  adoptionKey,
  remindNovelty,
  useNoveltiesAdoption,
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
    <NoveltiesAdoptionView
      load={load}
      onRetry={() => void query.refetch()}
      onRemind={onRemind}
      remindingId={remindingId}
    />
  );
}
