"""Camera and plate-solving backends for B1-AutoAlign."""

from .manager import AutomationManager
from .models import AutomationReport, CameraDevice, PlateSolution

__all__ = ["AutomationManager", "AutomationReport", "CameraDevice", "PlateSolution"]
