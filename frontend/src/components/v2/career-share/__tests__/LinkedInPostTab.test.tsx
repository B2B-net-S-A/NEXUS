import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { LinkedInPostTab } from "@/components/v2/career-share/LinkedInPostTab";
import { inviteLinksQueryKey, jobPublicProfileQueryKey } from "@/lib/api/careerLinks";
import { copyTextToClipboard } from "@/lib/clipboard";
import { postDataQueryKey, type PostDataResponse } from "@/lib/career/postGraphic";

vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: vi.fn(async () => true) }));

const LINK = {
  token: "t1",
  url: "https://kariera.b2bnetwork.pl/r/senior-java-7kq2",
  public_url: "https://kariera.b2bnetwork.pl/r/senior-java-7kq2",
  kind: "job",
  slug: "senior-java-7kq2",
  job: { id: 101, title: "Senior Java Developer" },
  label: "Post LinkedIn 27.11",
  expires_at: null,
  revoked: false,
  use_count: 0,
  last_used_at: null,
  created_at: "2026-11-27T10:00:00Z",
  status: "active",
};

const PROFILE = {
  job_id: 101,
  status: "approved",
  live: { title: "Senior Java Developer", subtitle: null, about: null, sections: {}, pending_changes: false },
};

const DATA: PostDataResponse = {
  post: {
    tags: ["Java"],
    word: "Java",
    title: "Senior Java Developer",
    line: "Gdańsk · hybryda · B2B",
    sub: null,
    map: { kind: "none" },
    host: "kariera.b2bnetwork.pl",
    duties: ["Rozwój platformy płatności"],
    must: ["Java 17"],
    nice: [],
    skills: ["Java", "Spring Boot"],
    steps: [],
    subtitle: null,
    office: null,
  },
  text: "Nowa rekrutacja: Senior Java Developer\nGdańsk · hybryda · B2B",
  slides: ["cover", "duties", "must", "apply"],
};

function setup(seed: { profile?: unknown; links?: unknown[]; data?: PostDataResponse }) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  qc.setQueryData(jobPublicProfileQueryKey(101), seed.profile ?? null);
  qc.setQueryData(inviteLinksQueryKey(), seed.links ?? []);
  if (seed.data) qc.setQueryData(postDataQueryKey("senior-java-7kq2"), seed.data);
  const onGoToLink = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <LinkedInPostTab enabled jobId={101} onGoToLink={onGoToLink} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { onGoToLink };
}

describe("zakładka „Post na LinkedIn”", () => {
  it("bez zatwierdzonego opisu odsyła do opisu i nie pokazuje grafiki", async () => {
    const { onGoToLink } = setup({ profile: { ...PROFILE, live: null }, links: [LINK] });
    expect(screen.getByTestId("post-not-ready")).toHaveTextContent("Najpierw zatwierdź opis publiczny");
    await userEvent.click(screen.getByRole("button", { name: "Przejdź do opisu" }));
    expect(onGoToLink).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Pobierz/ })).toBeNull();
  });

  it("bez linku prosi o wygenerowanie linku (komentarz nie miałby adresu)", () => {
    setup({ profile: PROFILE, links: [] });
    expect(screen.getByTestId("post-not-ready")).toHaveTextContent("Wygeneruj go");
    expect(screen.getByRole("button", { name: "Wygeneruj link" })).toBeInTheDocument();
  });

  it("strona działa: grafika, treść posta i komentarz z linkiem do skopiowania", async () => {
    setup({ profile: PROFILE, links: [LINK], data: DATA });
    expect(screen.getByRole("img", { name: /Grafika do posta: Senior Java Developer/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Treść posta")).toHaveValue(DATA.text);
    expect(screen.getByTestId("post-comment")).toHaveTextContent(
      "Aplikuj tutaj: https://kariera.b2bnetwork.pl/r/senior-java-7kq2",
    );
    expect(screen.getByText(/Link „Post LinkedIn 27.11”/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Kopiuj komentarz" }));
    expect(copyTextToClipboard).toHaveBeenCalledWith("Aplikuj tutaj: https://kariera.b2bnetwork.pl/r/senior-java-7kq2");
  });

  it("wybór wyglądu: karuzela ma slajdy i pobiera PDF", async () => {
    setup({ profile: PROFILE, links: [LINK], data: DATA });
    expect(screen.getByRole("button", { name: "Mapa" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Pobierz grafikę (PNG)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Karuzela" }));
    expect(screen.getByText("Slajd 1 z 4")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Następny slajd" }));
    expect(screen.getByText("Slajd 2 z 4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz karuzelę (PDF)" })).toBeInTheDocument();
  });

  it("poprawiona treść wraca do szablonu jednym kliknięciem", async () => {
    setup({ profile: PROFILE, links: [LINK], data: DATA });
    const box = screen.getByLabelText("Treść posta");
    await userEvent.type(box, " dopisek");
    await userEvent.click(screen.getByRole("button", { name: "Przywróć szablon" }));
    expect(box).toHaveValue(DATA.text);
  });
});
