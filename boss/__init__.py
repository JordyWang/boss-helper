"""Boss直聘推荐列表批量沟通自动化框架。"""

__version__ = "0.2.0"

from .domain import Job, JobPreview, Message, RunSummary
from .artifacts import RunArtifacts, RunInProgressError

__all__ = [
    "Job",
    "JobPreview",
    "Message",
    "RunArtifacts",
    "RunInProgressError",
    "RunSummary",
    "__version__",
]
