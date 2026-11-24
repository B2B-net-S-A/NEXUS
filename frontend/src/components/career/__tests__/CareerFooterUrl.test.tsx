import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RecruiterPage } from "@/components/career/site/RecruiterPage";
import type { CareerRecruiterResponse } from "@/lib/career/api";

const RECRUITER: CareerRecruiterResponse = {
  recruiter: { first_name: "Marta", slug: "marta-n" },
  jobs: [],
};

const footerText = (container: HTMLElement) =>
  container.querySelector("footer")?.textContent ?? "";

describe("stopka strony kariery — adres z hosta żądania", () => {
  it("host aplikacji: stały link rekrutera pod /kariera/p/<slug>", () => {
    const { container } = render(
      <RecruiterPage data={RECRUITER} board={null} base="/kariera" host="nexus.dynaminds.pl" />,
    );
    expect(footerText(container)).toContain("nexus.dynaminds.pl/kariera/p/marta-n");
    expect(footerText(container)).not.toContain("kariera.dynaminds.pl");
  });

  it("host kariery: stały link rekrutera bez prefiksu", () => {
    const { container } = render(
      <RecruiterPage data={RECRUITER} board={null} base="" host="kariera.dynaminds.pl" />,
    );
    expect(footerText(container)).toContain("kariera.dynaminds.pl/marta-n");
    expect(footerText(container)).not.toContain("/kariera/p/");
  });
});
