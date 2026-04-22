"""merge all 0028 branches + onboarding head into a single head

Revision ID: 0034_merge_phase8_heads
Revises: 0032_app_settings, 0031_champion_profile_notification_type, 0031_champion_profile_suggestions, 0029_procedures, 0029_proposal_snapshots, wyroznienia_availability, 0035_onboarding_and_job_sourcing
Create Date: 2026-04-22 08:35:00.000000

Parallel feature work from several agents branched from `0028` and produced
seven divergent heads. `0033_cc_entities -> 0034_kpi_coach -> 0035_onboarding`
then grew on top of one of those heads, so the graph had 8 leaves total.
This migration is a no-op whose only job is to rejoin the graph into a
single head. `0033_cc_entities` is omitted from the parent list because it
is a transitive ancestor through the onboarding chain.

Branches merged:
- 0029 -> 0030_candidate_created_by -> 0031_candidate_invite_links -> 0032_app_settings
- 0030_candidate_created_by -> 0031_champion_profile_notification_type
- notif_triggers_13 -> 0031_champion_profile_suggestions
- notif_triggers_13 -> 0033_cc_entities -> 0034_kpi_coach -> 0035_onboarding_and_job_sourcing
- 0029_procedures
- 0029_proposal_snapshots
- wyroznienia_availability
"""

revision = "0034_merge_phase8_heads"
down_revision = (
    "0032_app_settings",
    "0031_champion_profile_notification_type",
    "0031_champion_profile_suggestions",
    "0029_procedures",
    "0029_proposal_snapshots",
    "wyroznienia_availability",
    "0035_onboarding_and_job_sourcing",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
