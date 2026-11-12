"""Application integrations: a common interface over installed Windows apps."""

from .base import Integration, integration_allowed
from .chrome import ChromeIntegration
from .discord import DiscordIntegration
from .registry import (
    all_integrations,
    get_integration,
    integration_status,
    register,
)
from .spotify import SpotifyIntegration
from .steam import SteamIntegration
from .vscode import VSCodeIntegration

__all__ = [
    "Integration",
    "integration_allowed",
    "ChromeIntegration",
    "SpotifyIntegration",
    "SteamIntegration",
    "VSCodeIntegration",
    "DiscordIntegration",
    "register",
    "get_integration",
    "all_integrations",
    "integration_status",
]