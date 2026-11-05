"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { CompanySection, type CompanyPeriod } from "@/components/phone-preview/CompanySection";
import { MyMonthSection, MyPortfolioSection } from "@/components/phone-preview/MyResultsSection";
import { PREVIEW_PATH, resultsKind } from "@/components/phone-preview/access";
import { PageHeader } from "@/components/phone-preview/ui";
import { chooseFullVersion, fullVersionHref } from "@/components/phone-preview/usePhonePreviewRedirect";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

const PERIODS: Array<[CompanyPeriod, string]> = [["month", "Miesiąc"], ["quarter", "Kwartał"], ["year", "Rok"]];
const TITLES = { company: "Jak idzie firma", portfolio: "Mój portfel", month: "Mój miesiąc" } as const;

export default function PhonePreviewResultsPage() {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const router = useRouter();
  const kind = resultsKind(user);
  // Domyślnie ukryte przy każdym otwarciu: stan celowo nie trafia do pamięci przeglądarki.
  const [hidden, setHidden] = useState(true);
  const [period, setPeriod] = useState<CompanyPeriod>("quarter");

  useEffect(() => {
    if (hydrated && user && kind === null) router.replace(`${PREVIEW_PATH}/zespol`);
  }, [hydrated, user, kind, router]);

  if (!kind) return null;
  return (
    <div className="pb-6">
      <PageHeader
        title={TITLES[kind]}
        sub="Tylko podgląd"
        right={kind === "company" ? (
          <button
            type="button"
            onClick={() => setHidden((v) => !v)}
            aria-label={hidden ? "Pokaż kwoty" : "Ukryj kwoty"}
            aria-pressed={!hidden}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-muted"
          >
            {hidden ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
          </button>
        ) : undefined}
      />
      {kind === "company" ? (
        <>
          <div className="grid grid-cols-3 gap-1 px-4 pt-3">
            {PERIODS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={period === key}
                onClick={() => setPeriod(key)}
                className={cn("h-10 rounded-lg text-sm font-medium", period === key ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}
              >
                {label}
              </button>
            ))}
          </div>
          <CompanySection hidden={hidden} period={period} />
        </>
      ) : kind === "portfolio" ? (
        <MyPortfolioSection />
      ) : (
        <MyMonthSection />
      )}
      <p className="px-4 pt-6 text-center text-sm">
        <Link href={fullVersionHref(user)} onClick={chooseFullVersion} className="inline-flex h-11 items-center font-medium text-primary">
          Pełna wersja NEXUSA
        </Link>
      </p>
    </div>
  );
}
