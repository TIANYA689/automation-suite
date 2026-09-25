"""Built-in approved challenge providers."""

from .base import ChallengeProvider
from .manual import ManualChallengeProvider

__all__ = ["ChallengeProvider", "ManualChallengeProvider"]

