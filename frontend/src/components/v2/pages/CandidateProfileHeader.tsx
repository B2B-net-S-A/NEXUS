import * as React from "react";

import { EntityHeader, type EntityHeaderProps } from "@/components/ds/EntityHeader";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { getCandidateInitials } from "@/components/v2/pages/candidate-list-helpers";

export interface CandidateProfileHeaderCandidate {
  name?: string | null;
  lastname?: string | null;
}

export interface CandidateProfileHeaderProps
  extends Omit<EntityHeaderProps, "avatar" | "title" | "subtitle"> {
  candidate: CandidateProfileHeaderCandidate;
  summary?: React.ReactNode;
  title?: React.ReactNode;
  avatar?: React.ReactNode;
}

/** Domain wrapper that keeps identity hierarchy identical in drawer/page UI. */
export function CandidateProfileHeader({
  candidate,
  summary,
  title,
  avatar,
  ...props
}: CandidateProfileHeaderProps) {
  const fullName =
    `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim() ||
    "Kandydat";

  return (
    <EntityHeader
      {...props}
      avatar={
        avatar ?? (
          <Avatar size="xl">
            <AvatarFallback>{getCandidateInitials(candidate) || "?"}</AvatarFallback>
          </Avatar>
        )
      }
      title={title ?? fullName}
      subtitle={summary}
    />
  );
}
