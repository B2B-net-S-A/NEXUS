"use client";

import { Award, FolderKanban, History, Trophy } from "lucide-react";

import {
  formatExperienceDate,
  formatUsageMonths,
  type RichCvProfile,
} from "@/components/v2/pages/candidate-profile-helpers";

const SECTION_TITLE =
  "text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2 flex items-center gap-2";
const CARD = "rounded-lg bg-background/40 border border-border p-3";

function Chips({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {items.map((item) => (
        <span
          key={item}
          className="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[11px] text-foreground"
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function period(start: string | null, end: string | null): string {
  if (!start && !end) return "";
  const from = formatExperienceDate(start);
  const to = formatExperienceDate(end);
  if (from && to) return `${from} — ${to}`;
  return from || to;
}

/** Sekcje profilu z odczytu CV v7: certyfikaty, projekty, osiągnięcia, oś technologii.
 *
 *  Renderuje się wyłącznie dla profili ze schematem v7 (`getRichCvProfile`),
 *  a każda sekcja tylko wtedy, gdy CV coś w niej zawiera. */
export function CvRichProfileSections({ profile }: { profile: RichCvProfile }) {
  const { certifications, projects, achievements, timeline } = profile;
  return (
    <>
      {timeline.length > 0 && (
        <section data-testid="cv-skill-timeline">
          <h3 className={SECTION_TITLE}>
            <History className="h-3.5 w-3.5" />
            Technologie w czasie
          </h3>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Technologia</th>
                  <th className="px-3 py-2 font-medium">Okres</th>
                  <th className="px-3 py-2 font-medium">Łącznie</th>
                  <th className="px-3 py-2 font-medium">Gdzie</th>
                </tr>
              </thead>
              <tbody>
                {timeline.map((row) => (
                  <tr key={row.skill} className="border-t border-border align-top">
                    <td className="px-3 py-2 font-medium text-foreground">
                      {row.skill}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground tabular-nums">
                      {row.isCurrent
                        ? `${formatExperienceDate(row.firstUsed)} — obecnie`
                        : period(row.firstUsed, row.lastUsed)}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground tabular-nums">
                      {formatUsageMonths(row.months) || "—"}
                    </td>
                    <td className="min-w-[12rem] px-3 py-2 text-muted-foreground">
                      {row.contexts.join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Wyliczone z dat stanowisk i projektów w CV.
          </p>
        </section>
      )}

      {certifications.length > 0 && (
        <section data-testid="cv-certifications">
          <h3 className={SECTION_TITLE}>
            <Award className="h-3.5 w-3.5" />
            Certyfikaty
          </h3>
          <div className="space-y-2">
            {certifications.map((cert) => (
              <div key={cert.name} className={CARD}>
                <div className="text-sm font-medium text-foreground">{cert.name}</div>
                {(cert.issuer || cert.year || cert.expires) && (
                  <div className="text-xs text-muted-foreground">
                    {[
                      cert.issuer,
                      cert.year ? String(cert.year) : null,
                      cert.expires
                        ? `ważny do ${formatExperienceDate(cert.expires)}`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {projects.length > 0 && (
        <section data-testid="cv-projects">
          <h3 className={SECTION_TITLE}>
            <FolderKanban className="h-3.5 w-3.5" />
            Projekty
          </h3>
          <div className="space-y-2">
            {projects.map((project, i) => (
              <div key={`${project.name}-${i}`} className={CARD}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground">
                      {project.name}
                    </div>
                    {(project.role || project.company) && (
                      <div className="text-xs text-muted-foreground">
                        {[project.role, project.company].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </div>
                  {period(project.start, project.end) && (
                    <div className="whitespace-nowrap text-xs text-muted-foreground">
                      {period(project.start, project.end)}
                    </div>
                  )}
                </div>
                {project.description && (
                  <p className="mt-1 text-sm text-muted-foreground">
                    {project.description}
                  </p>
                )}
                <Chips items={project.technologies} />
              </div>
            ))}
          </div>
        </section>
      )}

      {achievements.length > 0 && (
        <section data-testid="cv-achievements">
          <h3 className={SECTION_TITLE}>
            <Trophy className="h-3.5 w-3.5" />
            Osiągnięcia
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-foreground">
            {achievements.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

export { Chips as CvTechnologyChips };
