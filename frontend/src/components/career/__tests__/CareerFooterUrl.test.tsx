import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CareerJobView } from "@/components/career/CareerJobView";
import { CareerRecruiterView } from "@/components/career/CareerRecruiterView";
import type { CareerJobResponse, CareerRecruiterResponse } from "@/lib/career/api";

const CLOSED_JOB: CareerJobResponse = {
  status: "closed",
  recruiter: { first_name: "Marta", slug: "marta-n" },
  job: {
    slug: "java-developer-ab12",
    title: "Java Developer",
    subtitle: null,
    about: null,
    must: [],
    nice: [],
    params: null,
    show: null,
  },
};

const RECRUITER: CareerRecruiterResponse = {
  recruiter: { first_name: "Marta", slug: "marta-n" },
  jobs: [],
};

const footerText = (container: HTMLElement) =>
  container.querySelector("footer")?.textContent ?? "";

describe("stopka strony kariery — adres z hosta żądania", () => {
  it("host aplikacji: stały link rekrutera pod /kariera/p/<slug>", () => {
    const { container } = render(
      <CareerRecruiterView data={RECRUITER} base="/kariera" host="nexus.dynaminds.pl" />,
    );
    expect(footerText(container)).toContain("nexus.dynaminds.pl/kariera/p/marta-n");
    expect(footerText(container)).not.toContain("kariera.dynaminds.pl");
  });

  it("host kariery: stały link rekrutera bez prefiksu", () => {
    const { container } = render(
      <CareerRecruiterView data={RECRUITER} base="" host="kariera.dynaminds.pl" />,
    );
    expect(footerText(container)).toContain("kariera.dynaminds.pl/marta-n");
    expect(footerText(container)).not.toContain("/kariera/p/");
  });

  it("link rekrutacji: pełny widoczny adres z /r/<slug>", () => {
    const app = render(<CareerJobView data={CLOSED_JOB} base="/kariera" host="nexus.dynaminds.pl" />);
    expect(footerText(app.container)).toContain("nexus.dynaminds.pl/kariera/r/java-developer-ab12");
    app.unmount();
    const career = render(<CareerJobView data={CLOSED_JOB} base="" host="kariera.dynaminds.pl" />);
    expect(footerText(career.container)).toContain("kariera.dynaminds.pl/r/java-developer-ab12");
  });
});
