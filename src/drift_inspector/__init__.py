"""__init__ for drift_inspector package."""

from drift_inspector.config import Settings as Settings
from drift_inspector.config import get_settings as get_settings

__all__ = ["Settings", "get_settings", "__version__"]

__version__ = "0.1.0"