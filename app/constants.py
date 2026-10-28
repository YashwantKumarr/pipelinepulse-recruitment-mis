"""Business vocabulary shared by services, schemas and routers."""

PIPELINE_ORDER = (
    "New",
    "Parsed",
    "Assessment Pending",
    "Assessed",
    "Shortlisted",
    "Submitted to Client",
    "Interview",
    "Offer",
    "Joined",
)
SIDE_STAGES = ("On Hold", "Rejected", "Withdrawn")
ALL_STAGES = PIPELINE_ORDER + SIDE_STAGES
TERMINAL_STAGES = frozenset({"Joined", "Rejected", "Withdrawn"})
SUBMITTED_STAGE = "Submitted to Client"
PARSED_STATUSES = frozenset({"parsed", "manually_corrected"})

INTERVIEW_STAGES = ("Screening", "Technical", "Client", "HR", "Final")
INTERVIEW_STATUSES = ("scheduled", "completed", "cancelled", "no_show")
JOB_STATUSES = ("open", "archived")
PAYMENT_STATUSES = ("pending", "recorded", "failed", "cancelled")
REVIEW_STATUSES = ("pending_review", "accepted", "overridden")
WEBHOOK_EVENT_TYPES = (
    "candidate.created",
    "candidate.stage_changed",
    "assessment.requested",
    "feedback.overdue",
)
