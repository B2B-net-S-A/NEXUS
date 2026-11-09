"use client";

// Ustawienia → Zespół rekrutacji → „Jakość generatora CV” — kontener: react-query.
// Widok: `components/settings/generator-quality`. Dostęp: admin i Head of Recruitment
// (middleware `/settings/jakosc-generatora` + `HeadOfRecruitmentPlus`
// w `backend/app/api/cv_generator_feedback.py`).

import { useState } from "react";

import {
  GeneratorQualityView,
  type GeneratorQualityLoad,
} from "@/components/settings/generator-quality/GeneratorQualityView";
import { apiErrorMessage } from "@/lib/api-error";
import { useGeneratorFeedbackSummary } from "@/lib/cv-generator-feedback";
import { isForbiddenError } from "@/lib/view-state";

export default function GeneratorQualityPage() {
  const [days, setDays] = useState(30);
  const query = useGeneratorFeedbackSummary(days);

  let load: GeneratorQualityLoad;
  if (query.isSuccess) {
    load = { status: "success", summary: query.data };
  } else if (query.isError) {
    const forbidden = isForbiddenError(query.error);
    load = {
      status: "error",
      forbidden,
      message: forbidden
        ? "Zestawienie widzą administrator i Head of Recruitment."
        : apiErrorMessage(query.error, "Nie udało się wczytać zgłoszeń."),
    };
  } else {
    load = { status: "loading" };
  }

  return (
    <GeneratorQualityView
      load={load}
      days={days}
      onDaysChange={setDays}
      onRetry={() => void query.refetch()}
    />
  );
}
