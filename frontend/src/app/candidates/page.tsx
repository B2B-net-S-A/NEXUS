import { Suspense } from "react";
import { cookies } from "next/headers";
import { readUiFlagFromCookies } from "@/lib/ui-flag";
import { CandidatesPageV1 } from "@/components/v1/CandidatesPageV1";
import { CandidatesListV2 } from "@/components/v2/pages/CandidatesListV2";

export default async function CandidatesPage() {
  const cookieStore = await cookies();
  const ui = readUiFlagFromCookies(cookieStore);
  if (ui === "v2") {
    return (
      <Suspense>
        <CandidatesListV2 />
      </Suspense>
    );
  }
  return <CandidatesPageV1 />;
}
