import { describe, expect, it } from "vitest";

import type { CvTopicResponse, DlSendQueueResponse } from "@/lib/api/boardTasks";
import { pipelineCvRefresh } from "@/lib/pipeline-changed-refresh";

const recruiter = { id: 5, role: "recruiter" as const, roles: ["recruiter" as const] };
const dl = { id: 8, role: "delivery_lead" as const, roles: ["delivery_lead" as const] };

function cv(jobIds: { recruiter?: number[]; dl?: number[] }): CvTopicResponse {
  const rows = (ids: number[] = []) => ids.map((job_id) => ({ job_id })) as never[];
  return {
    badge: 0,
    recruiter: { to_check: [], to_fix: [], with_dl: rows(jobIds.recruiter), sent: [] },
    dl: jobIds.dl
      ? { to_send: rows(jobIds.dl), to_send_total: 0, worst_urgency: null, with_recruiters_total: 0, sent_today: [] }
      : null,
  };
}

const dlSend = (ids: number[]): DlSendQueueResponse =>
  ({ ready: ids.map((job_id) => ({ job_id })), ready_total: ids.length }) as never;

describe("pipelineCvRefresh — które kolejki „CV” odświeżyć po ruchu karty", () => {
  it("bez konta w pamięci odświeża obie, jak przed 27.10.2026", () => {
    expect(pipelineCvRefresh(1, new Set([8]), null, undefined, undefined)).toEqual({
      cv: true,
      dlSend: true,
    });
  });

  it("rekruter: „CV” tylko, gdy ma wiersz tej rekrutacji; `dl-send` nigdy", () => {
    expect(pipelineCvRefresh(1, new Set([8]), recruiter, cv({ recruiter: [2] }), undefined)).toEqual({
      cv: false,
      dlSend: false,
    });
    expect(pipelineCvRefresh(2, new Set([8]), recruiter, cv({ recruiter: [2] }), undefined)).toEqual({
      cv: true,
      dlSend: false,
    });
  });

  it("Delivery Lead tej rekrutacji: obie, także bez wierszy w pamięci", () => {
    expect(pipelineCvRefresh(1, new Set([8]), dl, undefined, undefined)).toEqual({
      cv: true,
      dlSend: true,
    });
  });

  it("Delivery Lead innej rekrutacji: tylko kolejki, w których ma już jej wiersz", () => {
    expect(pipelineCvRefresh(1, new Set([9]), dl, cv({ dl: [] }), dlSend([]))).toEqual({
      cv: false,
      dlSend: false,
    });
    expect(pipelineCvRefresh(1, new Set([9]), dl, cv({ dl: [1] }), dlSend([1]))).toEqual({
      cv: true,
      dlSend: true,
    });
    // Rekrutacja bez Delivery Leada (`null`) też nie jest „jego”.
    expect(pipelineCvRefresh(1, new Set([null]), dl, undefined, undefined)).toEqual({
      cv: false,
      dlSend: false,
    });
  });

  it("ramka bez pola (backend sprzed zmiany) = każdy Delivery Lead, jak dawniej", () => {
    expect(pipelineCvRefresh(1, new Set([undefined]), dl, undefined, undefined)).toEqual({
      cv: true,
      dlSend: true,
    });
    // Sklejone ramki: wystarczy jedna z nim jako Delivery Leadem.
    expect(pipelineCvRefresh(1, new Set([9, 8]), dl, undefined, undefined).dlSend).toBe(true);
  });
});
