"""Structured understanding of what the user actually wants.

The rules pass is deterministic, fast and always available, so a casual chat
never waits for a second model round-trip. A model refinement can be layered
on top for ambiguous or multi-step requests; its JSON is validated and merged
instead of being trusted blindly.
"""

import json
import re
from dataclasses import dataclass, field

CATEGORIES = (
    "chat",
    "information",
    "research",
    "music",
    "weather",
    "calendar",
    "app_control",
    "system",
    "screen",
    "file",
    "development",
    "deep_work",
    "watch",
    "coach",
    "diagnostics",
    "media",
    "continuity",
)

RISKS = ("read", "low", "medium", "high")

_MUSIC_WORDS = re.compile(
    r"\b(song|songs|track|music|spotify|playlist|album|artist|listen|listening)\b",
    re.I,
)
_MUSIC_READ = re.compile(
    r"\b(what'?s playing|what is playing|now playing|which song|current song|"
    r"what song|who sings|what track)\b",
    re.I,
)
_MUSIC_CONTROL = re.compile(
    r"\b(play|pause|resume|skip|next|previous|go back|stop|volume)\b", re.I
)
_PLAY_BY = re.compile(
    r"^\s*(?:please\s+)?(?:play|put on|queue up)\s+\S.{0,140}?\s+by\s+\S.{0,60}$",
    re.I,
)
_NON_MUSIC_PLAY = re.compile(
    r"\b(video|videos|movie|movies|game|games|episode|trailer|match|chess|"
    r"recording|stream|live stream)\b",
    re.I,
)
_WEATHER_WORDS = re.compile(
    r"\b(weather|forecast|temperature|rain|raining|snow|sunny|cloudy|wind|"
    r"umbrella|humidity)\b",
    re.I,
)
_CALENDAR_WORDS = re.compile(
    r"\b(calendar|schedule|meeting|appointment|event|reminder|agenda|"
    r"book (?:a|an|me)|block (?:off|out))\b",
    re.I,
)
_APP_WORDS = re.compile(
    r"^\s*(?:please\s+)?(open|launch|start|run|close|quit|focus|switch to|"
    r"bring up)\s+(?P<name>.+)$",
    re.I,
)
_DEEP_WORDS = re.compile(
    r"\b(business plan|market research|competitor analysis|financial projection|"
    r"financial forecast|revenue model|pitch deck|presentation|spreadsheet|"
    r"proposal|whitepaper|white paper|deliverable|roadmap|essay|thesis|report)\b",
    re.I,
)
_DEVELOPMENT_WORDS = re.compile(
    r"\b(project|codebase|repository|repo|source code|bug|stack trace|unit test|"
    r"tests?|refactor|implement|debug|qoder|vs ?code|visual studio code|"
    r"pull request|merge conflict)\b",
    re.I,
)
_FILE_WORDS = re.compile(
    r"\b(read|write|save|create|make|edit|rename|move|copy|delete|organize)\b"
    r".{0,30}\b(file|folder|directory|document|documents|desktop)\b",
    re.I,
)
_SCREEN_WORDS = re.compile(
    r"\b(screenshot|screen capture|capture (?:the )?screen|what'?s on my screen|"
    r"see my screen|look at my screen|ocr)\b",
    re.I,
)
_SYSTEM_WORDS = re.compile(
    r"\b(volume|mute|unmute|battery|cpu|ram|memory usage|disk|processes|"
    r"what time is it|current time|system status)\b",
    re.I,
)
_RESEARCH_WORDS = re.compile(
    r"\b(who|what|when|where|why|how|compare|look up|find out|search for|"
    r"latest|news|research|explain|tell me about|is there|are there)\b",
    re.I,
)
_QUESTION_START = re.compile(r"^\s*(who|what|when|where|why|how|is|are|can|does|did)\b", re.I)

_WATCH_WORDS = re.compile(
    r"\b(watch me|watch my (?:screen|game|gameplay|play)|watch while i play|"
    r"keep an eye on my (?:screen|game)|game(?:ing)? companion|watch session|"
    r"watch the screen while)\b",
    re.I,
)
_WATCH_STOP = re.compile(
    r"\b(stop watching|stop the watch|stop watching me|stop the watch session)\b",
    re.I,
)
_COACH_WORDS = re.compile(
    r"\b(help me (?:set ?up|configure|connect|install)|walk me through|"
    r"(?:set ?up|setup) coach|i don'?t know how to (?:set ?up|configure|connect)|"
    r"configure my (?:spotify|voice|microphone|vscode|vs ?code|browser|ollama)|"
    r"(?:spotify|api) (?:client )?credentials|client id and (?:client )?secret|"
    r"where (?:do|can) i (?:get|find) .{0,40}credentials|"
    r"(?:inspect|show|check) (?:my )?settings|step by step (?:setup|set up))\b",
    re.I,
)
_DIAG_WORDS = re.compile(
    r"\b(system doctor|troubleshoot|diagnose (?:my|the|this)|"
    r"why (?:is|does|did) (?:my |the |this )?(?!code\b)[\w .'+-]{1,40}?"
    r"(?:so )?(?:slow|lag|crash|freeze|stutter|not respond|keeps? crashing|won'?t start)|"
    r"(?:game|app|program|pc|computer).{0,30}(?:keeps? crashing|freezes|"
    r"won'?t start|is slow)|blue screen|bsod|not responding|overheating|"
    r"system health|what'?s using my (?:cpu|ram|memory|disk|gpu)|"
    r"check my (?:pc|computer|system))\b",
    re.I,
)
_MEDIA_WORDS = re.compile(
    r"\b(transcript|transcribe|summari[sz]e (?:this|the|that) (?:video|youtube|clip)|"
    r"(?:video|youtube) (?:transcript|captions?)|captions of (?:this|the) video)\b",
    re.I,
)
_YOUTUBE_WORDS = re.compile(r"\byoutube\b|youtu\.be/|watch\?v=", re.I)
_VSCODE_WORDS = re.compile(
    r"\b(vs ?code|visual studio code|open (?:files|editors?|editor)|"
    r"what am i (?:working on|editing|looking at)|which file am i|"
    r"what file is open|review my code|check my code|look at my code|"
    r"find (?:the )?(?:bug|mistake|error) in my code)\b",
    re.I,
)
_CHANGE_WORDS = re.compile(
    r"\b(fix|refactor|implement|change|patch|edit|rewrite)\b", re.I
)
_PROGRAM_NAME = re.compile(
    r"\b(?:why (?:is|does|did) (?:my )?|diagnose(?: my| the)? )"
    r"(?P<program>[A-Za-z][\w .'+-]{1,40}?)\s+"
    r"(?:so\s+)?(?:keeps? crashing|crashing|freezes?|freezing|is slow|slow|"
    r"lagging|laggy|not responding|won'?t start)\b",
    re.I,
)
_CONTINUITY_WORDS = re.compile(
    r"\b(remember (?:that|what)\b|what was i (?:doing|working on|playing)|"
    r"what am i (?:working on|doing)|where was i|project context|"
    r"what'?s my context|my current project)\b",
    re.I,
)

_ACTION_VERBS = re.compile(
    r"\b(open|launch|play|pause|skip|schedule|create|make|write|read|send|"
    r"find|search|research|inspect|fix|build|organize|add|set|close|run)\b",
    re.I,
)

_PRONOUNS = re.compile(
    r"\b(it|that|this|them|those|these|the one|the second|the third|the last)\b",
    re.I,
)

_QUOTED = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{2,120})[\"'“”‘’]")
_BY_ARTIST = re.compile(r"^(?P<query>.+?)\s+by\s+(?P<artist>.+)$", re.I)
_IN_LOCATION = re.compile(
    r"\bin\s+(?P<place>[A-Za-z][\w .'’-]{1,60}?)(?=\s+(?:today|tomorrow|tonight|"
    r"this|next|for|at|on|and)\b|[,.]|$)",
)
_NOT_A_PLACE = {
    "the morning",
    "the evening",
    "the afternoon",
    "the week",
    "the next few days",
    "a bit",
    "general",
}
_WHEN_PHRASE = re.compile(
    r"\b(?:today|tomorrow|tonight|day after tomorrow|next\s+\w+|this\s+\w+|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"(?:\s+(?:at|around)?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?",
    re.I,
)
_ABOUT_TITLE = re.compile(r"\b(?:about|called|titled|named)\s+(?P<title>.+)$", re.I)


INTENT_PROMPT = """You convert one user request into a strict JSON object.

Return JSON only, with these keys:
objective (string), category (one of: chat, information, research, music,
weather, calendar, app_control, system, screen, file, development, deep_work,
watch, coach, diagnostics, media, continuity),
entities (object), target_application (string), target_service (string),
constraints (array of strings), expected_outcome (string),
required_capabilities (array of tool names if clear),
risk_level (read, low, medium or high), ambiguity (array of strings),
requires_action (boolean), multi_step (boolean), confidence (0 to 1).

Rules:
- Describe the user's intended outcome, not a keyword match.
- Do not invent applications, services or capabilities.
- If an essential detail is missing, put it in ambiguity instead of guessing.
- Never include prose outside the JSON object.

User request:
"""


@dataclass
class Intent:
    objective: str
    category: str = "chat"
    entities: dict = field(default_factory=dict)
    target_application: str = ""
    target_service: str = ""
    constraints: list = field(default_factory=list)
    expected_outcome: str = ""
    required_capabilities: list = field(default_factory=list)
    risk_level: str = "read"
    ambiguity: list = field(default_factory=list)
    requires_action: bool = False
    multi_step: bool = False
    context_references: list = field(default_factory=list)
    confidence: float = 0.5
    source: str = "rules"
    raw_text: str = ""

    def validate(self):
        if self.category not in CATEGORIES:
            self.category = "chat"
        if self.risk_level not in RISKS:
            self.risk_level = "medium"
        try:
            self.confidence = max(0.0, min(float(self.confidence), 1.0))
        except (TypeError, ValueError):
            self.confidence = 0.5
        self.entities = self.entities if isinstance(self.entities, dict) else {}
        self.constraints = [str(item) for item in (self.constraints or [])][:12]
        self.ambiguity = [str(item) for item in (self.ambiguity or [])][:12]
        self.required_capabilities = [
            str(item) for item in (self.required_capabilities or [])
        ][:12]
        self.context_references = [
            str(item) for item in (self.context_references or [])
        ][:12]
        self.multi_step = bool(self.multi_step)
        self.requires_action = bool(self.requires_action)
        return self

    def to_dict(self):
        return {
            "objective": self.objective,
            "category": self.category,
            "entities": self.entities,
            "target_application": self.target_application,
            "target_service": self.target_service,
            "constraints": self.constraints,
            "expected_outcome": self.expected_outcome,
            "required_capabilities": self.required_capabilities,
            "risk_level": self.risk_level,
            "ambiguity": self.ambiguity,
            "requires_action": self.requires_action,
            "multi_step": self.multi_step,
            "context_references": self.context_references,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "raw_text": self.raw_text,
        }

    def needs_clarification(self):
        return bool(self.ambiguity) and self.requires_action


def parse_intent_json(text):
    """Extract the first JSON object from a model reply, tolerating fences."""
    value = str(text or "").strip()
    if not value:
        raise ValueError("Empty intent response.")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", value, re.S)
    if fenced:
        value = fenced.group(1)
    else:
        start = value.find("{")
        end = value.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object in the intent response.")
        value = value[start : end + 1]
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("The intent response was not an object.")
    return data


def _clean_music_query(value):
    text = str(value or "").strip()
    text = re.sub(r"^(?:me\s+)?(?:the\s+)?(?:song|track|music)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+(?:on|from)\s+spotify\b", "", text, flags=re.I)
    text = re.sub(r"\bfor me\b", "", text, flags=re.I)
    text = re.sub(r"^something\s+(?:by|from)\s+", "", text, flags=re.I)
    return text.strip(" .,!?\"'")


def _action_count(text):
    return len(set(match.group(1).casefold() for match in _ACTION_VERBS.finditer(text)))


def _is_play_by_request(text):
    """'play <title> by <artist>' names a track even without a music noun."""
    if _NON_MUSIC_PLAY.search(text):
        return False
    return bool(_PLAY_BY.search(text))


def _when_phrase(text):
    match = _WHEN_PHRASE.search(text)
    if match:
        return match.group(0).strip()
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2})?\b", text)
    if iso:
        return iso.group(0)
    clock = re.search(r"\b(?:at|@)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", text, re.I)
    return clock.group(0).strip() if clock else ""


def _music_entities(text):
    entities = {}
    read_only = bool(_MUSIC_READ.search(text))
    if read_only:
        entities["action"] = "now_playing"
        return entities, read_only
    play = re.search(r"\bplay\s+(?P<rest>.+)$", text, re.I)
    if play:
        rest = _clean_music_query(play.group("rest"))
        by = _BY_ARTIST.match(rest)
        if by:
            entities["query"] = by.group("query").strip()
            entities["artist"] = by.group("artist").strip()
        else:
            entities["query"] = rest
    for verb in ("pause", "resume", "skip", "next", "previous", "stop", "mute"):
        if re.search(rf"\b{verb}\b", text, re.I) and "action" not in entities:
            entities["action"] = verb
    quoted = _QUOTED.search(text)
    if quoted and entities.get("query"):
        entities["query"] = quoted.group(1).strip()
    return entities, read_only


def _weather_entities(text):
    entities = {}
    location = _IN_LOCATION.search(text)
    if location:
        place = location.group("place").strip()
        if place.casefold() not in _NOT_A_PLACE:
            entities["location"] = place
    lowered = text.casefold()
    if "tomorrow" in lowered:
        entities["day_focus"] = "tomorrow"
        entities["days"] = 2
    elif "week" in lowered:
        entities["day_focus"] = "week"
        entities["days"] = 7
    else:
        entities["day_focus"] = "today"
        entities["days"] = 1
    return entities


def _calendar_entities(text):
    entities = {}
    lowered = text.casefold()
    if re.search(r"\b(cancel|delete|remove)\b", lowered):
        entities["action"] = "delete"
    elif re.search(r"\b(schedule|create|add|book|set up|remind|block)\b", lowered):
        entities["action"] = "create"
    else:
        entities["action"] = "list"
    when = _when_phrase(text)
    if when:
        entities["when"] = when
    title = _ABOUT_TITLE.search(text)
    if title:
        entities["title"] = title.group("title").strip(" .,!?\"'")
    duration = re.search(r"\bfor\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", lowered)
    if duration:
        amount = int(duration.group(1))
        if duration.group(2).startswith(("hour", "hr")):
            amount *= 60
        entities["duration_minutes"] = amount
    return entities


def _app_name(text):
    match = _APP_WORDS.match(text)
    if not match:
        return ""
    name = match.group("name").strip()
    name = re.split(r"\s+(?:and then|then|and)\s+", name, maxsplit=1, flags=re.I)[0]
    name = re.sub(
        r"^(?:the|my|a|an)\s+(?:app|application|program|window)\s+", "", name, flags=re.I
    )
    name = re.sub(r"^(?:the|my)\s+", "", name, flags=re.I)
    return name.strip(" .,!?\"'")


def rules_intent(text):
    """Deterministic structured intent; always returns a validated object."""
    raw = str(text or "").strip()
    lowered = raw.casefold()
    intent = Intent(objective=raw, raw_text=raw)

    music_command = bool(
        re.match(r"^\s*(?:please\s+)?(pause|resume|skip|next|previous|stop)\b", lowered)
    ) and not _WATCH_STOP.search(raw)
    if (
        (
            _MUSIC_WORDS.search(raw)
            or _MUSIC_READ.search(raw)
            or music_command
            or _is_play_by_request(raw)
        )
        and (_MUSIC_CONTROL.search(raw) or _MUSIC_READ.search(raw))
    ):
        entities, read_only = _music_entities(raw)
        query = str(entities.get("query") or "").strip()
        if read_only:
            intent.required_capabilities = ["now_playing"]
            intent.expected_outcome = "Report the track that is currently playing."
        elif entities.get("action") in {"pause", "resume", "skip", "next", "previous", "stop"}:
            intent.required_capabilities = ["media_control"]
            intent.expected_outcome = "Change the active media playback."
        else:
            intent.required_capabilities = ["play_music", "now_playing"]
            intent.expected_outcome = "Play the requested track and confirm it is playing."
        if query:
            if re.search(
                r"\b(yesterday|last night|earlier|that song|this song|the song)\b",
                query,
                re.I,
            ) or _PRONOUNS.fullmatch(query.strip()):
                intent.context_references.append(query)
                intent.entities["context"] = query
                intent.entities.pop("query", None)
                intent.ambiguity.append("which track")
            elif re.search(r"\b(favorite artist|my favorite|something|anything)\b", query, re.I):
                intent.entities.pop("query", None)
                intent.ambiguity.append("which artist or song")
            else:
                intent.entities["query"] = query
        intent.entities.update({k: v for k, v in entities.items() if k != "query"})
        if not intent.entities.get("query") and not intent.entities.get("artist") and not read_only:
            intent.ambiguity.append("which song or artist")
        intent.category = "music"
        intent.target_service = "Spotify"
        intent.target_application = "Spotify"
        intent.requires_action = not read_only
        intent.risk_level = "low" if not read_only else "read"
        intent.confidence = 0.9 if intent.entities.get("query") else 0.65
        return intent.validate()

    if _WEATHER_WORDS.search(raw):
        intent.category = "weather"
        intent.entities = _weather_entities(raw)
        intent.target_service = "Open-Meteo"
        intent.required_capabilities = ["weather_forecast"]
        intent.expected_outcome = "Report a live weather forecast."
        intent.risk_level = "read"
        intent.confidence = 0.9
        return intent.validate()

    if _CALENDAR_WORDS.search(raw):
        intent.category = "calendar"
        intent.entities = _calendar_entities(raw)
        intent.target_application = "Local calendar"
        action = intent.entities.get("action")
        intent.required_capabilities = (
            ["calendar_create"] if action == "create"
            else ["calendar_delete"] if action == "delete"
            else ["calendar_list"]
        )
        intent.expected_outcome = (
            "Create the event and confirm it exists." if action == "create"
            else "Delete the event and confirm it is gone." if action == "delete"
            else "Report the matching calendar events."
        )
        intent.requires_action = action in {"create", "delete"}
        intent.risk_level = "medium" if intent.requires_action else "read"
        if action == "create" and not intent.entities.get("when"):
            intent.ambiguity.append("start time")
        if action == "create" and not intent.entities.get("title"):
            implied = re.search(r"\b(meeting|appointment|call|reminder)\b", lowered)
            if implied:
                intent.entities["title"] = implied.group(1).capitalize()
            else:
                intent.ambiguity.append("event title")
        intent.confidence = 0.85
        return intent.validate()

    if _WATCH_WORDS.search(raw) or _WATCH_STOP.search(raw):
        stopping = bool(_WATCH_STOP.search(raw))
        intent.category = "watch"
        intent.entities["action"] = "stop" if stopping else "start"
        intent.required_capabilities = (
            ["watch_stop", "watch_status"] if stopping
            else ["watch_start", "watch_status"]
        )
        intent.expected_outcome = (
            "Stop the screen-watch session and remove the on-screen indicator."
            if stopping
            else "Watch the screen in short, visible intervals and help with what is happening."
        )
        intent.requires_action = True
        intent.risk_level = "low" if stopping else "medium"
        intent.confidence = 0.9
        return intent.validate()

    if _COACH_WORDS.search(raw):
        topic = "general"
        for candidate in (
            "spotify", "vscode", "voice", "browser", "ollama", "watch", "development",
        ):
            if candidate in lowered or (candidate == "vscode" and "vs code" in lowered):
                topic = candidate
                break
        intent.category = "coach"
        intent.entities["topic"] = topic
        intent.required_capabilities = [
            "setup_guide",
            "setup_verify",
            "inspect_settings",
            "app_registry",
            "open_url",
        ]
        intent.expected_outcome = (
            "Explain the exact setup steps, check what is already configured, "
            "and verify the result without exposing secrets."
        )
        intent.requires_action = False
        intent.multi_step = True
        intent.risk_level = "read"
        intent.confidence = 0.88
        return intent.validate()

    if _MEDIA_WORDS.search(raw) and _YOUTUBE_WORDS.search(raw):
        intent.category = "media"
        intent.required_capabilities = ["youtube_transcript"]
        link = re.search(r"https?://\S+", raw)
        if link:
            intent.entities["video"] = link.group(0).strip(" .,!?\"'")
        intent.expected_outcome = "Read the video's captions and summarize or answer from them."
        intent.risk_level = "read"
        intent.confidence = 0.85
        return intent.validate()

    if _DIAG_WORDS.search(raw):
        intent.category = "diagnostics"
        program = _PROGRAM_NAME.search(raw)
        if program:
            intent.entities["program"] = program.group("program").strip(" .,!?'\"")
        intent.required_capabilities = [
            "inspect_system",
            "diagnose_program",
            "running_processes",
            "active_window",
        ]
        intent.expected_outcome = (
            "Find the likely cause with read-only system evidence and explain "
            "the safest next step."
        )
        intent.requires_action = False
        intent.multi_step = True
        intent.risk_level = "read"
        intent.confidence = 0.85
        return intent.validate()

    if _CONTINUITY_WORDS.search(raw):
        remembering = bool(re.match(r"^\s*(?:please\s+)?remember\b", raw, re.I))
        intent.category = "continuity"
        intent.required_capabilities = (
            ["remember_activity"] if remembering
            else ["project_context", "vscode_editors", "watch_status"]
        )
        intent.expected_outcome = (
            "Save the activity note in local memory."
            if remembering
            else "Report the current project, editor and session context."
        )
        intent.requires_action = remembering
        intent.risk_level = "low" if remembering else "read"
        intent.confidence = 0.85
        return intent.validate()

    if _VSCODE_WORDS.search(raw) and not re.match(
        r"^\s*(?:please\s+)?(?:open|launch|start|run)\s+(?:vs ?code|visual studio code)\s*$",
        raw,
        re.I,
    ):
        intent.category = "development"
        intent.required_capabilities = [
            "vscode_editors",
            "vscode_read",
            "list_project_files",
            "open_project",
            "read_file",
            "search_code",
            "propose_change",
            "apply_change",
            "run_tests",
        ]
        if _CHANGE_WORDS.search(raw):
            intent.requires_action = True
        intent.target_application = "Visual Studio Code"
        intent.expected_outcome = (
            "Read the file that is actually open, review it like a pair "
            "programmer, and propose a verified change before writing."
        )
        intent.multi_step = True
        intent.risk_level = "medium" if intent.requires_action else "read"
        intent.confidence = 0.85
        return intent.validate()

    if _DEEP_WORDS.search(raw) and re.search(
        r"\b(create|make|build|prepare|draft|write|research|design|develop|produce)\b",
        lowered,
    ):
        intent.category = "deep_work"
        intent.required_capabilities = ["research_web", "write_file"]
        intent.expected_outcome = "Produce a finished, organized deliverable."
        intent.requires_action = True
        intent.multi_step = True
        intent.risk_level = "medium"
        intent.confidence = 0.8
        return intent.validate()

    if _DEVELOPMENT_WORDS.search(raw) and re.search(
        r"\b(inspect|fix|debug|implement|refactor|test|read|check|review|"
        r"work on|find the (?:bug|issue|error)|run the tests)\b",
        lowered,
    ):
        intent.category = "development"
        intent.required_capabilities = [
            "list_project_files",
            "search_code",
            "read_file",
            "open_project",
        ]
        if _VSCODE_WORDS.search(raw):
            intent.required_capabilities.extend(["vscode_editors", "vscode_read"])
        if _CHANGE_WORDS.search(raw):
            intent.required_capabilities.extend(
                ["propose_change", "apply_change", "run_tests"]
            )
        if re.search(r"\bqoder\b", lowered):
            intent.target_application = "Qoder"
        elif re.search(r"\bvs ?code\b", lowered):
            intent.target_application = "Visual Studio Code"
        intent.expected_outcome = "Inspect the project and act on the code safely."
        intent.requires_action = True
        intent.multi_step = True
        intent.risk_level = "medium"
        intent.confidence = 0.8
        return intent.validate()

    if _FILE_WORDS.search(raw):
        intent.category = "file"
        intent.required_capabilities = ["read_file", "write_file"]
        intent.expected_outcome = "Read or change the requested file."
        intent.requires_action = True
        intent.risk_level = "medium"
        intent.confidence = 0.75
        return intent.validate()

    if _SCREEN_WORDS.search(raw):
        intent.category = "screen"
        intent.required_capabilities = ["capture_screen_text", "screen_scene", "active_window"]
        intent.expected_outcome = "Report what is visible on screen."
        intent.requires_action = True
        intent.risk_level = "medium"
        intent.confidence = 0.85
        return intent.validate()

    if _SYSTEM_WORDS.search(raw):
        intent.category = "system"
        intent.required_capabilities = ["set_volume", "running_processes", "active_window"]
        intent.expected_outcome = "Report or change the requested system state."
        intent.requires_action = bool(re.search(r"\b(set|mute|unmute|change)\b", lowered))
        intent.risk_level = "low"
        intent.confidence = 0.8
        return intent.validate()

    app_name = _app_name(raw)
    if app_name:
        intent.category = "app_control"
        intent.entities["application"] = app_name
        intent.target_application = app_name
        closing = bool(re.match(r"^\s*(?:please\s+)?(close|quit)\b", lowered))
        intent.required_capabilities = (
            ["close_app", "find_app", "list_windows"]
            if closing
            else ["open_app", "find_app", "app_registry"]
        )
        intent.expected_outcome = (
            "Close the requested application cleanly."
            if closing
            else "Open or focus the requested application."
        )
        intent.requires_action = True
        intent.risk_level = "low"
        if _PRONOUNS.search(app_name):
            intent.context_references.append(app_name)
            intent.ambiguity.append("which application")
        if re.search(r"\b(installed|downloaded|added)\b", app_name, re.I):
            intent.ambiguity.append("which application")
        intent.multi_step = _action_count(raw) > 1
        intent.confidence = 0.8 if not intent.ambiguity else 0.6
        return intent.validate()

    if _QUESTION_START.search(raw) or _RESEARCH_WORDS.search(raw):
        intent.category = "research" if re.search(
            r"\b(research|look up|search for|find out|compare|latest|news)\b", lowered
        ) else "information"
        intent.required_capabilities = ["research_web"] if intent.category == "research" else []
        intent.expected_outcome = "Answer the question with current, reliable information."
        intent.risk_level = "read"
        intent.confidence = 0.7
        return intent.validate()

    intent.category = "chat"
    intent.expected_outcome = "Reply conversationally."
    intent.risk_level = "read"
    intent.confidence = 0.6
    return intent.validate()


def merge_model_intent(base, data):
    """Merge a validated model object into the deterministic intent."""
    if not isinstance(data, dict):
        return base
    objective = str(data.get("objective") or "").strip()
    if objective and len(objective) <= 500:
        base.objective = objective
    category = str(data.get("category") or "").strip().casefold()
    if category in CATEGORIES:
        base.category = category
    entities = data.get("entities")
    if isinstance(entities, dict):
        for key, value in entities.items():
            if value not in (None, "", []):
                base.entities.setdefault(str(key), value)
    for attribute in ("target_application", "target_service", "expected_outcome"):
        value = str(data.get(attribute) or "").strip()
        if value:
            setattr(base, attribute, value)
    for attribute in ("constraints", "required_capabilities", "ambiguity", "context_references"):
        values = data.get(attribute)
        if isinstance(values, list):
            merged = list(getattr(base, attribute))
            for value in values:
                text = str(value).strip()
                if text and text not in merged:
                    merged.append(text)
            setattr(base, attribute, merged)
    risk = str(data.get("risk_level") or "").strip().casefold()
    if risk in RISKS:
        base.risk_level = risk
    if isinstance(data.get("multi_step"), bool):
        base.multi_step = data["multi_step"]
    if isinstance(data.get("requires_action"), bool):
        base.requires_action = data["requires_action"]
    try:
        base.confidence = max(base.confidence, min(float(data.get("confidence", 0)), 1.0))
    except (TypeError, ValueError):
        pass
    base.source = "hybrid"
    return base.validate()


class IntentEngine:
    def __init__(self, model_call=None):
        self.model_call = model_call

    def understand(self, text, history=(), use_model=False):
        intent = rules_intent(text)
        if not use_model or self.model_call is None:
            return intent
        context = ""
        recent = [item for item in (history or []) if isinstance(item, dict)][-4:]
        if recent:
            context = "\nRecent conversation:\n" + "\n".join(
                f"{item.get('role')}: {str(item.get('content') or '')[:300]}"
                for item in recent
            )
        try:
            raw = self.model_call(INTENT_PROMPT + str(text) + context)
            data = parse_intent_json(raw)
        except Exception:
            return intent
        return merge_model_intent(intent, data)


def brief(intent):
    """One-line human summary used by the UI and the prompt."""
    parts = [intent.category.replace("_", " ")]
    if intent.target_application:
        parts.append(intent.target_application)
    elif intent.target_service:
        parts.append(intent.target_service)
    if intent.entities.get("query"):
        parts.append(f"‘{intent.entities['query']}’")
    if intent.multi_step:
        parts.append("multi-step")
    return " · ".join(parts)
