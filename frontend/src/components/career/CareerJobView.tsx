import type { CareerJobResponse } from "@/lib/career/api";
import { careerHref, careerVisibleUrl, type CareerBase } from "@/lib/career/host";

import type { CareerApplyFormProps } from "./CareerApplyForm";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { CareerThemeScope } from "./CareerThemeScope";
import { ClosedNotice } from "./ClosedNotice";
import { GrafitJob } from "./layouts/GrafitJob";
import { JasnyJob } from "./layouts/JasnyJob";
import { TerminalJob } from "./layouts/TerminalJob";
import type { CareerJobLayoutProps } from "./layouts/types";
import { careerThemeId, type CareerThemeId } from "./themes";

/** Układ strony per szablon (A Terminal, B Jasny, C Grafit — 28.10.2026). */
const LAYOUTS: Record<CareerThemeId, (props: CareerJobLayoutProps) => React.ReactNode> = {
  grafit: GrafitJob,
  terminal: TerminalJob,
  jasny: JasnyJob,
};

/**
 * Strona rekrutacji (`/r/<slug>`): jeden z trzech układów szablonu. Zamknięta
 * rekrutacja → `ClosedNotice`. Po wysłaniu formularza cała strona zamienia się
 * w podziękowanie (`CareerSubmitGate`).
 *
 * Komponent prezentacyjny — dane przychodzą z serwera (strona) albo z mocków
 * (harness `/preview/kariera`).
 */
export function CareerJobView({
  data,
  base,
  host,
  formPreview,
}: {
  data: CareerJobResponse;
  base: CareerBase;
  /** Host żądania do stopki („kariera.b2bnetwork.pl", „nexus.dynaminds.pl"). */
  host: string;
  formPreview?: CareerApplyFormProps["preview"];
}) {
  const { job, recruiter } = data;
  const theme = careerThemeId(data.theme);
  const recruiterHref = recruiter.slug
    ? careerHref(base, { to: "recruiter", slug: recruiter.slug })
    : null;
  const rodoHref = careerHref(base, { to: "rodo" });
  const homeHref = careerHref(base, { to: "home" });
  const visibleUrl = careerVisibleUrl(host, base, { to: "job", slug: job.slug });

  if (data.status === "closed") {
    return (
      <CareerThemeScope theme={theme}>
        <ClosedNotice
          jobTitle={job.title}
          recruiterFirstName={recruiter.first_name}
          recruiterPageHref={recruiterHref}
          otherJobs={data.other_jobs ?? []}
          jobHref={(slug) => careerHref(base, { to: "job", slug })}
          homeHref={homeHref}
          rodoHref={rodoHref}
          hostLabel={visibleUrl}
        />
      </CareerThemeScope>
    );
  }

  const Layout = LAYOUTS[theme];
  return (
    <CareerThemeScope theme={theme}>
      <CareerSubmitGate
        thanks={{
          variant: "job",
          recruiterFirstName: recruiter.first_name,
          jobTitle: job.title,
          homeHref,
          rodoHref,
          hostLabel: visibleUrl,
          recruiterPageHref: recruiterHref,
        }}
      >
        <Layout data={data} base={base} host={host} formPreview={formPreview} />
      </CareerSubmitGate>
    </CareerThemeScope>
  );
}
