"""Registry of application integrations."""

from .base import Integration, integration_allowed
from .chrome import ChromeIntegration
from .discord import DiscordIntegration
from .spotify import SpotifyIntegration
from .steam import SteamIntegration
from .vscode import VSCodeIntegration

_INTEGRATIONS = {}


def register(integration):
    if not isinstance(integration, Integration):
        raise TypeError("Only Integration instances can be registered.")
    _INTEGRATIONS[integration.name.casefold()] = integration


def get_integration(name):
    return _INTEGRATIONS.get((name or "").casefold())


def all_integrations():
    return list(_INTEGRATIONS.values())


def integration_status():
    return [
        {
            "name": integration.name,
            "available": integration.is_available(),
            "running": integration.is_running(),
            "actions": integration.supported_actions(),
        }
        for integration in _INTEGRATIONS.values()
    ]


for _cls in (
    ChromeIntegration,
    SpotifyIntegration,
    SteamIntegration,
    VSCodeIntegration,
    DiscordIntegration,
):
    register(_cls())