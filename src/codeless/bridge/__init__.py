"""Bridge exports."""

from codeless.bridge.manager import BridgeSessionManager, BridgeSessionRecord, get_bridge_manager
from codeless.bridge.session_runner import SessionHandle, spawn_session
from codeless.bridge.types import BridgeConfig, WorkData, WorkSecret
from codeless.bridge.work_secret import build_sdk_url, decode_work_secret, encode_work_secret

__all__ = [
    "BridgeSessionManager",
    "BridgeSessionRecord",
    "BridgeConfig",
    "SessionHandle",
    "WorkData",
    "WorkSecret",
    "build_sdk_url",
    "decode_work_secret",
    "encode_work_secret",
    "get_bridge_manager",
    "spawn_session",
]
