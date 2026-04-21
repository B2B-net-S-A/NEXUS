import { cookies } from "next/headers";
import { readUiFlagFromCookies } from "@/lib/ui-flag";
import { CandidateDetailPageV1 } from "@/components/v1/CandidateDetailPageV1";
import { CandidateDetailV2 } from "@/components/v2/pages/CandidateDetailV2";

export default async function CandidateDetailPage() {
  const cookieStore = await cookies();
  const ui = readUiFlagFromCookies(cookieStore);
  return ui === "v2" ? <CandidateDetailV2 /> : <CandidateDetailPageV1 />;
}
