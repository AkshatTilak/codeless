"""Task exports."""

from codeless.jobs.local_agent_task import spawn_local_agent_task
from codeless.jobs.local_shell_task import spawn_shell_task
from codeless.jobs.manager import BackgroundTaskManager, get_task_manager
from codeless.jobs.stop_task import stop_task
from codeless.jobs.types import TaskRecord, TaskStatus, TaskType

__all__ = [
    "BackgroundTaskManager",
    "TaskRecord",
    "TaskStatus",
    "TaskType",
    "get_task_manager",
    "spawn_local_agent_task",
    "spawn_shell_task",
    "stop_task",
]
