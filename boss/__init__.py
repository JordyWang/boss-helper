"""Boss直聘推荐列表批量沟通自动化框架。"""

__version__ = "0.2.0"

from .domain import Job, JobPreview, Message, RunSummary
from .artifacts import RunArtifacts, RunInProgressError
from .message_identity import (
    deduplicate_messages,
    message_fingerprint,
    message_id_value,
    message_identity,
    message_timestamp_value,
)

__all__ = [
    "Job",
    "JobPreview",
    "Message",
    "RunArtifacts",
    "RunInProgressError",
    "RunSummary",
    "deduplicate_messages",
    "message_fingerprint",
    "message_id_value",
    "message_identity",
    "message_timestamp_value",
    "__version__",
]
