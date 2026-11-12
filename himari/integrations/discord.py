"""Discord integration: open and close only.

Sending messages is deliberately not implemented: Discord has no safe local
send interface, and UI-automation sends would be unreliable. Requests to send
report the limitation instead of pretending to work.
"""

from .base import Integration


class DiscordIntegration(Integration):
    name = "discord"
    launch_name = "Discord"
    discovery_names = ("Discord",)
    process_names = ("discord.exe",)