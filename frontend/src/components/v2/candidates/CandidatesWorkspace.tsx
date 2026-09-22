"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { CandidatesListV2 } from "@/components/v2/pages/CandidatesListV2";
import {
  CandidateSearchView,
  JOB_URL_PARAM,
} from "@/components/v2/pages/CandidateSearchView";
import {
  TalentRadarWorkspace,
  type TalentRadarInitialRequest,
} from "@/components/talent-radar/TalentRadarWorkspace";
import {
  CANDIDATES_MODE_PARAM,
  candidatesModeHref,
  parseCandidatesMode,
} from "@/lib/candidates-mode";
import { searchStateToListHref } from "@/lib/candidates-search-redirect";

/**
 * Jeden ekran „Kandydaci" (uproszczenie 22.09.2026): lista z filtrami po
 * lewej i jednym polem wyszukiwania. Nie ma już zakładek trybów.
 *
 * Stare adresy dalej działają:
 * - `?mode=search` bez rekrutacji → stan wyszukiwarki (`?s=`) przechodzi na
 *   listę (`router.replace`, bez nowego wpisu historii);
 * - `?mode=search&job=…` → wyszukiwarka z wybraną rekrutacją, jak dotąd;
 * - `?mode=request` → wyniki „Szukaj z requestu" (Talent Radar) z linkiem
 *   powrotu. Dane z okna „Z requestu" idą STANEM, nigdy adresem — treść
 *   requestu klienta bywa długa i poufna.
 */

// Stały obiekt: wyszukiwarka dopisuje go do adresu przy każdej zmianie filtra.
const SEARCH_URL_PARAMS = { [CANDIDATES_MODE_PARAM]: "search" };

function BackToCandidates() {
  return (
    <Link
      href="/candidates"
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" aria-hidden />
      Kandydaci
    </Link>
  );
}

export function CandidatesWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const mode = parseCandidatesMode(searchParams?.get(CANDIDATES_MODE_PARAM));
  const jobParam = searchParams?.get(JOB_URL_PARAM) ?? null;
  const legacySearchWithoutJob = mode === "search" && !jobParam;
  const [requestSeed, setRequestSeed] = useState<
    (TalentRadarInitialRequest & { key: number }) | null
  >(null);

  useEffect(() => {
    if (!legacySearchWithoutJob) return;
    router.replace(searchStateToListHref(new URLSearchParams(searchParams?.toString() ?? "")));
  }, [legacySearchWithoutJob, router, searchParams]);

  const startRequest = useCallback(
    (initial: TalentRadarInitialRequest) => {
      setRequestSeed({ ...initial, key: Date.now() });
      router.push(candidatesModeHref("request"));
    },
    [router],
  );

  if (legacySearchWithoutJob) return null;

  if (mode === "search") {
    return (
      <div className="space-y-3">
        <BackToCandidates />
        <CandidateSearchView syncUrl hideHeader persistUrlParams={SEARCH_URL_PARAMS} />
      </div>
    );
  }

  if (mode === "request") {
    return (
      <div className="space-y-3">
        <BackToCandidates />
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          Szukaj z requestu
        </h1>
        <TalentRadarWorkspace
          key={requestSeed?.key ?? "radar"}
          embedded
          initial={requestSeed ?? undefined}
        />
      </div>
    );
  }

  return <CandidatesListV2 onRequestSearch={startRequest} />;
}
