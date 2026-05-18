from app.models.user import User
from app.models.candidate import Candidate
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
from app.models.client import Client
from app.models.candidate_risk import (
    CandidateOfferResponse,
    CandidateRiskProfile,
    RiskLevel,
)
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
from app.models.contract_onboarding import (
    ContractOnboardingItem,
    OnboardingItemStatus,
)
from app.models.contract_template import ContractTemplate
from app.models.invoice import Invoice, InvoiceDirection, InvoiceStatus
from app.models.fx_rate import FxRate
from app.models.activity import Activity
from app.models.user_activity import UserActivity
from app.models.email_template import EmailTemplate
from app.models.user_email_template import UserEmailTemplate
from app.models.teams_channel import TeamsNotificationChannel
from app.models.job_posting import JobPosting
from app.models.call import Call
from app.models.client_knowledge import ClientKnowledge
from app.models.client_one_pager import ClientOnePager
from app.models.client_contract_terms import ClientContractTerms
from app.models.screening_note import ScreeningNote
from app.models.contact import Contact, RelationshipStrength
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.models.marketplace_alert_log import MarketplaceAlertLog
from app.models.calendar_event import CalendarEvent
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
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
from app.models.procedure import Procedure
from app.models.proposal_snapshot import ProposalSnapshot
from app.models.champion_suggestion import (
    ChampionProfileSuggestion,
    SuggestionSource,
    SuggestionStatus,
)
from app.models.app_setting import AppSetting
from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
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
from app.models.candidate_document import CandidateDocument
from app.models.cv_share_token import CVShareToken
from app.models.required_document_template import RequiredDocumentTemplate
from app.models.client_required_document import (
    ClientDocStatus,
    ClientRequiredDocument,
)
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.document_signature_event import DocumentSignatureEvent
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.ai_feature import (
    AIFeatureConfig,
    AIFeatureKey,
    AIMasterToggle,
    AIUsageLog,
)
from app.models.oauth_client import OAuthClient, OAuthScope
from app.models.candidate_source_event import (
    CandidateSourceEvent,
    SourceChannel,
)
from app.models.dictionary import Dictionary, DictionaryItem
from app.models.entity_field import EntityFieldDef, EntityType, FieldType

__all__ = [
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
    "Client",
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
    "ContractOnboardingItem",
    "OnboardingItemStatus",
    "ContractTemplate",
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
    "ClientKnowledge",
    "ClientOnePager",
    "ClientContractTerms",
    "ScreeningNote",
    "Contact",
    "RelationshipStrength",
    "TalentPool",
    "TalentPoolMembership",
    "MarketplaceAlertLog",
    "CalendarEvent",
    "Notification",
    "PasswordResetToken",
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
    "Procedure",
    "ProposalSnapshot",
    "ChampionProfileSuggestion",
    "SuggestionSource",
    "SuggestionStatus",
    "AppSetting",
    "KpiRoleDefault",
    "UserKpiTarget",
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
    "RiskLevel",
    "CandidateOfferResponse",
    "NoteMention",
    "ScreeningNoteMention",
    "CandidateStageCV",
    "CandidateDocument",
    "CVShareToken",
    "RequiredDocumentTemplate",
    "ClientRequiredDocument",
    "ClientDocStatus",
    "DocumentSignature",
    "DocumentSignatureEvent",
    "SignatureStatus",
    "ClientFrameworkContract",
    "FrameworkContractStatus",
    "FrameworkContractSignedVia",
    "ClientContractAmendment",
    "ClientOrder",
    "ClientOrderStatus",
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
