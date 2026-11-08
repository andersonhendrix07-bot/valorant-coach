"""Agent -> role map. Static because HenrikDev match data only carries the agent name/id.
Roster checked Nov 2026 (Miks, Controller, released Mar 2026 in patch 12.05).
Any agent not listed here is reported as 'Unknown' rather than guessed."""

AGENT_ROLES: dict[str, str] = {
    # Duelists
    "Jett": "Duelist", "Phoenix": "Duelist", "Reyna": "Duelist", "Raze": "Duelist",
    "Yoru": "Duelist", "Neon": "Duelist", "Iso": "Duelist", "Waylay": "Duelist",
    # Initiators
    "Sova": "Initiator", "Breach": "Initiator", "Skye": "Initiator", "KAY/O": "Initiator",
    "Fade": "Initiator", "Gekko": "Initiator", "Tejo": "Initiator",
    # Controllers
    "Brimstone": "Controller", "Omen": "Controller", "Viper": "Controller", "Astra": "Controller",
    "Harbor": "Controller", "Clove": "Controller", "Miks": "Controller",
    # Sentinels
    "Killjoy": "Sentinel", "Cypher": "Sentinel", "Sage": "Sentinel", "Chamber": "Sentinel",
    "Deadlock": "Sentinel", "Vyse": "Sentinel", "Veto": "Sentinel",
}

_LOWER = {k.lower(): v for k, v in AGENT_ROLES.items()}


def role_of(agent: str | None) -> str:
    if not agent:
        return "Unknown"
    return _LOWER.get(agent.strip().lower(), "Unknown")
