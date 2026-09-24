from app.models.user import User
from app.models.section_permission import (  # noqa: F401
    RbacPermissionAudit,
    RbacPolicyState,
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
    UserSectionOverride,
)
from app.models.candidate import Candidate
from app.models.candidate_language import CandidateLanguage  # noqa: F401
from app.models.candidate_source_identity_review import (  # noqa: F401
    CandidateSourceIdentityReview,
)
from app.models.skill import Skill  # noqa: F401
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.competence_category import (
    CandidateCcCategorySource,
    CandidateCompetenceCategory,
    CompetenceCategory,
    UserCompetenceCategory,
)
from app.models.cc_feedback import CcSuggestionOverride, JobSecondaryCc
from app.models.invite_link import CandidateInviteLink
from app.models.application_submission import (  # noqa: F401
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.client import Client
from app.models.client_directory import (
    ClientAlias,
    ClientImportRow,
    ClientImportRowStatus,
    ClientImportRun,
    ClientImportRunStatus,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.candidate_risk import (
    CandidateOfferResponse,
    CandidateRiskProfile,
    RiskLevel,
)
from app.models.candidate_pin import CandidatePin
from app.models.recruitment_pipeline import CandidateStage
from app.models.note import Note
from app.models.contract import Contract, ContractTerminationReason
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_equipment import (
    ContractEquipment,
    EquipmentItemType,
    EquipmentOwner,
    EquipmentReturnStatus,
)
from app.models.rate_benchmark import RateBenchmark, SeniorityLevel
from app.models.rate_card import RateCard
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.contract_framework_rate import ContractFrameworkRate
from app.models.contract_alert_dedup import ContractAlertDedup  # noqa: F401
from app.models.contract_onboarding import (
    ContractOnboardingItem,
    OnboardingItemStatus,
)
from app.models.contract_template import ContractTemplate
from app.models.b2b_contract_role import B2BContractRole, B2BRoleCategory
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_contract_document import B2BContractDocument
from app.models.b2b_register_import import B2BRegisterImportRow, B2BRegisterImportRun
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.cv_generation_job import CvGenerationJob  # noqa: F401
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.invoice import Invoice, InvoiceDirection, InvoiceStatus
from app.models.fx_rate import FxRate
from app.models.activity import Activity
from app.models.user_activity import UserActivity
from app.models.email_template import EmailTemplate
from app.models.user_email_template import UserEmailTemplate
from app.models.teams_channel import TeamsNotificationChannel
from app.models.job_posting import JobPosting
from app.models.call import Call
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactEvent,
    CandidateContactEventType,
    CandidateContactOpportunity,
    CandidateContactOpportunityOutcome,
    CandidateContactOpportunitySource,
    CandidateContactOutcome,
    CandidateContactState,
    CandidateContactTraffitCursor,
    CandidateContactTraffitLedger,
)
from app.models.traffit_sync_state import TraffitSyncState
from app.models.integration_external_item import IntegrationExternalItem
from app.models.integration_run import (
    IntegrationAlertState,
    IntegrationRun,
    IntegrationRunEvent,
)
from app.models.traffit_integration import (
    IntegrationLease,
    TraffitEntityLink,
    TraffitFieldContract,
    TraffitIntegrationControl,
    TraffitOutboxEvent,
    TraffitSyncConflict,
    TraffitSyncRun,
    TraffitSyncRunPhase,
    TraffitWebhookEvent,
)
from app.models.client_knowledge import ClientKnowledge
from app.models.client_one_pager import ClientOnePager
from app.models.client_contract_terms import ClientContractTerms
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.client_cv_rule_publication import ClientCvRulePublication
from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.models.client_cleanup import ClientCleanupRun, PurgedClient
from app.models.critical_event import CriticalEvent
from app.models.order_change_check import OrderChangeCheck, OrderPdfDownload
from app.models.application_confirmation_send import ApplicationConfirmationSend
from app.models.order_change_event import OrderChangeEvent
from app.models.order_gap import OrderGap
from app.models.insights_scoring_config import InsightsScoringConfig
from app.models.user_workday_period import UserWorkdayPeriod
from app.models.compass_workdays_sync_state import CompassWorkdaysSyncState
from app.models.insights_seniority_snapshot import (  # noqa: F401
    InsightsSenioritySnapshot,
)
from app.models.user_performance_flag import (  # noqa: F401
    PerformanceFlagType,
    UserPerformanceFlag,
)
from app.models.recruitment_campaign import RecruitmentCampaign
from app.models.screening_note import ScreeningNote
from app.models.contact import Contact, RelationshipStrength
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.models.marketplace_alert_log import MarketplaceAlertLog
from app.models.calendar_event import CalendarEvent
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.email_verification_token import EmailVerificationToken
from app.models.rate_history import RateHistory, ContractType
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.embedding_cache import EmbeddingCache  # noqa: F401
from app.models.pipeline_template import (
    PipelineTemplate,
    PipelineStageDef,
    RejectionReason,
    StageCategoryEnum,
    TerminalType,
)
from app.models.saved_search import SavedSearch, MatchHistory
from app.models.saved_search_alert_log import SavedSearchAlertLog  # noqa: F401
from app.models.procedure import Procedure
from app.models.help_material import HelpMaterial
from app.models.proposal_snapshot import ProposalSnapshot
from app.models.champion_suggestion import (
    ChampionProfileSuggestion,
    SuggestionSource,
    SuggestionStatus,
)
from app.models.app_setting import AppSetting
from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
from app.models.kpi_target_event import KpiTargetEvent
from app.models.kpi_email_report_run import KpiEmailReportRun
from app.models.kpi_nudge_log import KpiNudgeLog, KpiNudgeType, KpiNudgeChannel
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
    TacDeliveryLeadAssignment,
    TacLinkedInFarming,
)
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.linkedin_metric import LinkedInDailyMetric
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionRating,
    InterviewQuestionSeniority,
    InterviewQuestionSource,
    InterviewQuestionType,
    JobQuestion,
    JobQuestionAddedBySource,
    QuestionRatingValue,
)
from app.models.interview_feedback import (
    FeedbackSource,
    InterestLevel,
    InterviewDecision,
    InterviewFeedback,
    NextStepPreference,
)
from app.models.m365 import (
    Email,
    EmailAttachment,
    EmailDirection,
    EmailMatchMethod,
    GraphSubscription,
    M365Connection,
    M365SyncStatus,
)
from app.models.linkedin_snapshot import (
    CandidateLinkedinSnapshot,
    LinkedinChangeKind,
    LinkedinSyncStatus,
)
from app.models.rejection_email import (
    RejectionEmailStatus,
    ScheduledRejectionEmail,
)
from app.models.job_chat import JobChatMessage, JobChatMention, JobChatReadState
from app.models.candidate_chat import (
    CandidateChatMessage,
    CandidateChatMention,
    CandidateChatReadState,
)
from app.models.chat_reaction import (
    JobChatMessageReaction,
    CandidateChatMessageReaction,
)
from app.models.engagement_token import EngagementDeclarationToken
from app.models.note_mention import NoteMention
from app.models.screening_note_mention import ScreeningNoteMention
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.candidate_document import CandidateDocument
from app.models.cv_share_token import CVShareToken
from app.models.cv_generated_share import CvGeneratedShareToken, CvShareChatMessage
from app.models.recruitment_priority import (  # noqa: F401
    PriorityAlertSeverity,
    PriorityBlockerCategory,
    PriorityBlockerStatus,
    PriorityChannel,
    PriorityDemandStatus,
    PriorityExceptionStatus,
    PriorityMemberStatus,
    PriorityMode,
    PriorityOriginKind,
    PriorityPlanStatus,
    PriorityRank,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityAlert,
    RecruitmentPriorityAuditEvent,
    RecruitmentPriorityBlocker,
    RecruitmentPriorityDemand,
    RecruitmentPriorityException,
    RecruitmentPriorityPlan,
    RecruitmentPriorityPlanMember,
    RecruitmentPriorityState,
    RecruitmentPriorityUserMode,
)
from app.models.recruitment_process import (  # noqa: F401
    ProcessStatus,
    RecruitmentProcess,
)
from app.models.workflow_revision import (  # noqa: F401
    StageRevision,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowRevision,
)
from app.models.required_document_template import RequiredDocumentTemplate
from app.models.client_required_document import (
    ClientDocStatus,
    ClientRequiredDocument,
)
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.document_signature_event import DocumentSignatureEvent
from app.models.signature_link import SignatureLink
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_executive_contract import ClientExecutiveContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_offboarding import ClientOrderOffboardingCase
from app.models.contract_termination_snapshot import ContractTerminationSnapshot
from app.models.client_order_group import (
    ClientOrderGroup,
    ClientOrderGroupEvent,
    ClientOrderGroupMdConsumption,
)
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    ClientOrderMdConsumption,
    MdConsumptionImport,
    MdConsumptionImportRow,
)
from app.models.dl_alert import DlAlert
from app.models.order_mail import (
    OrderMailDocument,
    OrderMailRecheckRun,
    OrderMailSyncState,
)
from app.models.finance import (
    FinanceImportRun,
    FinanceImportRunStatus,
    FinanceMonthlyResult,
)
from app.models.ai_feature import (
    AIFeatureConfig,
    AIFeatureKey,
    AIMasterToggle,
    AIUsageLog,
)
from app.models.oauth_client import OAuthClient, OAuthScope
from app.models.service_account import (  # noqa: F401
    ServiceAccount,
    ServiceAccountKey,
    ServiceScope,
)
from app.models.candidate_source_event import (
    CandidateSourceEvent,
    SourceChannel,
)
from app.models.dictionary import Dictionary, DictionaryItem
from app.models.entity_field import EntityFieldDef, EntityType, FieldType
from app.models.match_justification import CandidateMatchJustification
from app.models.candidate_activity_summary import CandidateActivitySummary
from app.models.match_telemetry import MatchImpression, MatchOutcome  # noqa: F401
from app.models.index_outbox import IndexOutboxEvent  # noqa: F401

__all__ = [
    "IntegrationAlertState",
    "IntegrationExternalItem",
    "IntegrationRun",
    "IntegrationRunEvent",
    "CandidateMatchJustification",
    "CandidateActivitySummary",
    "MatchImpression",
    "MatchOutcome",
    "IndexOutboxEvent",
    "User",
    "Candidate",
    "Job",
    "JobCollaborator",
    "JobCollaboratorSource",
    "CompetenceCategory",
    "UserCompetenceCategory",
    "CandidateCompetenceCategory",
    "CandidateCcCategorySource",
    "CcSuggestionOverride",
    "JobSecondaryCc",
    "CandidateInviteLink",
    "ApplicationSubmission",
    "ApplicationSubmissionStatus",
    "Client",
    "ClientAlias",
    "ClientImportRow",
    "ClientImportRowStatus",
    "ClientImportRun",
    "ClientImportRunStatus",
    "ClientPortfolioScope",
    "PortfolioCategory",
    "CandidateStage",
    "Note",
    "Contract",
    "ContractTerminationReason",
    "ContractDocument",
    "ContractDocumentType",
    "ContractEquipment",
    "EquipmentItemType",
    "EquipmentOwner",
    "EquipmentReturnStatus",
    "RateBenchmark",
    "SeniorityLevel",
    "RateCard",
    "ContractAmendment",
    "ContractAmendmentType",
    "ContractCandidateRate",
    "ContractClientRate",
    "ContractFrameworkRate",
    "ContractOnboardingItem",
    "OnboardingItemStatus",
    "ContractTemplate",
    "B2BContractRole",
    "B2BRoleCategory",
    "B2BContractDetail",
    "B2BGeneratedContract",
    "B2BContractDocument",
    "B2BRegisterImportRow",
    "B2BRegisterImportRun",
    "B2BGeneratedContractStatusEvent",
    "CvGeneratedDocument",
    "Invoice",
    "InvoiceDirection",
    "InvoiceStatus",
    "FxRate",
    "Activity",
    "UserActivity",
    "EmailTemplate",
    "UserEmailTemplate",
    "TeamsNotificationChannel",
    "JobPosting",
    "Call",
    "CandidateContactCase",
    "CandidateContactEvent",
    "CandidateContactEventType",
    "CandidateContactOpportunity",
    "CandidateContactOpportunityOutcome",
    "CandidateContactOpportunitySource",
    "CandidateContactOutcome",
    "CandidateContactState",
    "CandidateContactTraffitCursor",
    "CandidateContactTraffitLedger",
    "TraffitSyncState",
    "TraffitEntityLink",
    "TraffitFieldContract",
    "TraffitOutboxEvent",
    "TraffitWebhookEvent",
    "TraffitSyncConflict",
    "TraffitSyncRun",
    "TraffitSyncRunPhase",
    "IntegrationLease",
    "TraffitIntegrationControl",
    "ClientKnowledge",
    "ClientOnePager",
    "ClientContractTerms",
    "ClientCvRule",
    "ClientCvRuleEvent",
    "ClientCvRulePublication",
    "ClientCvRulePreview",
    "ClientPlaybook",
    "ClientPlaybookEvent",
    "ClientCleanupRun",
    "PurgedClient",
    "CriticalEvent",
    "OrderChangeCheck",
    "OrderChangeEvent",
    "OrderPdfDownload",
    "ApplicationConfirmationSend",
    "OrderGap",
    "InsightsScoringConfig",
    "UserWorkdayPeriod",
    "CompassWorkdaysSyncState",
    "InsightsSenioritySnapshot",
    "UserPerformanceFlag",
    "PerformanceFlagType",
    "RecruitmentCampaign",
    "ScreeningNote",
    "Contact",
    "RelationshipStrength",
    "TalentPool",
    "TalentPoolMembership",
    "MarketplaceAlertLog",
    "ContractAlertDedup",
    "CalendarEvent",
    "Notification",
    "PasswordResetToken",
    "EmailVerificationToken",
    "RateHistory",
    "ContractType",
    "CandidateConflict",
    "ConflictType",
    "PipelineTemplate",
    "PipelineStageDef",
    "RejectionReason",
    "StageCategoryEnum",
    "TerminalType",
    "SavedSearch",
    "MatchHistory",
    "SavedSearchAlertLog",
    "Procedure",
    "HelpMaterial",
    "ProposalSnapshot",
    "ChampionProfileSuggestion",
    "SuggestionSource",
    "SuggestionStatus",
    "AppSetting",
    "KpiRoleDefault",
    "UserKpiTarget",
    "KpiTargetEvent",
    "KpiEmailReportRun",
    "KpiNudgeLog",
    "KpiNudgeType",
    "KpiNudgeChannel",
    "TacDeliveryLeadAssignment",
    "TacLinkedInFarming",
    "DeliveryLeadClientAssignment",
    "ClientTacAssignment",
    "CompetitionType",
    "CompetitionWinner",
    "LinkedInDailyMetric",
    "InterviewQuestion",
    "InterviewQuestionRating",
    "InterviewQuestionSeniority",
    "InterviewQuestionSource",
    "InterviewQuestionType",
    "JobQuestion",
    "JobQuestionAddedBySource",
    "QuestionRatingValue",
    "InterviewFeedback",
    "FeedbackSource",
    "InterestLevel",
    "NextStepPreference",
    "InterviewDecision",
    "RejectionEmailStatus",
    "ScheduledRejectionEmail",
    "Email",
    "EmailAttachment",
    "EmailDirection",
    "EmailMatchMethod",
    "GraphSubscription",
    "M365Connection",
    "M365SyncStatus",
    "CandidateLinkedinSnapshot",
    "LinkedinChangeKind",
    "LinkedinSyncStatus",
    "JobChatMessage",
    "JobChatMention",
    "JobChatReadState",
    "CandidateChatMessage",
    "CandidateChatMention",
    "CandidateChatReadState",
    "JobChatMessageReaction",
    "CandidateChatMessageReaction",
    "EngagementDeclarationToken",
    "CandidateRiskProfile",
    "CandidatePin",
    "RiskLevel",
    "CandidateOfferResponse",
    "NoteMention",
    "ScreeningNoteMention",
    "CandidateStageCV",
    "CandidateStageRemoval",
    "CandidateDocument",
    "CVShareToken",
    "CvGeneratedShareToken",
    "CvShareChatMessage",
    "PriorityBlockerCategory",
    "PriorityAlertSeverity",
    "PriorityBlockerStatus",
    "PriorityChannel",
    "PriorityDemandStatus",
    "PriorityExceptionStatus",
    "PriorityMemberStatus",
    "PriorityMode",
    "PriorityOriginKind",
    "PriorityPlanStatus",
    "PriorityRank",
    "RecruitmentPriorityAssignment",
    "RecruitmentPriorityAlert",
    "RecruitmentPriorityAuditEvent",
    "RecruitmentPriorityBlocker",
    "RecruitmentPriorityDemand",
    "RecruitmentPriorityException",
    "RecruitmentPriorityPlan",
    "RecruitmentPriorityPlanMember",
    "RecruitmentPriorityState",
    "RecruitmentPriorityUserMode",
    "RequiredDocumentTemplate",
    "ClientRequiredDocument",
    "ClientDocStatus",
    "DocumentSignature",
    "DocumentSignatureEvent",
    "SignatureLink",
    "SignatureStatus",
    "ClientFrameworkContract",
    "FrameworkContractStatus",
    "FrameworkContractSignedVia",
    "ClientContractAmendment",
    "ClientExecutiveContract",
    "ClientOrder",
    "ClientOrderOffboardingCase",
    "ContractTerminationSnapshot",
    "ClientOrderGroup",
    "ClientOrderGroupEvent",
    "ClientOrderGroupMdConsumption",
    "ClientOrderInvoiceConsumption",
    "ClientOrderMdConsumption",
    "DlAlert",
    "OrderMailDocument",
    "OrderMailRecheckRun",
    "OrderMailSyncState",
    "ClientOrderStatus",
    "MdConsumptionImport",
    "MdConsumptionImportRow",
    "FinanceImportRun",
    "FinanceImportRunStatus",
    "FinanceMonthlyResult",
    "AIFeatureConfig",
    "AIFeatureKey",
    "AIMasterToggle",
    "AIUsageLog",
    "OAuthClient",
    "OAuthScope",
    "CandidateSourceEvent",
    "SourceChannel",
    "Dictionary",
    "DictionaryItem",
    "EntityFieldDef",
    "EntityType",
    "FieldType",
    # DynaReporter migration (B.2 — modele dr_* tabel)
    "DrKpiBodyLeasing",
    "DrKpiSales",
    "DrKpiDeliveryLead",
    "DrPlacementDetail",
    "DrClient",
    "DrClientMrr",
    "DrFinance",
    "DrCompetitionNotification",
    "DrCompetitionWinner",
    "DrPrzetargiAllocation",
    "DrPrzetargiConsultant",
    "DrPrzetargiProject",
    "DrPrzetargiProjectCost",
    "DrBoardMonthlyReport",
    "DrBoardPlacementClient",
    "DrSalesLead",
    "DrSalesOffer",
    "DrSalesPerson",
    "DrSalesProject",
    "DrWeeklySalesActivity",
    "DrUploadHistory",
    "DrUserSeniority",
]

# DynaReporter migration (B.2 — modele dr_* tabel)
from app.models.dr_kpi_body_leasing import DrKpiBodyLeasing  # noqa: F401
from app.models.dr_kpi_sales import DrKpiSales  # noqa: F401
from app.models.dr_kpi_delivery_lead import DrKpiDeliveryLead  # noqa: F401
from app.models.dr_placement_details import DrPlacementDetail  # noqa: F401
from app.models.dr_clients_mrr import DrClient, DrClientMrr, DrFinance  # noqa: F401
from app.models.dr_competition import DrCompetitionNotification, DrCompetitionWinner  # noqa: F401
from app.models.dr_przetargi import (
    DrPrzetargiAllocation,
    DrPrzetargiConsultant,
    DrPrzetargiProject,
    DrPrzetargiProjectCost,
)  # noqa: F401
from app.models.dr_board import DrBoardMonthlyReport, DrBoardPlacementClient  # noqa: F401
from app.models.dr_sales import (
    DrSalesLead,
    DrSalesOffer,
    DrSalesPerson,
    DrSalesProject,
    DrWeeklySalesActivity,
)  # noqa: F401
from app.models.dr_upload import DrUploadHistory  # noqa: F401
from app.models.dr_user_seniority import DrUserSeniority  # noqa: F401
from app.models.cortex import (  # noqa: F401
    CortexExtractionRun,
    CortexSkillFact,
    CortexUnmatchedObservation,
    CortexUnmatchedTerm,
)

from app.models.job_shortlist import JobShortlistEntry  # noqa: F401
from app.models.financial_adjustment import FinancialAdjustment  # noqa: F401,E501
from app.models.analytics_snapshot import (  # noqa: F401
    AnalyticsCutover,
    AnalyticsMetricSnapshot,
)

from app.models.recruitment_allocation import (  # noqa: F401
    WorkforceAvailabilityState,
    RecruitmentAllocationState,
    RecruitmentAllocationRequest,
    RecruitmentAllocationEvent,
)

from app.models.ai_metering import AIOperation, AIProviderCall, AIGenerationLease  # noqa: F401
from app.models.ai_metering import AISpendAlert  # noqa: F401

from app.models.cv_document_version import CvDocumentVersion  # noqa: F401
from app.models.candidate_search_run import CandidateSearchRun, CandidateSearchResult  # noqa: F401
from app.models.requirement_verification import RequirementVerification  # noqa: F401

from app.models.cv_generated_draft import CvGeneratedDraft  # noqa: F401

from app.models.cv_generation_request import CvGenerationRequest  # noqa: F401
from app.models.cv_approval_job import CvApprovalJob  # noqa: F401

from app.models.cv_source_cleanup import CvSourceCleanup  # noqa: F401

from app.models.cv_version_map import CvVersionMap  # noqa: F401

from app.models.candidate_skill_usage import CandidateSkillUsage  # noqa: F401
from app.models.candidate_auto_match import (  # noqa: F401
    CandidateAutoMatchLog,
    CandidateMatchOutbox,
)
from app.models.jarvis import (  # noqa: F401
    JarvisAction,
    JarvisConversation,
    JarvisConversationEntity,
    JarvisMessage,
    JarvisUiEvent,
)
from app.models.mail_delivery import MailDeliveryState  # noqa: F401
from app.models.job_proposal import JobProposal  # noqa: F401
from app.models.job_similar_link import JobSimilarLink  # noqa: F401
from app.models.my_people import MyPeopleJobMatch, MyPeopleOverride  # noqa: F401

# 0369: Akademia — nabór do programów szkoleniowych.
from app.models.academy import (  # noqa: F401
    AcademyApplication,
    AcademyProgram,
    AcademyProgramSource,
    AcademySession,
)
from app.models.user_dashboard import UserDashboard  # noqa: F401
from app.models.client_interview_slot_request import (  # noqa: F401
    ClientInterviewSlotRequest,
)
from app.models.job_public_profile import JobPublicProfile  # noqa: F401
from app.models.candidate_consent import CandidateConsent  # noqa: F401

# 0343: wykluczone placementy (seria „Zatrudniony" bez CV) — czyta je widok
# analytics_first_milestones i VERIFIER_ANCHORED_CTE.
from app.models.placement_exclusion import PlacementExclusion  # noqa: F401
from app.models.dz_review_hint import DzReviewHint  # noqa: F401

# 0372: praktykant — program wdrożenia i codzienna lista telefonów.
from app.models.trainee import (  # noqa: F401
    TraineeCallItem,
    TraineeCallList,
    TraineeProgram,
)

# 0370: prepy w Teams — spotkanie, transkrypt i ocena prepu.
from app.models.prep_meeting import (  # noqa: F401
    PrepMeeting,
    PrepReview,
    PrepTranscript,
)

# 0372: follow-up z kandydatem, gdy klient milczy — wyniki telefonów.
from app.models.candidate_followup import CandidateFollowup  # noqa: F401

# 0361: przebiegi QC CV (Rekrutacja v5) — bramka przed „CV wysłane”/Cpro.
from app.models.cv_qc_run import CvQcRun  # noqa: F401
from app.models.competition_period_closure import (  # noqa: F401
    CompetitionPeriodClosure,
)

# 0371: kto pracuje nad requestem (automat przydziału + ręczne dodanie).
from app.models.job_work_assignment import JobWorkAssignment  # noqa: F401
