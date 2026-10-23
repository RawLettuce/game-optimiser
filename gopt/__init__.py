"""game-optimiser: tune a Steam game's settings towards an fps goal on Linux.

Config files and Steam launch options only. Dry run by default.
"""

__version__ = "0.1.0"


class Refusal(Exception):
    """A safety refusal. Exit code 3. Nothing has been written when raised."""


class GoalNotMet(Exception):
    """The search finished without reaching the goal. Exit code 2."""
