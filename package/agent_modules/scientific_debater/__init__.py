"""Scientific debater: simulate dev Q&A → draft auxiliary metrics scripts (not in 星海舰队 delivery path)."""

from .debate_runner import run_debate_session
from .schema import DebateSession

__all__ = ["run_debate_session", "DebateSession"]