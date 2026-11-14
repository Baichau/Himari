import sys, threading, logging, time, io
from datetime import datetime
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QTextEdit,
 QLineEdit,QPushButton,QLabel,QListWidget,QListWidgetItem,QCheckBox,QComboBox,QSlider,QTabWidget,
 QInputDialog,QFileDialog,QMessageBox,QSystemTrayIcon,QMenu,QScrollArea,QFrame,QSizePolicy,
 QSpinBox,QTreeWidget,QTreeWidgetItem,QHeaderView)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QPainter, QDesktopServices
from .config import load, save
from .paths import user_data_dir
from . import db, persona, chat_web, theme, ui_effects, ui_settings
from .ambient import AmbientBackground, AuroraDivider, reduced_motion_enabled
from .ui_living import StatusDot, VoiceWaveform
from .agent import AgentOrchestrator, CancellationToken
from .core.capabilities import (
    is_himari_browser_tool,
    registry as capability_registry,
    wants_himari_browser,
)
from .core.context import EnvironmentContext
from .core.intent import IntentEngine
from .control import dashboard as control_dashboard
from .control import diagnostics as control_diagnostics
from .control import settings as control_settings
from .memory import CATEGORIES, MemoryManager, retrieve as retrieve_memories, summarize_older
from .personality import load_persona
from .security import (
    SecurityLayer,
    new_decision,
    release_pending_confirmations,
    resolve_decision,
    wait_for_decision,
)
from .avatar import AvatarWidget, FloatingAvatarWindow
from .llm import LLM, LLMCancelled
from .research import research_for_prompt, should_research
from .voice import STT, TTS, Mic, WakeWordMonitor, correct_known_voice_commands
from .screen import ocr as ocr_image
from .attachments import (
    MAX_FILES,
    attachment_summary,
    attachment_text_block,
    image_attachment,
    load_attachment,
)
from .vision import VisionError, describe_images
from .tools import TOOLS
from .tool_results import as_text
log=logging.getLogger("himari.ui")

# Requests where the right tools cannot be predicted from the category alone
# keep the full toolbox; specialized intents get a focused, small tool list.
GENERAL_INTENTS = frozenset(
    {"chat", "app_control", "system", "screen", "file", "development", "deep_work"}
)

AGENT_STATUS_LABELS = {
    "understanding": "Understanding the request",
    "planning": "Planning the steps",
    "waiting_for_permission": "Waiting for your permission",
    "executing": "Using a tool",
    "observing": "Checking what happened",
    "verifying": "Verifying the result",
    "recovering": "Trying a safer alternative",
    "waiting_for_user": "Needs one detail from you",
    "completed": "Completed",
    "partially_completed": "Partly completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
}

AGENT_STATUS_AVATARS = {
    "completed": "Happy",
    "partially_completed": "Confused",
    "failed": "Error",
    "cancelled": "Idle",
    "waiting_for_permission": "Listening",
    "waiting_for_user": "Listening",
    "recovering": "Confused",
}

STEP_STATUS_LABELS = {
    "pending": "pending",
    "running": "running",
    "succeeded": "done",
    "failed": "failed",
    "denied": "denied",
    "invalid": "invalid",
    "skipped": "skipped",
}


def tools_for_intent(intent):
    """Return the tool entries that fit this turn without losing general tools."""
    if intent is None or getattr(intent, "category", "chat") in GENERAL_INTENTS:
        return [tool for tool in TOOLS if _tool_allowed_for_intent(tool, intent)]
    try:
        selected = capability_registry().select(intent)
    except Exception as exc:
        log.warning("Capability selection failed: %s", exc)
        return [tool for tool in TOOLS if _tool_allowed_for_intent(tool, intent)]
    return selected or [tool for tool in TOOLS if _tool_allowed_for_intent(tool, intent)]


def _tool_allowed_for_intent(tool, intent):
    """Keep Himari's isolated browser opt-in; the default browser stays the default."""
    name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", "")
    if not is_himari_browser_tool(name):
        return True
    required = getattr(intent, "required_capabilities", []) or []
    return wants_himari_browser(intent) or name in required


def app_icon():
    path = Path(__file__).resolve().parent / "avatar_assets" / "idle.png"
    return QIcon(str(path)) if path.is_file() else QIcon()


def _chord_value(widget, fallback):
    reader = getattr(widget, "currentChord", None)
    try:
        value = reader() if callable(reader) else widget.text()
    except Exception:
        value = ""
    return str(value or "").strip() or fallback


class UI(QMainWindow):
    token=Signal(str); status=Signal(str); done=Signal(str); tool=Signal(str)
    failed=Signal(str); cancelled=Signal(str)
    voice_result=Signal(str); screen_error=Signal(str)
    screenshot_ready=Signal(object,str); screenshot_error=Signal(str)
    ollama_checked=Signal(object)
    hotkey_pressed=Signal(); screen_hotkey_pressed=Signal(); confirmation_requested=Signal(object)
    auto_stop_requested=Signal(); wake_word_detected_signal=Signal(str)
    dashboard_ready=Signal(object); diagnostics_ready=Signal(object)
    agent_status=Signal(object); agent_finished=Signal(object)
    coach_ready=Signal(str); doctor_ready=Signal(str); watch_changed=Signal(object)
    def __init__(self):
        super().__init__(); self.setWindowTitle("Himari ひまり"); self.resize(1160,780)
        self.setMinimumSize(980,620)
        cfg = load()
        self.theme_name = str(cfg.get("ui", {}).get("theme", "dark"))
        self._colors = theme.palette(self.theme_name)
        self._font_size = int(cfg.get("ui", {}).get("font_size", 14))
        self.setStyleSheet(theme.stylesheet(self.theme_name, self._font_size))
        self.setFont(QFont("Segoe UI", self._font_size))
        self.setWindowIcon(app_icon())
        self.assistant_name = str((cfg.get("personality") or {}).get("name") or "Himari")
        self.session="default"
        try:
            db.approve_legacy_suggestions()
        except Exception:
            log.exception("Could not migrate legacy memory suggestions")
        self._messages=[]
        self._stream_message=None
        self._last_user_text=""
        self._last_screen_context=None
        self._last_attachments=[]
        self._attachments=[]
        self._attachment_widgets=[]
        self._cancel_event=threading.Event()
        self._render_timer=QTimer(self); self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(70); self._render_timer.timeout.connect(self._render_chat)
        self._wait_timer=QTimer(self); self._wait_timer.setInterval(1000)
        self._wait_timer.timeout.connect(self._wait_tick)
        self._tts_active=False
        self._voice_timer=QTimer(self); self._voice_timer.setInterval(80)
        self._voice_timer.timeout.connect(self._poll_voice)
        self._first_token_seen=True
        self._wait_started=0.0
        self._waiting_label="Waiting for Ollama…"
        self.security=SecurityLayer(confirm_callback=self._confirm_security_action)
        self.llm=LLM(TOOLS, security=self.security)
        self.tts=TTS(
            on_error=self._on_tts_error,
            on_finished=self._on_tts_finished,
        )
        self.mic=Mic(); self.stt=None; self.busy=False
        self.hotkey_id=None; self.screen_hotkey_id=None
        self._streamed_response = ""
        self.hotkey_error = None
        self.screen_hotkey_error = None
        self._ollama_check_running = False
        self._preload_running = False
        self._preload_done = False
        self._summary_running = False
        self._summary_at = 0
        self.agent_running = False
        self._agent_token = None
        self._dashboard_running = False
        self._diag_running = False
        self.wake_word_monitor = WakeWordMonitor(
            on_detect=self.wake_word_detected_signal.emit,
            on_error=self.status.emit,
        )
        self.wake_word_status = QLabel("Wake-word: idle")
        self.floating_avatar = FloatingAvatarWindow(self)
        self.floating_avatar.avatar.clicked.connect(self._restore_from_floating)
        self.tray=None
        self.capture_tray_action=None
        self._allow_quit = False
        self._init_tray()
        self.token.connect(self._token); self.status.connect(self._status)
        self.done.connect(self._done); self.tool.connect(self._tool)
        self.failed.connect(self._failed); self.cancelled.connect(self._cancelled)
        self.voice_result.connect(self._apply_voice_text)
        self.screenshot_ready.connect(self._screenshot_ready)
        self.screenshot_error.connect(self._screen_failed)
        self.hotkey_pressed.connect(self.toggle_mic)
        self.screen_hotkey_pressed.connect(self.screen_query)
        self.confirmation_requested.connect(self._confirm_tool)
        self.auto_stop_requested.connect(self._auto_stop_mic)
        self.wake_word_detected_signal.connect(self._wake_word_detected)
        self.ollama_checked.connect(self._apply_ollama_status)
        self.dashboard_ready.connect(self._apply_dashboard)
        self.diagnostics_ready.connect(self._apply_diagnostics)
        self.coach_ready.connect(self._apply_coach)
        self.doctor_ready.connect(self._apply_doctor)
        self.watch_changed.connect(self._apply_watch_status)
        self.agent_status.connect(self._agent_progress)
        self.agent_finished.connect(self._agent_done)
        self.tabs=ui_effects.AnimatedTabWidget(); tabs=self.tabs
        tabs.tabBar().hide()
        self.backdrop=AmbientBackground(self._colors, self)
        shell=QVBoxLayout(self.backdrop)
        shell.setContentsMargins(0,0,0,0); shell.setSpacing(0)
        body=QWidget(); body_row=QHBoxLayout(body)
        body_row.setContentsMargins(16,10,16,16); body_row.setSpacing(16)
        shell.addWidget(body)
        self.setCentralWidget(self.backdrop)
        # Chat tab
        chat=QWidget(); root=QHBoxLayout(chat)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        sidebar=QFrame(); sidebar.setObjectName("NavSidebar"); sidebar.setFixedWidth(248)
        side=QVBoxLayout(sidebar); side.setContentsMargins(16,18,16,16); side.setSpacing(9)
        brand_row=QHBoxLayout(); brand_row.setSpacing(8)
        side_brand=QLabel("Himari"); side_brand.setObjectName("AppTitle")
        side_glyph=QLabel("ひまり"); side_glyph.setObjectName("Tagline")
        brand_row.addWidget(side_brand); brand_row.addWidget(side_glyph); brand_row.addStretch()
        side_caption=QLabel("Living anime companion"); side_caption.setObjectName("MutedLine")

        status_card=QFrame(); status_card.setObjectName("GlassCard")
        status_layout=QVBoxLayout(status_card)
        status_layout.setContentsMargins(12,10,12,11); status_layout.setSpacing(6)
        status_head=QHBoxLayout(); status_head.setSpacing(8)
        self.status_dot=StatusDot(self._colors["accent"])
        self.avatar_state=QLabel("● Idle"); self.avatar_state.setObjectName("StatusChip")
        status_head.addWidget(self.status_dot)
        status_head.addWidget(self.avatar_state, 1)
        self.companion_note=QLabel("Here whenever you need me.")
        self.companion_note.setObjectName("MutedLine")
        self.companion_note.setWordWrap(True)
        status_layout.addLayout(status_head); status_layout.addWidget(self.companion_note)

        self.new_chat_btn=QPushButton("＋  New chat"); self.new_chat_btn.setObjectName("PrimaryButton")
        self.new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_chat_btn.clicked.connect(self.new_chat)
        side_title=QLabel("RECENT CHATS"); side_title.setObjectName("SidebarTitle")
        self.session_list=QListWidget(); self.session_list.setObjectName("SessionList")
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._session_menu)
        self.session_list.itemClicked.connect(self._session_changed)
        self.session_list.itemActivated.connect(self._session_changed)

        side.addLayout(brand_row); side.addWidget(side_caption)
        side.addSpacing(2); side.addWidget(status_card)
        self.watch_card=QFrame(); self.watch_card.setObjectName("GlassCard")
        watch_layout=QHBoxLayout(self.watch_card)
        watch_layout.setContentsMargins(10,7,8,7); watch_layout.setSpacing(6)
        self.watch_dot=StatusDot("#ff6b9d")
        self.watch_badge=QLabel("Watching"); self.watch_badge.setObjectName("StatusChip")
        self.watch_left=QLabel("")
        self.watch_left.setObjectName("MutedLine")
        self.watch_stop_btn=QPushButton("Stop"); self.watch_stop_btn.setObjectName("SoftButton")
        self.watch_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.watch_stop_btn.clicked.connect(self.stop_watch)
        watch_layout.addWidget(self.watch_dot)
        watch_layout.addWidget(self.watch_badge)
        watch_layout.addWidget(self.watch_left,1)
        watch_layout.addWidget(self.watch_stop_btn)
        self.watch_card.setVisible(False)
        side.addWidget(self.watch_card)
        side.addWidget(self.new_chat_btn); side.addSpacing(2)
        side.addWidget(side_title); side.addWidget(self.session_list, 1)
        side_hint=QLabel("Right-click a chat to delete it")
        side_hint.setObjectName("MutedLine"); side_hint.setWordWrap(True)
        side.addWidget(side_hint)
        explore_title=QLabel("EXPLORE"); explore_title.setObjectName("SidebarTitle")
        side.addWidget(explore_title)
        self._nav_buttons={}
        for label, index in (
            ("Chat", 0), ("Companion", 1), ("Dashboard", 2), ("Tasks", 3),
            ("Activity", 4), ("Memory", 5), ("Settings", 6), ("Diagnostics", 7),
        ):
            button=QPushButton(label); button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self.tabs.setCurrentIndex(i))
            self._nav_buttons[index]=button
            side.addWidget(button)
        side_privacy=QLabel("Private · stored only on this PC")
        side_privacy.setObjectName("MutedLine"); side_privacy.setWordWrap(True)
        side.addWidget(side_privacy)
        body_row.addWidget(sidebar)
        body_row.addWidget(tabs, 1)

        main=QVBoxLayout(); main.setSpacing(10)
        hero=QFrame(); hero.setObjectName("HeroCard")
        hero_row=QHBoxLayout(hero); hero_row.setContentsMargins(18,14,18,14); hero_row.setSpacing(18)
        stage=QFrame(); stage.setObjectName("AvatarStage")
        stage.setFixedSize(176,230)
        stage_layout=QVBoxLayout(stage); stage_layout.setContentsMargins(10,10,10,10)
        self.avatar=AvatarWidget(self); self.avatar.setFixedSize(152,208)
        self.avatar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.avatar.clicked.connect(self.toggle_floating_avatar)
        stage_layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignCenter)
        hero_row.addWidget(stage, 0, Qt.AlignmentFlag.AlignVCenter)

        info=QVBoxLayout(); info.setSpacing(7)
        name_row=QHBoxLayout(); name_row.setSpacing(10)
        name=QLabel("Himari"); name.setObjectName("HeroName")
        glyph=QLabel("ひまり"); glyph.setObjectName("Tagline")
        name_row.addWidget(name); name_row.addWidget(glyph)
        name_row.addStretch()
        self.mood_label=QLabel("Idle · dreaming of new chats")
        self.mood_label.setObjectName("HeroMood")
        tagline=QLabel(
            "Warm, local companion — she listens, remembers, and gets things done on this PC."
        )
        tagline.setObjectName("Tagline")
        tagline.setWordWrap(True)
        stats_row=QHBoxLayout(); stats_row.setSpacing(6)
        for text in ("● Fully local", "● Private memory", "● Voice ready"):
            chip=QLabel(text); chip.setObjectName("MutedLine")
            chip.setStyleSheet(
                f"color: {self._colors['muted']}; background-color: {self._colors['card']};"
                f" border: 1px solid {self._colors['border']}; border-radius: 10px;"
                " padding: 4px 9px; font-size: 10px;"
            )
            stats_row.addWidget(chip)
        stats_row.addStretch()
        actions_widget=QWidget()
        actions_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        header_actions=QHBoxLayout(actions_widget)
        header_actions.setContentsMargins(0,0,0,0); header_actions.setSpacing(8)
        self.voice_btn=QPushButton(); self.voice_btn.setCheckable(True)
        self.voice_btn.setObjectName("IconButton")
        self.voice_btn.setChecked(self._voice_replies())
        self.voice_btn.setToolTip("Speak replies aloud using the local Piper voice")
        self.voice_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.voice_btn.toggled.connect(self._toggle_voice_replies)
        self._update_voice_button(self.voice_btn.isChecked())
        self.floating_avatar_btn=QPushButton("↗ Float")
        self.floating_avatar_btn.setObjectName("IconButton")
        self.floating_avatar_btn.setToolTip("Keep Himari on top of other windows")
        self.floating_avatar_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.floating_avatar_btn.clicked.connect(self.toggle_floating_avatar)
        header_actions.addWidget(self.voice_btn)
        header_actions.addWidget(self.floating_avatar_btn)
        info.addLayout(name_row); info.addWidget(self.mood_label); info.addWidget(tagline)
        info.addLayout(stats_row)
        info.addLayout(header_actions)
        hero_row.addLayout(info, 1)
        main.addWidget(hero)

        toolbar=QHBoxLayout(); toolbar.setSpacing(8)
        self.mic_btn=QPushButton(self._talk_label()); self.mic_btn.setObjectName("ChipButton")
        self.mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_btn.clicked.connect(self.toggle_mic)
        self.stop_btn=QPushButton("Stop voice"); self.stop_btn.setObjectName("ChipButton")
        self.stop_btn.clicked.connect(self._stop_voice)
        screen_key = str(load().get("screen", {}).get("capture_hotkey", "f10") or "").upper()
        self.analyze_btn=QPushButton(f"Screen ({screen_key})" if screen_key else "Screen")
        self.analyze_btn.setObjectName("ChipButton")
        self.analyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.analyze_btn.clicked.connect(self.screen_query)
        self.show_tools_btn=QPushButton("Tool trace"); self.show_tools_btn.setCheckable(True)
        self.show_tools_btn.setObjectName("ChipButton")
        self.show_tools_btn.setToolTip("Show tool calls in the transcript")
        self.show_tools_btn.toggled.connect(lambda _: self._render_chat(force_scroll=True))
        self.save_memory_btn=QPushButton("Save memory"); self.save_memory_btn.setObjectName("ChipButton")
        self.save_memory_btn.setToolTip("Save selected chat text (or a new note) as a long-term memory")
        self.save_memory_btn.clicked.connect(self.save_chat_memory)
        self.clear_btn=QPushButton("Delete chat"); self.clear_btn.setObjectName("ChipButton")
        self.clear_btn.setToolTip("Delete this conversation from local history; saved memories are kept")
        self.clear_btn.clicked.connect(self.clear_chat)
        toolbar.addWidget(self.mic_btn); toolbar.addWidget(self.stop_btn)
        toolbar.addWidget(self.analyze_btn); toolbar.addWidget(self.save_memory_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.show_tools_btn); toolbar.addWidget(self.clear_btn)
        main.addLayout(toolbar)

        self.chat = chat_web.create_chat_view(
            self,
            colors=self._colors,
            assistant_name=self.assistant_name,
            font_size=self._font_size,
            theme_name=self.theme_name,
            engine=str(cfg.get("ui", {}).get("chat_engine", "web")),
        )
        if hasattr(self.chat, "fillRequested"):
            self.chat.fillRequested.connect(self._fill_from_welcome)
        self.chat.render_messages(
            [], assistant_name=self.assistant_name, force_scroll=True
        )
        main.addWidget(self.chat, 1)

        voice_row=QHBoxLayout(); voice_row.setSpacing(12)
        self.voice_wave=VoiceWaveform(self._colors)
        self.voice_wave.setToolTip("Real microphone and voice activity")
        voice_row.addWidget(self.voice_wave, 1)
        self.status_label=QLabel("Starting…"); self.status_label.setObjectName("StatusLine")
        voice_row.addWidget(self.status_label)
        main.addLayout(voice_row)
        self.wake_word_status.setObjectName("MutedLine")
        main.addWidget(self.wake_word_status)

        self.attachments_widget=QWidget()
        self.attachments_row=QHBoxLayout(self.attachments_widget)
        self.attachments_row.setContentsMargins(0,0,0,0); self.attachments_row.setSpacing(6)
        self.attachments_widget.setVisible(False)
        main.addWidget(self.attachments_widget)

        composer=QFrame(); composer.setObjectName("ComposerFrame")
        composer_row=QHBoxLayout(composer)
        composer_row.setContentsMargins(8,6,8,6); composer_row.setSpacing(6)
        self.attach_btn=QPushButton("＋")
        self.attach_btn.setObjectName("IconButton")
        self.attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.attach_btn.setToolTip(
            "Attach images, PDF, Word, spreadsheet, or text/code files. "
            "Files stay local and are read only for this message."
        )
        self.attach_btn.clicked.connect(self.attach_files)
        self.input=QLineEdit(); self.input.setObjectName("ComposerInput")
        self.input.setPlaceholderText("Say something to Himari…  (Enter to send)")
        self.input.returnPressed.connect(self.send)
        self.retry_btn=QPushButton("Retry")
        self.retry_btn.setObjectName("SoftButton")
        self.retry_btn.setToolTip("Send the last message again without adding a duplicate")
        self.retry_btn.clicked.connect(self.retry_last)
        self.retry_btn.setVisible(False)
        self.send_btn=QPushButton("Send"); self.send_btn.setObjectName("PrimaryButton")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self.send)
        self.stop_generation_btn=QPushButton("Stop"); self.stop_generation_btn.setObjectName("StopButton")
        self.stop_generation_btn.clicked.connect(self.stop_generation)
        self.stop_generation_btn.setVisible(False)
        composer_row.addWidget(self.attach_btn)
        composer_row.addWidget(self.input, 1)
        composer_row.addWidget(self.retry_btn)
        composer_row.addWidget(self.send_btn)
        composer_row.addWidget(self.stop_generation_btn)
        main.addWidget(composer)
        self.shortcut_hint=QLabel("")
        self.shortcut_hint.setObjectName("MutedLine")
        main.addWidget(self.shortcut_hint)
        self.input.textChanged.connect(self._refresh_send_button)
        self._refresh_send_button()
        root.addLayout(main, 1)
        tabs.addTab(chat,"Chat")
        # Companion tab
        companion_content=QWidget()
        companion_layout=QVBoxLayout(companion_content)
        companion_layout.setContentsMargins(26,18,26,26); companion_layout.setSpacing(12)
        companion_layout.addStretch(1)
        companion_card=QFrame(); companion_card.setObjectName("GlassCard")
        companion_card.setMaximumWidth(780)
        companion_body=QVBoxLayout(companion_card)
        companion_body.setContentsMargins(30,24,30,26); companion_body.setSpacing(10)
        companion_kicker=QLabel("COMPANION MODE")
        companion_kicker.setObjectName("SectionLabel")
        companion_kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        companion_title=QLabel("Himari, right here")
        companion_title.setObjectName("HeroName")
        companion_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        companion_stage=QFrame(); companion_stage.setObjectName("AvatarStage")
        companion_stage.setFixedSize(348,452)
        companion_stage_layout=QVBoxLayout(companion_stage)
        companion_stage_layout.setContentsMargins(12,12,12,12)
        self.companion_avatar=AvatarWidget(self)
        self.companion_avatar.setFixedSize(320,424)
        self.companion_avatar.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.companion_avatar.clicked.connect(self.toggle_floating_avatar)
        companion_stage_layout.addWidget(
            self.companion_avatar, 0, Qt.AlignmentFlag.AlignCenter
        )
        companion_stage_row=QHBoxLayout()
        companion_stage_row.addStretch()
        companion_stage_row.addWidget(companion_stage)
        companion_stage_row.addStretch()
        self.companion_state=QLabel("● Idle"); self.companion_state.setObjectName("StatusChip")
        self.companion_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.companion_state.setMaximumWidth(200)
        companion_state_row=QHBoxLayout()
        companion_state_row.addStretch()
        companion_state_row.addWidget(self.companion_state)
        companion_state_row.addStretch()
        self.companion_mood=QLabel("Idle · dreaming of new chats")
        self.companion_mood.setObjectName("HeroMood")
        self.companion_mood.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.companion_wave=VoiceWaveform(self._colors, bars=34)
        self.companion_wave.setFixedHeight(46)
        self.companion_wave.setMaximumWidth(430)
        companion_wave_row=QHBoxLayout()
        companion_wave_row.addStretch()
        companion_wave_row.addWidget(self.companion_wave, 1)
        companion_wave_row.addStretch()
        companion_actions=QHBoxLayout(); companion_actions.setSpacing(8)
        companion_talk=QPushButton("Talk to Himari"); companion_talk.setObjectName("PrimaryButton")
        companion_talk.setCursor(Qt.CursorShape.PointingHandCursor)
        companion_talk.clicked.connect(self.toggle_mic)
        companion_screen=QPushButton("Capture screen"); companion_screen.setObjectName("SoftButton")
        companion_screen.clicked.connect(self.screen_query)
        companion_float=QPushButton("Float avatar"); companion_float.setObjectName("SoftButton")
        companion_float.clicked.connect(self.toggle_floating_avatar)
        companion_back=QPushButton("Back to chat"); companion_back.setObjectName("SoftButton")
        companion_back.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        for button in (companion_talk, companion_screen, companion_float, companion_back):
            companion_actions.addWidget(button)
        companion_hint=QLabel(
            "Himari only listens when you start the microphone, and every tool "
            "still asks for your permission."
        )
        companion_hint.setObjectName("MutedLine")
        companion_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        companion_hint.setWordWrap(True)
        companion_body.addWidget(companion_kicker)
        companion_body.addWidget(companion_title)
        companion_body.addLayout(companion_stage_row)
        companion_body.addLayout(companion_state_row)
        companion_body.addWidget(self.companion_mood)
        companion_body.addLayout(companion_wave_row)
        companion_body.addSpacing(4)
        companion_body.addLayout(companion_actions)
        self.companion_watch_btn=QPushButton("Watch with me"); self.companion_watch_btn.setObjectName("SoftButton")
        self.companion_watch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.companion_watch_btn.clicked.connect(self.toggle_watch)
        companion_watch_row=QHBoxLayout()
        companion_watch_row.addStretch(); companion_watch_row.addWidget(self.companion_watch_btn)
        companion_watch_row.addStretch()
        self.companion_watch_status=QLabel(
            "Watch is off — she looks only while you ask, never records."
        )
        self.companion_watch_status.setObjectName("MutedLine")
        self.companion_watch_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.companion_watch_status.setWordWrap(True)
        companion_body.addLayout(companion_watch_row)
        companion_body.addWidget(self.companion_watch_status)
        companion_body.addWidget(companion_hint)
        companion_card_row=QHBoxLayout()
        companion_card_row.addStretch()
        companion_card_row.addWidget(companion_card, 1)
        companion_card_row.addStretch()
        companion_layout.addLayout(companion_card_row)

        coach_card=QFrame(); coach_card.setObjectName("GlassCard")
        coach_card.setMaximumWidth(780)
        coach_body=QVBoxLayout(coach_card)
        coach_body.setContentsMargins(24,18,24,20); coach_body.setSpacing(8)
        coach_kicker=QLabel("SETUP COACH")
        coach_kicker.setObjectName("SectionLabel")
        coach_title=QLabel("Let me walk you through a setup")
        coach_title.setObjectName("CardTitle")
        coach_title.setWordWrap(True)
        coach_row=QHBoxLayout(); coach_row.setSpacing(8)
        self.coach_topic=QComboBox()
        for label, key in (
            ("Spotify credentials", "spotify"),
            ("VS Code pairing", "vscode"),
            ("Voice and TTS", "voice"),
            ("Ollama models", "ollama"),
            ("Browser tools", "browser"),
            ("Watch companion", "watch"),
        ):
            self.coach_topic.addItem(label, key)
        self.coach_btn=QPushButton("Show steps"); self.coach_btn.setObjectName("SoftButton")
        self.coach_btn.clicked.connect(self.show_coach_guide)
        self.coach_verify_btn=QPushButton("Verify"); self.coach_verify_btn.setObjectName("SoftButton")
        self.coach_verify_btn.clicked.connect(self.verify_coach_setup)
        coach_row.addWidget(self.coach_topic,1)
        coach_row.addWidget(self.coach_btn)
        coach_row.addWidget(self.coach_verify_btn)
        self.coach_text=QTextEdit(); self.coach_text.setReadOnly(True)
        self.coach_text.setMaximumHeight(170)
        self.coach_text.setPlaceholderText(
            "Pick a topic and press Show steps. Secrets are never displayed, "
            "only whether they are configured."
        )
        coach_body.addWidget(coach_kicker)
        coach_body.addWidget(coach_title)
        coach_body.addLayout(coach_row)
        coach_body.addWidget(self.coach_text)
        coach_card_row=QHBoxLayout()
        coach_card_row.addStretch(); coach_card_row.addWidget(coach_card, 1); coach_card_row.addStretch()
        companion_layout.addLayout(coach_card_row)
        companion_layout.addStretch(1)
        companion=QScrollArea(); companion.setWidgetResizable(True)
        companion.setFrameShape(QFrame.Shape.NoFrame)
        companion.setWidget(companion_content)
        tabs.addTab(companion,"Companion")
        # Dashboard tab
        dash, dv, dash_head = self._page_shell(
            "Dashboard",
            "A calm overview of what Himari is doing on this PC — all local.",
        )
        refresh_dash=QPushButton("Refresh"); refresh_dash.setObjectName("SoftButton")
        refresh_dash.clicked.connect(self.refresh_dashboard)
        dash_head.addWidget(refresh_dash, 0, Qt.AlignmentFlag.AlignTop)
        dash_card, dash_body = self._glass_card()
        self.dashboard_text=QTextEdit(); self.dashboard_text.setReadOnly(True)
        self.dashboard_text.setObjectName("DashboardText")
        self.dashboard_text.setPlainText("Dashboard not loaded yet. Press Refresh.")
        dash_body.addWidget(self.dashboard_text, 2)
        activity_label=QLabel("RECENT ACTIVITY"); activity_label.setObjectName("SectionLabel")
        dash_body.addWidget(activity_label)
        self.dash_activity=QListWidget(); dash_body.addWidget(self.dash_activity, 1)
        dv.addWidget(dash_card, 1)
        tabs.addTab(dash,"Dashboard")
        tasks_tab, tv, tasks_head = self._page_shell(
            "Tasks",
            "Describe an outcome; Himari plans the steps, uses allowed tools, "
            "checks what happened, and reports honestly.",
        )
        tasks_card, task_body = self._glass_card()
        task_row=QHBoxLayout()
        self.agent_input=QLineEdit()
        self.agent_input.setPlaceholderText("e.g. Play Blinding Lights by The Weeknd")
        self.agent_input.returnPressed.connect(self.run_agent_task)
        self.agent_run_btn=QPushButton("Run task"); self.agent_run_btn.setObjectName("PrimaryButton")
        self.agent_run_btn.clicked.connect(self.run_agent_task)
        self.agent_cancel_btn=QPushButton("Cancel"); self.agent_cancel_btn.setObjectName("SoftButton")
        self.agent_cancel_btn.clicked.connect(self.cancel_agent_task)
        self.agent_cancel_btn.setEnabled(False)
        task_row.addWidget(self.agent_input,1); task_row.addWidget(self.agent_run_btn); task_row.addWidget(self.agent_cancel_btn)
        task_body.addLayout(task_row)
        task_hint=QLabel(
            "Anything risky asks for your permission first. Denying a step stops it; "
            "Himari never retries a denied or uncertain action on its own."
        )
        task_hint.setObjectName("SectionHint"); task_hint.setWordWrap(True)
        task_body.addWidget(task_hint)
        self.agent_status_label=QLabel("Agent: idle"); task_body.addWidget(self.agent_status_label)
        self.agent_plan=QTreeWidget()
        self.agent_plan.setHeaderLabels(["Step","Tool","Status","Check"])
        self.agent_plan.setRootIsDecorated(False)
        self.agent_plan.setAlternatingRowColors(True)
        self.agent_plan.setUniformRowHeights(True)
        self.agent_plan.setMinimumHeight(140)
        header = self.agent_plan.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        task_body.addWidget(self.agent_plan, 3)
        report_label=QLabel("COMPLETION REPORT"); report_label.setObjectName("SectionLabel")
        task_body.addWidget(report_label)
        self.agent_report=QTextEdit(); self.agent_report.setReadOnly(True)
        self.agent_report.setPlaceholderText("The report appears here when the task ends.")
        self.agent_report.setMaximumHeight(140)
        task_body.addWidget(self.agent_report, 1)
        tasks_history_row=QHBoxLayout()
        history_label=QLabel("RECENT TASKS"); history_label.setObjectName("SectionLabel")
        tasks_history_row.addWidget(history_label)
        open_task_btn=QPushButton("Open selected"); open_task_btn.setObjectName("SoftButton")
        open_task_btn.clicked.connect(self.open_selected_task)
        tasks_history_row.addWidget(open_task_btn); tasks_history_row.addStretch()
        task_body.addLayout(tasks_history_row)
        self.task_history=QListWidget()
        self.task_history.itemDoubleClicked.connect(lambda _item: self.open_selected_task())
        task_body.addWidget(self.task_history, 1)
        tv.addWidget(tasks_card, 1)
        tabs.addTab(tasks_tab,"Tasks")
        activity_tab, activity_layout, activity_head = self._page_shell(
            "Activity",
            "Every tool run with its real result — including actions that were "
            "denied or never happened.",
        )
        activity_refresh=QPushButton("Reload"); activity_refresh.setObjectName("SoftButton")
        activity_refresh.clicked.connect(self.refresh_actions)
        activity_head.addWidget(activity_refresh, 0, Qt.AlignmentFlag.AlignTop)
        activity_card, activity_body = self._glass_card()
        self.activity_list=QListWidget(); activity_body.addWidget(self.activity_list)
        activity_layout.addWidget(activity_card, 1)
        tabs.addTab(activity_tab,"Activity")
        # Memory tab
        mem, mv, mem_head = self._page_shell(
            "Memory",
            "What Himari remembers about you stays in a local database. "
            "Facts are never saved without review.",
        )
        mem_card, mem_body = self._glass_card()
        search_row=QHBoxLayout()
        self.memory_search=QLineEdit()
        self.memory_search.setPlaceholderText("Search saved memories")
        self.memory_search.textChanged.connect(self.refresh_mem)
        self.memory_filter=QComboBox()
        self.memory_filter.addItem("All categories", "")
        for category in CATEGORIES:
            self.memory_filter.addItem(category.replace("_", " ").title(), category)
        self.memory_filter.currentIndexChanged.connect(self.refresh_mem)
        search_row.addWidget(self.memory_search,1)
        search_row.addWidget(self.memory_filter)
        mem_body.addLayout(search_row)
        self.mem_list=QListWidget(); mem_body.addWidget(self.mem_list, 2)
        mrow=QHBoxLayout()
        add=QPushButton("Add"); add.setObjectName("SoftButton"); add.clicked.connect(self.add_mem)
        edit=QPushButton("Edit"); edit.setObjectName("SoftButton"); edit.clicked.connect(self.edit_mem)
        dele=QPushButton("Delete"); dele.setObjectName("SoftButton"); dele.clicked.connect(self.del_mem)
        conflicts=QPushButton("Check contradictions"); conflicts.setObjectName("SoftButton")
        conflicts.setToolTip(
            "Look for saved memories that appear to disagree. Nothing is changed automatically."
        )
        conflicts.clicked.connect(self.check_memory_conflicts)
        for b in [add,edit,dele,conflicts]: mrow.addWidget(b)
        mrow.addStretch()
        mem_body.addLayout(mrow)
        suggestion_label=QLabel("SUGGESTIONS — REVIEW BEFORE SAVING")
        suggestion_label.setObjectName("SectionLabel")
        mem_body.addWidget(suggestion_label)
        self.suggestion_list=QListWidget(); mem_body.addWidget(self.suggestion_list, 1)
        suggestion_row=QHBoxLayout()
        approve=QPushButton("Approve"); approve.setObjectName("PrimaryButton")
        approve.clicked.connect(self.approve_memory_suggestion)
        reject=QPushButton("Reject"); reject.setObjectName("SoftButton")
        reject.clicked.connect(self.reject_memory_suggestion)
        suggestion_row.addWidget(approve); suggestion_row.addWidget(reject)
        suggestion_row.addStretch()
        mem_body.addLayout(suggestion_row)
        mv.addWidget(mem_card, 1)
        self.memory_tab_index=tabs.addTab(mem,"Memory")
        # Settings tab
        settings_page, sv, settings_head = self._page_shell(
            "Settings",
            "Tune the voice, model, hotkeys and permissions. Everything is "
            "stored locally on this PC.",
        )
        settings_scroll=ui_settings.build_settings_page(self)
        sv.addWidget(settings_scroll, 1)
        self.settings_tab_index=tabs.addTab(settings_page,"Settings")
        diag, dv2, diag_head = self._page_shell(
            "Diagnostics",
            "Check local dependencies, Ollama, the database and permissions.",
        )
        self.diag_btn=QPushButton("Run diagnostics"); self.diag_btn.setObjectName("PrimaryButton")
        self.diag_btn.clicked.connect(self.run_diagnostics)
        diag_head.addWidget(self.diag_btn, 0, Qt.AlignmentFlag.AlignTop)
        diag_card, diag_body = self._glass_card()
        self.diag_text=QTextEdit(); self.diag_text.setReadOnly(True)
        self.diag_text.setPlainText(
            "Run diagnostics to check local dependencies, Ollama, the database, "
            "and permissions."
        )
        diag_body.addWidget(self.diag_text)
        dv2.addWidget(diag_card, 1)
        doctor_card, doctor_body = self._glass_card()
        doctor_head=QHBoxLayout(); doctor_head.setSpacing(8)
        doctor_title=QLabel("SYSTEM DOCTOR"); doctor_title.setObjectName("SectionLabel")
        self.doctor_name=QLineEdit()
        self.doctor_name.setPlaceholderText("Program or game name (optional)")
        self.doctor_system_btn=QPushButton("Inspect system"); self.doctor_system_btn.setObjectName("SoftButton")
        self.doctor_system_btn.clicked.connect(self.run_doctor_system)
        self.doctor_program_btn=QPushButton("Diagnose program"); self.doctor_program_btn.setObjectName("SoftButton")
        self.doctor_program_btn.clicked.connect(self.run_doctor_program)
        doctor_head.addWidget(doctor_title)
        doctor_head.addStretch()
        doctor_head.addWidget(self.doctor_name, 1)
        doctor_head.addWidget(self.doctor_system_btn)
        doctor_head.addWidget(self.doctor_program_btn)
        doctor_body.addLayout(doctor_head)
        self.doctor_text=QTextEdit(); self.doctor_text.setReadOnly(True)
        self.doctor_text.setPlaceholderText(
            "Read-only: uptime, CPU, memory, disks, GPU, top processes and recent "
            "Windows errors. Nothing is changed, terminated or uninstalled."
        )
        doctor_body.addWidget(self.doctor_text)
        dv2.addWidget(doctor_card, 1)
        tabs.addTab(diag,"Diagnostics")
        self.tabs.currentChanged.connect(self._sync_nav)
        self._sync_nav(self.tabs.currentIndex())
        self._restore_last_session()
        self.refresh_mem()
        self.refresh_actions()
        self.refresh_tasks()
        QTimer.singleShot(300,self.check)
        QTimer.singleShot(700,self.refresh_dashboard)
        QTimer.singleShot(2500,self._preload_model)
        self._bind_hotkeys()
        if self.cb_wake.isChecked():
            self._toggle_wake_word(True)
        self._settings_save_timer=QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(600)
        self._settings_save_timer.timeout.connect(self._autosave_settings)
        self._connect_settings_autosave()
        self._watch_timer=QTimer(self)
        self._watch_timer.setInterval(2000)
        self._watch_timer.timeout.connect(self._poll_watch)
        self._watch_timer.start()
        QTimer.singleShot(400, self._poll_watch)
    # ---- chat shell -------------------------------------------------
    def _talk_label(self, key=None):
        if key is None:
            key = load().get("voice", {}).get("push_to_talk_key")
        key = str(key or "").strip()
        return f"Talk ({key.upper()})" if key else "Talk"
    def _start_waiting(self):
        self._first_token_seen = False
        self._wait_started = time.monotonic()
        self._wait_timer.start()
        self._status(f"{getattr(self, '_waiting_label', 'Waiting for Ollama…')} 0s")
        self._set_avatar_state("Thinking")
    def _stop_waiting(self):
        self._wait_timer.stop()
    def _wait_tick(self):
        if not self.busy or self._first_token_seen:
            self._wait_timer.stop()
            return
        elapsed = max(0, int(time.monotonic() - self._wait_started))
        label = getattr(self, "_waiting_label", "Waiting for Ollama…")
        if elapsed >= 60:
            message = "Still working — you can press Stop."
        elif elapsed >= 20 and (
            label == "Waiting for Ollama…" or "waking the local model" in label.casefold()
        ):
            message = "Still loading the local model…"
        else:
            message = label
        self._status(f"{message} {elapsed}s")
        self._set_avatar_state("Thinking")
    def _voice_replies(self):
        try:
            return bool(load().get("voice", {}).get("speak_replies", True))
        except Exception:
            return True
    def _update_voice_button(self, enabled):
        self.voice_btn.setText("Voice on" if enabled else "Voice off")
        self.voice_btn.setToolTip(
            "Replies are spoken with the local Piper voice"
            if enabled else "Replies stay silent; click to speak them aloud"
        )
    def _toggle_voice_replies(self, enabled):
        self._update_voice_button(enabled)
        if not enabled:
            self.tts.stop()
        try:
            cfg = load()
            cfg.setdefault("voice", {})["speak_replies"] = bool(enabled)
            save(cfg)
        except Exception as exc:
            log.warning("Could not save speak_replies: %s", exc)
    def _update_hotkey_labels(self):
        try:
            cfg = load()
        except Exception:
            return
        talk_key = (cfg.get("voice") or {}).get("push_to_talk_key")
        capture_key = (cfg.get("screen") or {}).get("capture_hotkey")
        if getattr(self, "mic_btn", None) is not None:
            recording = bool(getattr(self, "mic", None) and self.mic.rec)
            self.mic_btn.setText(
                "Stop & Transcribe" if recording else self._talk_label(talk_key)
            )
        if getattr(self, "analyze_btn", None) is not None:
            key = str(capture_key or "").strip().upper()
            self.analyze_btn.setText(f"Screen ({key})" if key else "Screen")
        self._update_shortcut_hint(talk_key, capture_key)
    def _update_shortcut_hint(self, talk_key=None, capture_key=None):
        hint = getattr(self, "shortcut_hint", None)
        if hint is None:
            return
        if talk_key is None or capture_key is None:
            try:
                cfg = load()
            except Exception:
                cfg = {}
            talk_key = (cfg.get("voice") or {}).get("push_to_talk_key", talk_key)
            capture_key = (cfg.get("screen") or {}).get("capture_hotkey", capture_key)
        parts = ["Enter to send"]
        if str(talk_key or "").strip():
            parts.append(f"{str(talk_key).upper()} to talk")
        if str(capture_key or "").strip():
            parts.append(f"{str(capture_key).upper()} to capture")
        parts.append("drop files in anytime")
        hint.setText("   ·   ".join(parts))
    def _fill_from_welcome(self, text):
        text = str(text or "").strip()
        if not text or not hasattr(self, "input"):
            return
        self.input.setText(text)
        self.input.setCursorPosition(len(text))
        self.input.setFocus()
        ui_effects.pulse(self.input, duration=360, low=0.55)
    def _restore_last_session(self):
        try:
            recent = db.sessions(limit=1)
        except Exception as exc:
            log.warning("Could not read chat sessions: %s", exc)
            recent = []
        if recent:
            self.session = recent[0]["session"]
        self._load_messages()
        self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
    def _load_messages(self):
        try:
            self._messages = db.messages_detailed(self.session)
        except Exception as exc:
            log.warning("Could not load chat history: %s", exc)
            self._messages = []
    def _load_sessions(self, select=None):
        try:
            rows = db.sessions(limit=40)
        except Exception as exc:
            log.warning("Could not load chat sessions: %s", exc)
            rows = []
        self.session_list.blockSignals(True)
        self.session_list.clear()
        for row in rows:
            stamp = time.strftime("%b %d", time.localtime(row.get("updated") or time.time()))
            item = QListWidgetItem(
                f"{row.get('title') or 'Untitled chat'}\n"
                f"{stamp} · {row.get('messages', 0)} messages"
            )
            item.setData(Qt.ItemDataRole.UserRole, row.get("session"))
            item.setToolTip(str(row.get("session") or ""))
            self.session_list.addItem(item)
        self.session_list.blockSignals(False)
        self._select_session_item(select or self.session)
    def _select_session_item(self, session):
        for index in range(self.session_list.count()):
            item = self.session_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == session:
                self.session_list.setCurrentRow(index)
                return
        self.session_list.clearSelection()
        self.session_list.setCurrentRow(-1)
    def _session_changed(self, item):
        if item is None:
            return
        session = item.data(Qt.ItemDataRole.UserRole)
        if not session or session == self.session:
            return
        if self.busy:
            self._status("Stop the current reply before switching chats.")
            self._select_session_item(self.session)
            return
        self.tts.stop()
        self.session = session
        self._stream_message = None
        if getattr(self, "retry_btn", None) is not None:
            self.retry_btn.setVisible(False)
        self._load_messages()
        self._render_chat(force_scroll=True)
        self._status(f"Loaded {len(self._messages)} messages.")
    def new_chat(self):
        if self.busy:
            self._status("Stop the current reply before starting a new chat.")
            return
        self.tts.stop()
        self.session = datetime.now().strftime("chat-%Y%m%d-%H%M%S-%f")
        self._messages = []
        self._stream_message = None
        if getattr(self, "retry_btn", None) is not None:
            self.retry_btn.setVisible(False)
        self._load_sessions(select=self.session)
        self._render_chat(force_scroll=True)
        self.input.clear(); self.input.setFocus()
        self._status("New chat. What are we doing?")
    def _schedule_render(self):
        if not self._render_timer.isActive():
            self._render_timer.start()
    def _render_chat(self, force_scroll=False):
        messages = list(self._messages)
        if self._stream_message is not None:
            messages.append(self._stream_message)
        show_tools = bool(
            getattr(self, "show_tools_btn", None) and self.show_tools_btn.isChecked()
        )
        self.chat.render_messages(
            messages,
            show_tools=show_tools,
            assistant_name=self.assistant_name,
            colors=self._colors,
            force_scroll=force_scroll,
        )
    def _append_message(self, role, content, **extra):
        message = {"role": role, "content": str(content or ""), "ts": time.time()}
        message.update(extra)
        self._messages.append(message)
        self._schedule_render()
        return message
    def _persist_message(self, role, content):
        content = str(content or "").strip()
        if not content:
            return
        try:
            if load().get("privacy", {}).get("store_conversations", True):
                db.add_message(self.session, role, content)
        except Exception as exc:
            log.warning("Could not save chat message: %s", exc)
    def _maybe_summarize(self):
        if self._summary_running:
            return
        try:
            total = db.message_count(self.session)
        except Exception:
            return
        if total < 40 or total - self._summary_at < 16:
            return
        self._summary_at = total
        self._summary_running = True
        session = self.session

        def work():
            try:
                summarize_older(session, keep_recent=24)
            except Exception as exc:
                log.warning("Conversation summarization failed: %s", exc)
            finally:
                self._summary_running = False

        threading.Thread(target=work, daemon=True).start()
    def _finish_generation(self):
        self._stop_waiting()
        self.stop_generation_btn.setEnabled(True)
        self.stop_generation_btn.setVisible(False)
        self.input.setEnabled(True)
        self.input.setFocus()
        self._refresh_send_button()
    def _refresh_send_button(self, *_):
        if not hasattr(self, "send_btn") or not hasattr(self, "input"):
            return
        ready = bool(self.input.text().strip() or getattr(self, "_attachments", []))
        self.send_btn.setEnabled(bool(ready and not getattr(self, "busy", False)))
    def stop_generation(self):
        if not self.busy:
            return
        self._cancel_event.set()
        self._release_confirmations()
        timer = getattr(self, "_wait_timer", None)
        if timer is not None:
            timer.stop()
        self.stop_generation_btn.setEnabled(False)
        self._status("Stopping…")
    def _bind_hotkeys(self):
        self._remove_hotkeys()
        self._update_hotkey_labels()
        ptt_key = str(load()["voice"].get("push_to_talk_key") or "f9").strip()
        screen_key = str(load().get("screen", {}).get("capture_hotkey") or "f10").strip()
        self.hotkey_error = None
        self.screen_hotkey_error = None
        try:
            import keyboard
        except Exception as e:
            self.hotkey_error = f"Push-to-talk hotkey is unavailable; use the microphone button. ({e})"
            self.screen_hotkey_error = f"Screen-capture hotkey is unavailable. ({e})"
            log.warning("Global hotkey setup failed: %s", e)
            return
        if self.tray is not None:
            self.tray.setToolTip(
                f"Himari — {screen_key.upper()} screen capture; close hides to tray."
            )
        if self.capture_tray_action is not None:
            self.capture_tray_action.setText(f"Capture Screen ({screen_key.upper()})")
        try:
            self.hotkey_id=keyboard.add_hotkey(ptt_key,lambda:self.hotkey_pressed.emit())
        except Exception as e:
            self.hotkey_error = f"Push-to-talk hotkey '{ptt_key}' is unavailable; use the microphone button. ({e})"
            log.warning("Push-to-talk hotkey bind failed: %s", e)
        if screen_key.casefold() == ptt_key.casefold():
            self.screen_hotkey_error = "Screen-capture and push-to-talk keys must be different."
            return
        try:
            self.screen_hotkey_id=keyboard.add_hotkey(
                screen_key, lambda:self.screen_hotkey_pressed.emit()
            )
        except Exception as e:
            self.screen_hotkey_error = f"Screen-capture hotkey '{screen_key}' is unavailable. ({e})"
            log.warning("Screen-capture hotkey bind failed: %s", e)
    def _remove_hotkeys(self):
        hotkey_ids = (self.hotkey_id, self.screen_hotkey_id)
        self.hotkey_id = None
        self.screen_hotkey_id = None
        if not any(hotkey_id is not None for hotkey_id in hotkey_ids):
            return
        try:
            import keyboard
        except Exception as e:
            log.warning("Could not load keyboard module during hotkey cleanup: %s", e)
            return
        for hotkey_id in hotkey_ids:
            if hotkey_id is not None:
                try:
                    keyboard.remove_hotkey(hotkey_id)
                except Exception as e:
                    log.warning("Hotkey cleanup failed: %s", e)
    def check(self):
        if self._ollama_check_running:
            return
        self._ollama_check_running = True

        def probe():
            result = self.llm.model_status()
            if result[1] is None:
                self.llm.refresh_capabilities()
            self.ollama_checked.emit(result)

        threading.Thread(target=probe, daemon=True).start()
    def _preload_model(self):
        if self._preload_running or self._preload_done or self.busy:
            return
        try:
            enabled = bool(load().get("ollama", {}).get("preload_model", True))
        except Exception:
            enabled = True
        if not enabled:
            return
        self._preload_running = True
        if not self.busy:
            self._status("Warming up the local model — first reply will be quicker…")
        threading.Thread(target=self._preload_worker, daemon=True).start()
    def _preload_worker(self):
        try:
            self.llm.preload()
            self._preload_done = True
            log.info("Chat model preloaded into Ollama memory")
            if not self.busy:
                self._status("Ready — the local model is warm.")
        except Exception as exc:
            log.info("Chat model preload skipped: %s", exc)
        finally:
            self._preload_running = False
    def _apply_ollama_status(self, result):
        self._ollama_check_running = False
        models, error = result
        selected = self.model_box.currentText() or load()["ollama"]["chat_model"]
        configured = load()["ollama"]["chat_model"]
        choices = list(dict.fromkeys(["qwen3:8b", *models, configured, selected]))
        self.model_box.clear()
        self.model_box.addItems(choices)
        self.model_box.setCurrentText(selected)

        if error:
            message = (
                f"Ollama is unreachable at {load()['ollama']['host']}. "
                "Start Ollama; Himari will not download models automatically."
            )
            log.warning("Ollama is unavailable at startup: %s", error)
        elif selected not in models:
            message = (
                f"Ollama connected, but '{selected}' is not installed. "
                f"To add it, run: ollama pull {selected}"
            )
            log.warning("Selected Ollama model is not installed: %s", selected)
        else:
            message = f"Ollama connected ✓ — {selected} is available."
            log.info("Ollama model available at startup: %s", selected)
            QTimer.singleShot(0, self._preload_model)
        if self.hotkey_error:
            message = f"{message} {self.hotkey_error}"
        if self.screen_hotkey_error:
            message = f"{message} {self.screen_hotkey_error}"
        self._status(message)
        self._refresh_wake_word_status()
    def _set_avatar_state(self, state):
        p = self._colors
        states = {
            "Idle": ("● Idle", p["muted"]),
            "Listening": ("● Listening", p["success"]),
            "Thinking": ("● Thinking", p["warning"]),
            "Searching": ("● Searching", p["accent_2"]),
            "Speaking": ("● Speaking", p["accent_strong"]),
            "Working": ("● Working", p["accent"]),
            "Happy": ("● Happy", p["success"]),
            "Confused": ("● Confused", p["warning"]),
            "Sad": ("● Sad", p["error"]),
            "Error": ("● Error", p["error"]),
        }
        label, color = states.get(state, states["Idle"])
        self.avatar_state.setText(label)
        self.avatar_state.setStyleSheet(
            f"color: {color}; background-color: {p['card_alt']}; "
            "border-radius: 10px; padding: 4px 10px; font-weight: 600;"
        )
        moods = {
            "Idle": "Idle · dreaming of new chats",
            "Listening": "Listening · go ahead, I'm here",
            "Thinking": "Thinking · one moment…",
            "Searching": "Searching · looking through sources",
            "Speaking": "Speaking · out loud for you",
            "Working": "Working · busy on this PC",
            "Happy": "Happy · that went nicely!",
            "Confused": "Confused · hmm, say that again?",
            "Sad": "A little trouble · let's fix it",
            "Error": "Something went wrong · let's fix it",
        }
        notes = {
            "Idle": "Here whenever you need me.",
            "Listening": "Listening — take your time.",
            "Thinking": "Thinking it through…",
            "Searching": "Looking through the web or your project.",
            "Speaking": "Reading my reply out loud.",
            "Working": "Running a task on this PC.",
            "Happy": "That worked out nicely.",
            "Confused": "Something didn't quite land.",
            "Sad": "That didn't go as planned.",
            "Error": "Something failed — want to retry?",
        }
        if getattr(self, "mood_label", None) is not None:
            self.mood_label.setText(moods.get(state, moods["Idle"]))
        if getattr(self, "companion_note", None) is not None:
            self.companion_note.setText(notes.get(state, notes["Idle"]))
        if getattr(self, "status_dot", None) is not None:
            self.status_dot.set_color(color)
        avatar_state = {
            "Listening": "listening",
            "Thinking": "thinking",
            "Searching": "searching",
            "Speaking": "speaking",
            "Working": "thinking",
            "Happy": "happy",
            "Confused": "confused",
            "Sad": "sad",
            "Error": "error",
        }.get(state, "idle")
        self.avatar.set_state(avatar_state)
        self.avatar.set_accent(color)
        self.floating_avatar.set_state(avatar_state)
        self.floating_avatar.avatar.set_accent(color)
        companion_avatar = getattr(self, "companion_avatar", None)
        if companion_avatar is not None:
            companion_avatar.set_state(avatar_state)
            companion_avatar.set_accent(color)
        companion_state = getattr(self, "companion_state", None)
        if companion_state is not None:
            companion_state.setText(label)
            companion_state.setStyleSheet(
                f"color: {color}; background-color: {p['card_alt']}; "
                "border: 1px solid " + p["border_bright"] + "; "
                "border-radius: 12px; padding: 5px 14px; font-weight: 600;"
            )
        if getattr(self, "companion_mood", None) is not None:
            self.companion_mood.setText(moods.get(state, moods["Idle"]))
        if getattr(self, "_avatar_state_name", None) != state:
            self._avatar_state_name = state
            if state != "Idle":
                ui_effects.pulse(self.avatar_state, duration=420, low=0.45)
    def _flash_expression(self, state, delay_ms=1800):
        self._set_avatar_state(state)
        def reset():
            if self.busy or (getattr(self, "mic", None) and self.mic.rec):
                return
            if "speaking" in self.status_label.text().casefold():
                return
            self._set_avatar_state("Idle")
        QTimer.singleShot(delay_ms, reset)
    def toggle_floating_avatar(self):
        if self.floating_avatar.isVisible():
            self.floating_avatar.hide()
            self.floating_avatar_btn.setText("↗ Float")
            self.floating_avatar_btn.setToolTip("Keep Himari on top of other windows")
        else:
            self.floating_avatar.show()
            self.floating_avatar_btn.setText("◱ Dock")
            self.floating_avatar_btn.setToolTip("Return Himari to the main window")
    def _restore_from_floating(self):
        self.floating_avatar.hide()
        self.floating_avatar_btn.setText("↗ Float")
        self.floating_avatar_btn.setToolTip("Keep Himari on top of other windows")
        self.show(); self.raise_(); self.activateWindow()
    def _page_shell(self, title, subtitle):
        page=QWidget(); page.setObjectName("Page")
        layout=QVBoxLayout(page)
        layout.setContentsMargins(22,14,22,18); layout.setSpacing(10)
        head=QHBoxLayout(); head.setSpacing(12)
        text_col=QVBoxLayout(); text_col.setSpacing(2)
        title_label=QLabel(title); title_label.setObjectName("PageTitle")
        subtitle_label=QLabel(subtitle); subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        text_col.addWidget(title_label); text_col.addWidget(subtitle_label)
        head.addLayout(text_col,1)
        layout.addLayout(head)
        layout.addWidget(AuroraDivider(self._colors))
        return page, layout, head
    def _glass_card(self):
        card=QFrame(); card.setObjectName("GlassCard")
        body=QVBoxLayout(card)
        body.setContentsMargins(16,14,16,16); body.setSpacing(10)
        return card, body
    def _sync_nav(self, index):
        for nav_index, button in getattr(self, "_nav_buttons", {}).items():
            button.setChecked(int(nav_index) == int(index))
    def _status(self,s):
        self.status_label.setText(s)
        if "error" in s.lower() or "failed" in s.lower():
            self._set_avatar_state("Error")
        elif "listening" in s.lower():
            self._set_avatar_state("Listening")
        elif (
            "search" in s.lower()
            or "checking the web" in s.lower()
            or "looking through" in s.lower()
        ):
            self._set_avatar_state("Searching")
        elif (
            "generating" in s.lower()
            or "responding" in s.lower()
            or "thinking" in s.lower()
            or "checking" in s.lower()
            or "transcrib" in s.lower()
        ):
            self._set_avatar_state("Thinking")
        elif "speaking" in s.lower():
            self._set_avatar_state("Speaking")
        elif "tool" in s.lower() or "completed" in s.lower() or "working" in s.lower():
            self._set_avatar_state("Working")
        else:
            self._set_avatar_state("Idle")
    def _refresh_wake_word_status(self, state="idle"):
        p = self._colors
        if state == "listening":
            self.wake_word_status.setText("Wake-word: listening")
            self.wake_word_status.setStyleSheet(f"color: {p['success']}; font-weight: 600;")
        elif state == "triggered":
            self.wake_word_status.setText("Wake-word: detected")
            self.wake_word_status.setStyleSheet(f"color: {p['warning']}; font-weight: 600;")
        else:
            self.wake_word_status.setText("Wake-word: idle")
            self.wake_word_status.setStyleSheet(f"color: {p['muted']};")
    def _init_tray(self):
        if self.tray is not None:
            return
        icon = app_icon()
        if icon.isNull():
            icon = QIcon.fromTheme("preferences-system")
        if icon.isNull():
            px = QPixmap(64,64); px.fill(Qt.transparent)
            painter = QPainter(px); painter.setBrush(Qt.GlobalColor.magenta); painter.drawRoundedRect(8,8,48,48,14,14); painter.end(); icon = QIcon(px)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu(self)
        show_action = menu.addAction("Show Himari")
        show_action.triggered.connect(lambda: (self.show(), self.raise_(), self.activateWindow()))
        screen_key = load().get("screen", {}).get("capture_hotkey", "f10").upper()
        self.capture_tray_action = menu.addAction(f"Capture Screen ({screen_key})")
        self.capture_tray_action.triggered.connect(self.screen_query)
        hide_action = menu.addAction("Hide")
        hide_action.triggered.connect(self.hide)
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_from_tray)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.setToolTip(f"Himari — {screen_key} captures the screen; close to keep running in the tray.")
        self.tray.show()
    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isHidden():
                self.show(); self.raise_(); self.activateWindow()
            else:
                self.hide()
    def _quit_from_tray(self):
        self._allow_quit = True
        self.close()
    def _set_always_on_top(self, enabled):
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
    def add_allowed_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Choose an allowed folder")
        if folder and not any(self.allowed_folders.item(i).text()==folder
                              for i in range(self.allowed_folders.count())):
            self.allowed_folders.addItem(folder)
    def add_development_workspace(self):
        folder=QFileDialog.getExistingDirectory(self,"Choose a development workspace")
        if folder and not any(self.development_workspaces.item(i).text()==folder
                              for i in range(self.development_workspaces.count())):
            self.development_workspaces.addItem(folder)
    def open_log_folder(self):
        folder=user_data_dir()/"logs"
        try:
            folder.mkdir(parents=True,exist_ok=True)
        except OSError as exc:
            self._status(f"Could not open the log folder: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    def open_log_viewer(self):
        from .log_viewer import LogViewerDialog
        viewer=getattr(self,"_log_viewer",None)
        if viewer is None:
            viewer=LogViewerDialog(self)
            self._log_viewer=viewer
        viewer.refresh()
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()
    def _token(self,t):
        if not self.busy:
            return
        if not getattr(self, "_first_token_seen", True):
            self._first_token_seen = True
            timer = getattr(self, "_wait_timer", None)
            if timer is not None:
                timer.stop()
        self._streamed_response += t
        self._stream_message = {
            "role": "assistant",
            "content": self._streamed_response,
            "ts": time.time(),
            "streaming": True,
        }
        self._status("Generating response…")
        self._schedule_render()
    def _tool(self,s):
        if not self.busy:
            return
        self._append_message("tool", s)
        self._status("Action finished — waiting for Ollama to continue…")
        if getattr(self, "_wait_timer", None) is not None:
            self._first_token_seen = False
            self._wait_started = time.monotonic()
            self._wait_timer.start()
        self.refresh_actions()
    def _done(self,t):
        self.busy=False
        self._finish_generation()
        content = str(t or "").strip() or self._streamed_response.strip()
        self._stream_message=None
        self._streamed_response=""
        if content:
            self._append_message("assistant", content)
            self._persist_message("assistant", content)
        else:
            self._append_message("system", "Himari did not return a reply. Check Ollama and try again.")
            if getattr(self, "retry_btn", None) is not None:
                self.retry_btn.setVisible(True)
        self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
        self._maybe_summarize()
        self._flash_expression("Happy")
        self._speak(content)
    def _cancelled(self, partial):
        self.busy=False
        self._finish_generation()
        content = str(partial or self._streamed_response or "").strip()
        self._stream_message=None
        self._streamed_response=""
        if content:
            self._append_message("assistant", content)
            self._persist_message("assistant", content)
            self._status("Stopped — the partial reply was kept.")
        else:
            self._append_message("system", "Generation stopped.")
            self._status("Stopped.")
        self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
        self._flash_expression("Confused", 1200)
    def _poll_voice(self):
        waves = [
            wave
            for wave in (
                getattr(self, "voice_wave", None),
                getattr(self, "companion_wave", None),
            )
            if wave is not None
        ]
        if not waves:
            return
        recording = getattr(self, "mic", None) is not None and self.mic.rec
        speaking = bool(getattr(self, "_tts_active", False))
        for wave in waves:
            if recording:
                wave.set_mode("listening")
                wave.set_level(getattr(self.mic, "level", 0.0))
            elif speaking:
                wave.set_mode("speaking")
            else:
                wave.set_mode("idle")
        if not recording and not speaking:
            timer = getattr(self, "_voice_timer", None)
            if timer is not None:
                timer.stop()
    def _on_tts_finished(self):
        self._tts_active = False
        if not self.busy:
            self.status.emit("Ready.")
    def _on_tts_error(self, message):
        self._tts_active = False
        self.status.emit(f"TTS error: {message}")
    def _stop_voice(self):
        self._tts_active = False
        self.tts.stop()
        self._poll_voice()
        if not self.busy:
            self._status("Ready.")
    def _speak(self,t):
        if not self._voice_replies():
            self._status("Ready.")
            return
        try:
            if t.strip():
                self._tts_active = True
                if getattr(self, "_voice_timer", None) is not None:
                    self._voice_timer.start()
                self.status.emit("Speaking… click Stop voice to interrupt.")
                self.tts.speak(t)
            else:
                self._status("Ready.")
        except Exception as e:
            self._tts_active = False
            self._status(f"TTS unavailable: {e}")
    def attach_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach files",
            "",
            (
                "Supported files (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff "
                "*.pdf *.docx *.xlsx *.xlsm *.csv *.tsv *.json *.txt *.md *.py *.js "
                "*.ts *.tsx *.jsx *.java *.c *.h *.cpp *.cs *.go *.rs *.rb *.php "
                "*.html *.css *.xml *.yaml *.yml *.ini *.toml *.log *.sql *.sh *.ps1 "
                "*.bat);;All files (*.*)"
            ),
        )
        self._add_attachment_paths(paths)

    def _add_attachment_paths(self, paths):
        existing = {a.path for a in self._attachments if a.path}
        added = 0
        for raw in paths or []:
            if len(self._attachments) >= MAX_FILES:
                self._status(f"At most {MAX_FILES} attachments per message.")
                break
            path = Path(raw)
            if not path.is_file() or str(path) in existing:
                continue
            attachment = load_attachment(path)
            if not attachment.ok:
                self._status(f"{attachment.name}: {attachment.error}")
                continue
            self._attachments.append(attachment)
            existing.add(str(path))
            added += 1
        if added:
            self._refresh_attachments()
            self._status(
                f"{attachment_summary(self._attachments)} attached — "
                "add a question or press Send."
            )
        return added

    def _refresh_attachments(self):
        while self.attachments_row.count():
            item = self.attachments_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._attachment_widgets = []
        p = self._colors
        for index, attachment in enumerate(self._attachments):
            chip = QFrame()
            chip.setObjectName("AttachmentChip")
            chip.setStyleSheet(
                f"QFrame#AttachmentChip {{ background-color:{p['card_alt']}; "
                f"border:1px solid {p['border']}; border-radius:9px; }}"
            )
            row = QHBoxLayout(chip)
            row.setContentsMargins(6, 3, 4, 3)
            row.setSpacing(6)
            if attachment.is_image:
                preview = QPixmap()
                if preview.loadFromData(attachment.image_bytes or b""):
                    picture = QLabel()
                    picture.setPixmap(
                        preview.scaled(
                            34, 34,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    row.addWidget(picture)
            label = QLabel(
                attachment.name if attachment.ok
                else f"{attachment.name} — {attachment.error}"
            )
            label.setToolTip(attachment.label() if attachment.ok else attachment.error)
            label.setMaximumWidth(240)
            label.setStyleSheet(
                f"color:{p['text'] if attachment.ok else p['error']}; font-size:11px;"
            )
            row.addWidget(label)
            remove = QPushButton("×")
            remove.setFixedSize(20, 20)
            remove.setToolTip("Remove attachment")
            remove.setStyleSheet(
                "QPushButton { border:none; background:transparent; padding:0; "
                f"color:{p['muted']}; font-weight:700; }}"
            )
            remove.clicked.connect(
                lambda _checked=False, position=index: self._remove_attachment(position)
            )
            row.addWidget(remove)
            self.attachments_row.addWidget(chip)
            self._attachment_widgets.append(chip)
            ui_effects.fade_in(chip, duration=180, start=0.0)
        self.attachments_row.addStretch(1)
        self.attachments_widget.setVisible(bool(self._attachments))
        self._refresh_send_button()

    def _remove_attachment(self, index):
        if 0 <= index < len(self._attachments):
            self._attachments.pop(index)
            self._refresh_attachments()

    def _clear_attachments(self):
        self._attachments = []
        self._refresh_attachments()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self._add_attachment_paths(paths)
            event.acceptProposedAction()

    def send(self, screen_context=None):
        if self.busy:
            self._status("Finish or stop the current reply first.")
            return
        text=self.input.text().strip()
        attachments=list(self._attachments)
        if not text and attachments:
            text = "Please look at the attached file and explain what matters."
            self.input.setText(text)
        if not text: return
        self._last_user_text = text
        self._last_screen_context = screen_context
        self._last_attachments = attachments
        self.input.clear()
        self._append_message(
            "user", text, attachments=list(attachments)
        )
        self._persist_message("user", text)
        self._clear_attachments()
        self._load_sessions(select=self.session)
        privacy = load().get("privacy", {})
        if privacy.get("store_conversations", True) and privacy.get("auto_memory", True):
            try:
                if db.remember_request(text):
                    self.refresh_mem()
            except Exception as exc:
                log.exception("Could not save a memory")
                self.status.emit(f"Memory save error: {exc}")
        self._begin_generation(text, screen_context, attachments)
    def retry_last(self):
        if self.busy:
            self._status("Finish or stop the current reply first.")
            return
        text = str(self._last_user_text or "").strip()
        if not text:
            self._status("Nothing to retry yet.")
            return
        self.retry_btn.setVisible(False)
        self._begin_generation(
            text,
            self._last_screen_context,
            getattr(self, "_last_attachments", []),
        )
    def _begin_generation(self, text, screen_context=None, attachments=None):
        attachments = list(attachments or [])
        self.busy=True
        self._streamed_response = ""
        self._stream_message = None
        self._cancel_event = threading.Event()
        self.send_btn.setEnabled(False)
        self.retry_btn.setVisible(False)
        self.stop_generation_btn.setEnabled(True)
        self.stop_generation_btn.setVisible(True)
        self.input.setEnabled(False)
        if any(attachment.is_image for attachment in attachments):
            self._waiting_label = "Looking at your image…"
        elif should_research(text):
            self._waiting_label = "Checking the web for reliable sources…"
        else:
            ollama_cfg = load().get("ollama", {})
            first_load = bool(ollama_cfg.get("preload_model", True)) and not self._preload_done
            self._waiting_label = (
                "Waking the local model — the first reply can take a little longer…"
                if first_load
                else "Waiting for Ollama…"
            )
        self._start_waiting()
        threading.Thread(
            target=self._prepare_and_run,
            args=(text, screen_context, attachments, self._cancel_event),
            daemon=True,
        ).start()

    def _prepare_and_run(self, text, screen_context, attachments, cancel_event):
        try:
            attachments = list(attachments or [])
            image_atts = [
                attachment
                for attachment in attachments
                if attachment.is_image and attachment.ok
            ]
            text_atts = [
                attachment
                for attachment in attachments
                if attachment.ok and not attachment.is_image
            ]
            attachment_block = attachment_text_block(text_atts)
            vision_text = None
            if image_atts:
                if not load().get("permissions", {}).get("allow_vision", True):
                    self.failed.emit(
                        "Image analysis is disabled in Settings. Enable "
                        "'Send images to the local vision model' first."
                    )
                    return
                self.status.emit("Looking at your image…")
                self._waiting_label = "Looking at your image…"
                context_bits = str(screen_context or "")
                for attachment in image_atts:
                    window = attachment.meta.get("window")
                    if window:
                        context_bits += f"\nWindow: {window}"
                try:
                    vision_text = describe_images(
                        [attachment.image_bytes for attachment in image_atts[:3]],
                        question=text,
                        context=context_bits.strip(),
                    )
                    self.status.emit("Image understood — thinking…")
                except VisionError as exc:
                    log.warning("Vision analysis failed: %s", exc)
                    ocr_text = self._ocr_attachment_text(image_atts)
                    if ocr_text:
                        vision_text = (
                            "The vision model was unavailable "
                            f"({exc}). Local OCR text from the image:\n{ocr_text}"
                        )
                        self.status.emit(
                            "Vision model unavailable — using local OCR text…"
                        )
                    else:
                        vision_text = (
                            "Image analysis failed: "
                            f"{exc} The image could not be read."
                        )
                        self.status.emit("Image analysis failed — continuing…")
                if cancel_event.is_set():
                    self.cancelled.emit("")
                    return
                self._waiting_label = "Thinking through your question…"
            needs_research = should_research(text)
            deep_reasoning = bool(
                load().get("ollama", {}).get("deep_reasoning", True)
            )
            intent = None
            environment = None
            try:
                intent = IntentEngine().understand(text)
                environment = EnvironmentContext().brief(intent)
            except Exception as exc:
                log.warning("Intent or environment analysis failed: %s", exc)
            chat_tools = tools_for_intent(intent)
            think = deep_reasoning and persona.should_think(text)
            self._waiting_label = (
                "Thinking deeply about this…"
                if think
                else "Thinking through your question…"
            )
            research = None
            if needs_research:
                self.status.emit("Checking the web for reliable sources…")
                research = research_for_prompt(
                    text,
                    cancel=cancel_event,
                    progress=self.status.emit,
                )
                if cancel_event.is_set():
                    self.cancelled.emit("")
                    return
                if research and "Source:" in research:
                    self.status.emit("Web sources checked — thinking…")
                elif research:
                    self.status.emit("Web check failed — answering from knowledge…")
                self._waiting_label = (
                    "Thinking deeply about your question…"
                    if think
                    else "Thinking through your question…"
                )
            relevant = db.relevant_memories(text, limit=10)
            if MemoryManager().enabled():
                try:
                    relevant = [
                        {"text": memory.text}
                        for memory in retrieve_memories(text, limit=10)
                    ] or relevant
                except Exception as exc:
                    log.warning("Memory retrieval failed: %s", exc)
                recent = [
                    {"text": memory.get("text", "")}
                    for memory in db.memories(limit=5)
                ]
                combined = []
                seen = set()
                for memory in list(relevant or []) + recent:
                    value = str(memory.get("text") or "").strip()
                    key = value.casefold()
                    if not value or key in seen:
                        continue
                    seen.add(key)
                    combined.append({"text": value})
                relevant = combined[:12]
            else:
                relevant = []
            summary = db.summary_for_session(self.session)
            try:
                personality_settings = load().get("personality")
                persona_instructions = (
                    load_persona().instruction_block() if personality_settings else None
                )
            except Exception as exc:
                log.warning("Personality settings unavailable: %s", exc)
                persona_instructions = None
            history = db.history(self.session)
            if (
                history
                and history[-1].get("role") == "user"
                and history[-1].get("content") == text
            ):
                history = history[:-1]
            msgs=persona.build(
                history,
                relevant,
                user_query=text,
                summary=summary,
                screen_context=screen_context,
                extra=persona_instructions,
                research=research,
                attachments=attachment_block,
                vision=vision_text,
                directive=persona.directive_for(text),
                tools=chat_tools,
                intent=intent,
                environment=environment,
            )
        except Exception as exc:
            log.exception("Chat preparation failed")
            self.failed.emit(f"Chat preparation failed: {exc}")
            return
        if cancel_event.is_set():
            self.cancelled.emit("")
            return
        self._run(msgs, cancel_event, think=think, tools=chat_tools)
    def _ocr_attachment_text(self, image_attachments):
        parts = []
        for attachment in image_attachments:
            if not attachment.meta.get("source") == "screen" and not attachment.name.startswith("screen-"):
                continue
            try:
                image = Image.open(io.BytesIO(attachment.image_bytes or b""))
                text = ocr_image(image)
            except Exception as exc:
                log.warning("OCR fallback failed: %s", exc)
                continue
            text = str(text or "").strip()
            if text:
                parts.append(text[:6000])
        return "\n\n".join(parts)
    def _run(self,msgs,cancel_event=None,think=False,tools=None):
        out=[]
        def on_token(t): out.append(t); self.token.emit(t)
        def on_tool(n,a,r):
            self.tool.emit(f"{n} {a} → {as_text(r)}")
        try:
            self.llm.stream_chat(
                msgs,
                on_token,
                on_tool=on_tool,
                cancel_event=cancel_event,
                on_status=self.status.emit,
                think=think,
                tools=tools,
            )
            self.done.emit("".join(out))
        except LLMCancelled as exc:
            self.cancelled.emit(exc.partial or "".join(out))
        except Exception as e:
            self.failed.emit(f"LLM error: {e}")
    def _confirm_security_action(self, name, args, message):
        result=new_decision()
        self.confirmation_requested.emit((name,args,message,result))
        allowed = wait_for_decision(result)
        if not allowed and not result["event"].is_set():
            self._status("The confirmation timed out, so the action was not allowed.")
        return allowed
    def _confirm_tool(self,request):
        name,args,message,result=request
        if result["event"].is_set():
            return
        if name == "write_desktop_file":
            content = args.get("content", "")
            details = (
                f"File: {args.get('filename', '')}\n"
                f"Characters: {len(content) if isinstance(content, str) else 0}\n\n"
                f"Preview: {content[:500] if isinstance(content, str) else ''}"
            )
        elif name in {"apply_change", "propose_change"}:
            content = args.get("new_content", "")
            details = (
                f"File: {args.get('path', '')}\n"
                f"Characters: {len(content) if isinstance(content, str) else 0}\n\n"
                f"Preview: {content[:500] if isinstance(content, str) else ''}"
            )
        else:
            details = str(args)
        box=QMessageBox(self)
        box.setWindowTitle("Confirm Himari action")
        box.setText(f"{message}\n\n{name}:\n{details}")
        box.setIcon(QMessageBox.Question)
        box.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        self._confirm_box=box
        try:
            answer=box.exec()
        finally:
            self._confirm_box=None
        resolve_decision(result, answer==QMessageBox.Yes)
    def _release_confirmations(self):
        box=getattr(self,"_confirm_box",None)
        if box is not None:
            box.reject()
        release_pending_confirmations()
    def _failed(self,message):
        self.busy=False
        partial = str(self._streamed_response or "").strip()
        self._stream_message=None
        self._streamed_response=""
        self._finish_generation()
        if partial:
            self._append_message("assistant", partial)
            self._append_message(
                "system",
                "The reply above was interrupted and may be incomplete. " + message,
            )
        else:
            self._append_message("error", message)
        self.retry_btn.setVisible(True)
        self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
        self._status(message)
        self._flash_expression("Sad", 2600)
    def _auto_stop_mic(self):
        if self.mic.rec:
            audio=self.mic.stop(); self.mic_btn.setText(self._talk_label())
            self._poll_voice()
            self._status("Voice detected; transcribing locally…")
            threading.Thread(
                target=self._transcribe,
                args=(audio, self._recognition_language()),
                daemon=True,
            ).start()

    def toggle_mic(self):
        if self.mic.rec:
            audio=self.mic.stop(); self.mic_btn.setText(self._talk_label())
            self._poll_voice()
            self._status("Transcribing locally…")
            threading.Thread(
                target=self._transcribe,
                args=(audio, self._recognition_language()),
                daemon=True,
            ).start()
        else:
            try:
                self._tts_active = False
                self.tts.stop()
                self.mic.start(on_silence=None)
                self.mic_btn.setText("Stop & Transcribe")
                if getattr(self, "_voice_timer", None) is not None:
                    self._voice_timer.start()
                self._status("Listening… click Stop & Transcribe when you’re done.")
            except Exception as e: self._status(f"Microphone error: {e}")
    def _recognition_language(self):
        return self.lang_box.currentData() or "auto"
    def _transcribe(self,audio,selected_lang):
        try:
            cfg=load()
            cfg["voice"]["recognition_language"]=selected_lang
            cfg["voice"]["language"]=selected_lang
            save(cfg)
            if not self.stt or (self.stt.lang != selected_lang):
                self.stt = STT()
            used_english_only_model = selected_lang == "auto" and self.stt.model_name.endswith(".en")
            text=self.stt.transcribe(audio)
            if text and used_english_only_model:
                self.status.emit(
                    f"Heard: {text} (English-only model; install large-v3 for multilingual recognition.)"
                )
            else:
                self.status.emit(f"Heard: {text}" if text else "No speech detected. Try again.")
            if text: self.voice_result.emit(text)
        except Exception as e: self.status.emit(f"STT error: {e}")
    def _toggle_wake_word(self, enabled):
        cfg=load(); cfg["voice"]["wake_word_enabled"]=enabled; save(cfg)
        if enabled:
            self._refresh_wake_word_status("listening")
            try:
                self.wake_word_monitor.start()
            except Exception as e:
                self._status(f"Wake-word error: {e}")
        else:
            self._refresh_wake_word_status("idle")
            try:
                self.wake_word_monitor.stop()
            except Exception:
                pass
    def _wake_word_detected(self, wake_word):
        self._refresh_wake_word_status("triggered")
        self._status(f"{wake_word} detected — listening for your command.")
        self.input.setFocus()
        if not self.mic.rec:
            try:
                self.tts.stop()
                self.mic.start(on_silence=self.auto_stop_requested.emit)
                self.mic_btn.setText("Stop & Transcribe")
            except Exception as exc:
                self._status(f"Microphone error: {exc}")
    def _apply_voice_text(self,text):
        self.input.setText(correct_known_voice_commands(text))
        self.send()
    def screen_query(self):
        if self.busy:
            self._status(
                "Wait for the current response to finish "
                "before capturing the screen."
            )
            return
        if not self.cb_screen.isChecked():
            self._status("Screen capture is disabled in Settings.")
            return

        screen_cfg = load().get("screen", {}) or {}
        area_widget = getattr(self, "screen_area", None)
        try:
            chosen = area_widget.currentData() if area_widget is not None else None
        except Exception:
            chosen = None
        target = str(chosen or screen_cfg.get("monitor") or "primary").strip().casefold()
        region = getattr(self, "_screen_region", None) if target == "region" else None
        if target == "region" and not region:
            self._status(
                "Choose a custom region in Settings first, or switch the capture "
                "area back to the primary screen."
            )
            return
        if target == "active" and not self.cb_active_window.isChecked():
            self._status(
                "Active-window capture is disabled in Settings. Enable it or "
                "choose another capture area."
            )
            return
        target_text = {
            "primary": "your primary screen",
            "all": "all of your screens",
            "active": "your active window",
            "region": "the selected screen region",
        }.get(target, f"screen {target}")

        answer = QMessageBox.question(
            self,
            "Allow one-time screen capture?",
            (
                f"Himari will capture {target_text} once and attach it to your "
                "message so you can ask about it.\n\n"
                "It is read locally when you press Send — by the local vision "
                "model, or by on-device OCR when that model is unavailable — "
                "and it is never saved to disk.\n\n"
                "Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            self._status("Screen capture cancelled.")
            return
        if not self._save_settings(interactive=False):
            self._status("Screen capture cancelled because the settings could not be saved.")
            return

        question = self.input.text().strip()
        self.analyze_btn.setEnabled(False)
        self._status(f"Capturing {target_text}…")

        def work():
            try:
                from .perception.capture import capture_screen
                from .perception.scene import active_window_info

                image = capture_screen(
                    region=region,
                    monitor=None if target in ("primary", "region") else target,
                    active_window=target == "active",
                )
                try:
                    attachment = image_attachment(
                        image,
                        name=f"screen-{datetime.now():%Y%m%d-%H%M%S}.png",
                        meta={"source": "screen", "target": target},
                    )
                    if target == "active":
                        title, application = active_window_info()
                        if title:
                            attachment.meta["window"] = (
                                f"{application} — {title}" if application else title
                            )
                finally:
                    image.close()
                self.screenshot_ready.emit(attachment, question)
            except Exception as e:
                self.screenshot_error.emit(f"Screen error: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _screenshot_ready(self, attachment, question):
        self.analyze_btn.setEnabled(True)
        if self.isHidden():
            self.show(); self.raise_(); self.activateWindow()
        if attachment is None or not attachment.ok:
            self._status(
                getattr(attachment, "error", "") or "The screenshot could not be read."
            )
            return
        if len(self._attachments) >= MAX_FILES:
            self._status(f"At most {MAX_FILES} attachments per message.")
            return
        self._attachments.append(attachment)
        self._refresh_attachments()
        if question:
            self.input.setText(question)
        elif not self.input.text().strip():
            self.input.setText(
                "What is on my screen? Read the visible text and explain "
                "what matters."
            )
        self.input.setFocus()
        self._status(
            "Screenshot attached — add a question, then press Send. "
            "It is sent only to your local vision model."
        )

    def _screen_failed(self,message):
        self.analyze_btn.setEnabled(True)
        if self.isHidden():
            self.show(); self.raise_(); self.activateWindow()
        self._status(message)
    def _session_menu(self, pos):
        item=self.session_list.itemAt(pos)
        if item is None:
            return
        session=item.data(Qt.ItemDataRole.UserRole)
        if not session:
            return
        title=item.text().splitlines()[0] if item.text() else ""
        menu=QMenu(self)
        delete=menu.addAction("Delete this chat")
        delete.triggered.connect(lambda: self._delete_session(session, title))
        menu.exec(self.session_list.mapToGlobal(pos))
    def _delete_session(self, session, title=None):
        if self.busy:
            self._status("Stop the current reply before deleting a chat.")
            return
        label=f"“{title}”" if title else "this chat"
        answer=QMessageBox.question(
            self,
            "Delete chat?",
            (
                f"Delete {label} from local history?\n\n"
                "Saved memories, settings, and other chats are kept.\n\nContinue?"
            ),
            QMessageBox.Yes|QMessageBox.No,
            QMessageBox.No,
        )
        if answer!=QMessageBox.Yes:
            self._status("Delete cancelled.")
            return
        db.clear_session(session)
        if getattr(self, "retry_btn", None) is not None:
            self.retry_btn.setVisible(False)
        if session==self.session:
            self._messages=[]; self._stream_message=None
            remaining=db.sessions(limit=1)
            if remaining:
                self.session=remaining[0]["session"]; self._load_messages()
            else:
                self.session=datetime.now().strftime("chat-%Y%m%d-%H%M%S-%f")
            self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
        self._status("Chat deleted. Saved memories are kept.")
    def clear_chat(self):
        self._delete_session(self.session)
    def clear_all_history(self):
        if self.busy:
            self._status("Stop the current reply before clearing history.")
            return
        answer=QMessageBox.question(
            self,
            "Clear all chat history?",
            (
                "This deletes every saved chat message and summary on this PC.\n\n"
                "Saved memories, settings, the activity log, and avatar/voice assets "
                "are kept.\n\nContinue?"
            ),
            QMessageBox.Yes|QMessageBox.No,
            QMessageBox.No,
        )
        if answer!=QMessageBox.Yes:
            self._status("Clear cancelled.")
            return
        db.clear_all_sessions()
        self.session=datetime.now().strftime("chat-%Y%m%d-%H%M%S-%f")
        self._messages=[]; self._stream_message=None
        if getattr(self, "retry_btn", None) is not None:
            self.retry_btn.setVisible(False)
        self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
        self._status("Chat history cleared. Saved memories are kept.")
    def save_chat_memory(self):
        self.chat.selected_text(self._save_chat_memory_dialog)
    def _save_chat_memory_dialog(self, selected):
        selected = str(selected or "").replace("\u2029", " ").strip()
        text,ok=QInputDialog.getText(
            self,
            "Save to memory",
            "Saved locally and used in future chats:",
            text=selected[:240],
        )
        text=(text or "").strip()
        if not ok or not text:
            return
        if db.memory_is_sensitive(text):
            QMessageBox.warning(
                self,
                "Not saved",
                "That looks like a password, contact detail, or other sensitive "
                "information, so it was not saved.",
            )
            return
        if db.add_memory(text[:500], source="user", approved=1):
            self.refresh_mem()
            self._status("Saved to memory. It will be available in future chats.")
        else:
            self._status("That memory is already saved.")
    def refresh_mem(self):
        query=self.memory_search.text().strip().casefold()
        category=self.memory_filter.currentData() if hasattr(self,"memory_filter") else ""
        self.mem_list.clear()
        for m in db.memories():
            text=str(m.get("text") or "")
            if query and query not in text.casefold():
                continue
            if category and (m.get("category") or "personal_context") != category:
                continue
            label=(m.get("category") or "personal_context").replace("_"," ")
            item=QListWidgetItem(f"{label} · {text}")
            item.setData(Qt.UserRole, m["id"])
            item.setToolTip(text)
            self.mem_list.addItem(item)
        self.suggestion_list.clear()
        suggestions=db.memory_suggestions()
        for suggestion in suggestions:
            item=QListWidgetItem(f"{suggestion['id'][:8]} — {suggestion['text']}")
            item.setData(Qt.UserRole, suggestion["id"])
            self.suggestion_list.addItem(item)
        tabs=getattr(self,"tabs",None)
        if tabs is not None and getattr(self,"memory_tab_index",None) is not None:
            tabs.setTabText(
                self.memory_tab_index,
                f"Memory ({len(suggestions)})" if suggestions else "Memory",
            )
    def _selected_memory_suggestion(self):
        item=self.suggestion_list.currentItem()
        if item is None:
            return None
        memory_id=item.data(Qt.UserRole)
        suggestions=db.memory_suggestions()
        return next(
            (suggestion for suggestion in suggestions if suggestion["id"]==memory_id),
            None,
        )
    def approve_memory_suggestion(self):
        suggestion=self._selected_memory_suggestion()
        if suggestion:
            db.add_memory(suggestion["text"],source="user",approved=1)
            self.refresh_mem()
    def reject_memory_suggestion(self):
        suggestion=self._selected_memory_suggestion()
        if suggestion:
            db.delete_memory(suggestion["id"])
            self.refresh_mem()
    def refresh_actions(self):
        self.activity_list.clear()
        for action in db.recent_actions():
            timestamp=datetime.fromtimestamp(action["ts"]).strftime("%Y-%m-%d %H:%M:%S")
            text = (
                f"{timestamp}  {action['tool']}  "
                f"allowed={bool(action['approved'])}"
            )
            result = str(action["result"] or "").strip()
            if result:
                text += f"\n{result}"
            self.activity_list.addItem(text)
    def refresh_dashboard(self):
        if self._dashboard_running:
            return
        self._dashboard_running = True
        interactions = {
            "state": "busy" if self.busy else "idle",
            "busy": self.busy,
            "current_task": self.agent_input.text().strip() if self.agent_running else "",
        }
        control_dashboard.build_dashboard_async(
            lambda snapshot, error: self.dashboard_ready.emit((snapshot, error)),
            model_status=self.llm.model_status,
            interactions=interactions,
        )
    def _apply_dashboard(self, payload):
        self._dashboard_running = False
        snapshot, error = payload
        if error:
            self.dashboard_text.setPlainText(f"Dashboard error: {error}")
            return
        self.dashboard_text.setPlainText(control_dashboard.format_dashboard(snapshot))
        self.dash_activity.clear()
        for row in snapshot["recent_activity"]:
            status = "allowed" if row["approved"] else "denied"
            text = f"{row['display_time']}  {row['tool']}  [{status}]"
            result = str(row["result"] or "").strip()[:200]
            if result:
                text += f"\n{result}"
            self.dash_activity.addItem(text)
    def run_diagnostics(self):
        if self._diag_running:
            return
        self._diag_running = True
        self.diag_btn.setEnabled(False)
        self.diag_text.setPlainText("Running local diagnostics…")
        control_diagnostics.diagnostics_async(
            lambda checks, error: self.diagnostics_ready.emit((checks, error)),
            model_status=self.llm.model_status,
            include_windows=True,
        )
    def _apply_diagnostics(self, payload):
        self._diag_running = False
        self.diag_btn.setEnabled(True)
        checks, error = payload
        if error:
            self.diag_text.setPlainText(f"Diagnostics error: {error}")
            return
        self.diag_text.setPlainText(control_diagnostics.format_diagnostics(checks))
    # ---- watch companion --------------------------------------------
    def toggle_watch(self):
        try:
            from .skills import watch

            running = watch.session().status().get("running")
        except Exception as exc:
            self._status(f"Watch is unavailable: {exc}")
            return
        if running:
            self.stop_watch()
        else:
            self.start_watch()
    def start_watch(self):
        try:
            from .skills import watch

            status = watch.session().start()
        except Exception as exc:
            self._status(f"Watch not started: {exc}")
            return
        self._apply_watch_status(status)
        self._status(
            "Watch started. She takes one local look every few seconds, shows the "
            "indicator, and stops automatically."
        )
    def stop_watch(self):
        try:
            from .skills import watch

            watch.session().stop("stopped from the UI")
            status = watch.session().status()
        except Exception as exc:
            self._status(f"Could not stop the watch session: {exc}")
            return
        self._apply_watch_status(status)
        self._status("Watch stopped. The observations were in-memory only.")
    def _poll_watch(self):
        try:
            from .skills import watch

            status = watch.session().status()
        except Exception:
            return
        self._apply_watch_status(status)
    def _apply_watch_status(self, status):
        status = status or {}
        running = bool(status.get("running"))
        self.watch_card.setVisible(running)
        remaining = str(status.get("remaining_text") or "")
        self.watch_left.setText(remaining)
        self.companion_watch_btn.setText("Stop watching" if running else "Watch with me")
        if running:
            last = status.get("last") or {}
            subject = last.get("game") or last.get("application") or "your screen"
            self.companion_watch_status.setText(
                f"Watching {subject} · {remaining} left · screenshots discarded"
            )
        else:
            interval = status.get("interval_seconds") or 20
            cap = status.get("limit_minutes") or 30
            self.companion_watch_status.setText(
                f"Watch is off — a session would look every {interval}s, "
                f"at most {cap} min, and save nothing."
            )
    # ---- setup coach ------------------------------------------------
    def _coach_topic_key(self):
        return str(self.coach_topic.currentData() or "spotify")
    def show_coach_guide(self):
        topic = self._coach_topic_key()
        try:
            from .skills import coach

            text = coach.setup_guide(topic)
        except Exception as exc:
            text = f"Could not build the {topic} guide: {exc}"
        self.coach_text.setPlainText(text)
    def verify_coach_setup(self):
        topic = self._coach_topic_key()
        self.coach_verify_btn.setEnabled(False)
        self.coach_text.setPlainText(f"Checking {topic}…")
        def work():
            try:
                from .skills import coach

                text = coach.setup_verify(topic)
            except Exception as exc:
                text = f"The {topic} check failed: {exc}"
            self.coach_ready.emit(str(text))
        threading.Thread(target=work, daemon=True).start()
    def _apply_coach(self, text):
        self.coach_verify_btn.setEnabled(True)
        self.coach_text.setPlainText(str(text or ""))
    # ---- system doctor ----------------------------------------------
    def run_doctor_system(self):
        from .skills import doctor

        self._run_doctor(doctor.inspect_system, "Inspecting the system (read-only)…")
    def run_doctor_program(self):
        name = self.doctor_name.text().strip()
        if not name:
            self.doctor_text.setPlainText(
                "Type the program or game name first, then press Diagnose program."
            )
            return
        from .skills import doctor

        self._run_doctor(
            lambda: doctor.diagnose_program(name),
            f"Diagnosing {name} (read-only)…",
        )
    def _run_doctor(self, task, message):
        self.doctor_system_btn.setEnabled(False)
        self.doctor_program_btn.setEnabled(False)
        self.doctor_text.setPlainText(message)
        def work():
            try:
                text = task()
            except Exception as exc:
                text = f"System Doctor failed: {exc}"
            self.doctor_ready.emit(str(text))
        threading.Thread(target=work, daemon=True).start()
    def _apply_doctor(self, text):
        self.doctor_system_btn.setEnabled(True)
        self.doctor_program_btn.setEnabled(True)
        self.doctor_text.setPlainText(str(text or ""))
    def run_agent_task(self):
        if self.agent_running:
            return
        task = self.agent_input.text().strip()
        if not task:
            self._status("Describe a task before running the agent.")
            return
        self.agent_running = True
        self.busy = True
        self._agent_token = CancellationToken()
        self.agent_run_btn.setEnabled(False); self.agent_cancel_btn.setEnabled(True)
        self.agent_status_label.setText("Agent: Understanding the request")
        self.agent_plan.clear()
        self.agent_report.clear()
        self.status_label.setText("Working on the task…")
        self._set_avatar_state("Working")
        self._append_message("user", task)
        self._persist_message("user", task)
        self._render_chat(force_scroll=True)
        token = self._agent_token
        def confirm(name, args, message):
            result=new_decision()
            self.confirmation_requested.emit((name,args,message,result))
            return wait_for_decision(result)
        def work():
            try:
                orchestrator = AgentOrchestrator(
                    confirm_callback=confirm,
                    on_status=lambda event: self.agent_status.emit(event),
                    persist=True,
                )
                state = orchestrator.run(task, token=token)
                self.agent_finished.emit(state.to_dict())
            except Exception as exc:
                self.agent_finished.emit({
                    "status": "failed", "error": str(exc),
                    "final_answer": "", "steps": [],
                })
        threading.Thread(target=work, daemon=True).start()
    def cancel_agent_task(self):
        if self._agent_token is not None:
            self._agent_token.cancel()
            self._release_confirmations()
            self.agent_status_label.setText("Agent: Cancelling…")
    def _agent_progress(self, event):
        status = str(event.get("status") or "")
        label = AGENT_STATUS_LABELS.get(status, status.replace("_", " ").capitalize())
        detail = str(event.get("detail") or "").strip()
        self.agent_status_label.setText(f"Agent: {label}" + (f" — {detail}" if detail else ""))
        self._set_avatar_state(AGENT_STATUS_AVATARS.get(status, "Working"))
        self._render_task_plan(event.get("plan"), event.get("steps"))
        if detail:
            stamp = datetime.now().strftime("%H:%M:%S")
            self.activity_list.insertItem(0, f"{stamp}  agent  [{status}]\n{detail}")
            while self.activity_list.count() > 250:
                self.activity_list.takeItem(self.activity_list.count() - 1)
    def _render_task_plan(self, plan, steps):
        self.agent_plan.clear()
        plan_steps = None
        if isinstance(plan, dict):
            plan_steps = plan.get("steps")
        elif isinstance(plan, list):
            plan_steps = plan
        rows = plan_steps or steps or []
        for step in rows:
            if not isinstance(step, dict):
                continue
            verification = step.get("verification") or {}
            recovery = step.get("recovery") or {}
            check = (
                str(verification.get("detail") or "")
                or str(step.get("error") or "")
                or str(recovery.get("reason") or "")
                or str(step.get("expected") or "")
            )
            status = str(step.get("status") or "pending")
            objective = str(step.get("objective") or step.get("id") or "Step")
            tool = str(step.get("tool") or "")
            item = QTreeWidgetItem(
                [
                    objective[:160],
                    tool,
                    STEP_STATUS_LABELS.get(status, status),
                    check[:180],
                ]
            )
            item.setToolTip(0, objective)
            if tool:
                item.setToolTip(1, tool)
            if check:
                item.setToolTip(3, check)
            status_color = {
                "succeeded": self._colors["success"],
                "running": self._colors["accent"],
                "failed": self._colors["error"],
                "denied": self._colors["warning"],
                "invalid": self._colors["warning"],
                "skipped": self._colors["muted"],
            }.get(status)
            if status_color:
                item.setForeground(2, QColor(status_color))
            self.agent_plan.addTopLevelItem(item)
        if rows:
            self.agent_plan.resizeColumnToContents(0)
            self.agent_plan.resizeColumnToContents(1)
            self.agent_plan.resizeColumnToContents(2)
    def open_selected_task(self):
        item = self.task_history.currentItem()
        if item is None:
            self._status("Select a saved task first.")
            return
        record = db.load_task(item.data(Qt.UserRole))
        if not record:
            self._status("That task record could not be loaded.")
            return
        payload = record.get("payload") or {}
        status = str(payload.get("status") or record.get("status") or "unknown")
        self.agent_status_label.setText(
            f"Agent: {AGENT_STATUS_LABELS.get(status, status)} — saved task"
        )
        self._render_task_plan(payload.get("plan"), payload.get("steps"))
        self.agent_report.setPlainText(
            str(payload.get("report") or payload.get("error") or "No report was saved for this task.")
        )
    def refresh_tasks(self):
        self.task_history.clear()
        try:
            records = db.recent_tasks(limit=15)
        except Exception as exc:
            log.warning("Could not read recent tasks: %s", exc)
            return
        for record in records:
            when = datetime.fromtimestamp(record["updated"]).strftime("%m-%d %H:%M")
            item = QListWidgetItem(
                f"{when}  [{record['status']}]  {str(record['objective'])[:80]}"
            )
            item.setData(Qt.UserRole, record["id"])
            self.task_history.addItem(item)
    def _agent_done(self, state):
        self.agent_running = False
        self.busy = False
        self._agent_token = None
        self.agent_run_btn.setEnabled(True); self.agent_cancel_btn.setEnabled(False)
        status = str(state.get("status") or "failed")
        verified = state.get("verified", True)
        label = AGENT_STATUS_LABELS.get(status, status)
        if status == "completed" and not verified:
            label = "Completed, but some steps unverified"
        self.agent_status_label.setText(f"Agent: {label}")
        self._render_task_plan(state.get("plan"), state.get("steps"))
        report = state.get("final_answer") or state.get("error") or ""
        self.agent_report.setPlainText(str(report))
        if state.get("final_answer"):
            self._append_message("assistant", state["final_answer"])
            self._persist_message("assistant", state["final_answer"])
        if status == "completed" and not verified:
            self._append_message(
                "system",
                "This task finished, but at least one step was denied, invalid, or "
                "failed. Check the steps above before trusting the result.",
            )
        if status == "partially_completed":
            self._append_message(
                "system",
                "Only part of this task was completed. The remaining steps were "
                "not done; the report lists what failed and why.",
            )
        if status == "cancelled":
            self._append_message("system", "The task was cancelled before it finished.")
        if status == "failed" and state.get("error"):
            self._append_message("error", f"Agent error: {state['error']}")
        self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
        self._set_avatar_state(AGENT_STATUS_AVATARS.get(status, "Idle"))
        self.refresh_actions(); self.refresh_mem(); self.refresh_dashboard()
        self.refresh_tasks()
    def add_mem(self):
        text,ok=QInputDialog.getText(self,"Add memory","Memory:")
        if ok and text:
            if db.memory_is_sensitive(text):
                QMessageBox.warning(self,"Not saved","That looks like sensitive information, so it was not saved.")
                return
            db.add_memory(text); self.refresh_mem()
    def _selected_memory(self):
        item=self.mem_list.currentItem()
        if item is None:
            return None
        memory_id=item.data(Qt.UserRole)
        return next(
            (memory for memory in db.memories() if memory["id"]==memory_id),
            None,
        )
    def edit_mem(self):
        m=self._selected_memory()
        if m is None:
            return
        text,ok=QInputDialog.getText(self,"Edit memory","Memory:",text=m["text"])
        if ok and text:
            if db.memory_is_sensitive(text):
                QMessageBox.warning(self,"Not saved","That looks like sensitive information, so it was not changed.")
                return
            db.update_memory(m["id"],text); self.refresh_mem()
    def del_mem(self):
        m=self._selected_memory()
        if m is None:
            return
        db.delete_memory(m["id"]); self.refresh_mem()
    def check_memory_conflicts(self):
        try:
            conflicts=MemoryManager().conflicts()
        except Exception as exc:
            log.warning("Memory conflict check failed: %s", exc)
            self._status(f"Could not check memories: {exc}")
            return
        if not conflicts:
            QMessageBox.information(
                self,"Memory check",
                "No likely contradictions were found in your saved memories.",
            )
            return
        lines=[
            f"• {item['first'][:140]}\n  ↔ {item['second'][:140]}"
            for item in conflicts[:8]
        ]
        QMessageBox.warning(
            self,"Possible memory contradictions",
            "These saved memories may disagree:\n\n"
            + "\n\n".join(lines)
            + "\n\nReview the Memory list and edit or delete the outdated entry. "
              "Nothing was changed automatically.",
        )
    # ---- settings persistence ----------------------------------------
    def _connect_settings_autosave(self):
        for box in (
            self.cb_store,self.cb_auto_memory,self.cb_memory_enabled,
            self.cb_apps,self.cb_web,self.cb_research,
            self.cb_screen,self.cb_screen_control,
            self.cb_active_window,self.cb_media,self.cb_browser,
            self.cb_watch_mode,self.cb_diagnostics,self.cb_vscode_state,
            self.cb_run_tests,self.cb_write,self.cb_vision,
            self.cb_preload,self.cb_deep_reasoning,
            self.cb_always_on_top,self.cb_minimize_to_tray,
            self.cb_weather_auto,self.cb_auto_escalate,
        ):
            box.toggled.connect(self._schedule_settings_save)
        for box in (
            self.mic_box,self.out_box,self.lang_box,self.voice_box,
            self.chat_engine_box,self.screen_area,
            self.weather_units,self.reasoning_profile,
        ):
            box.currentIndexChanged.connect(self._schedule_settings_save)
        for widget in (
            self.vol,self.sensitivity,self.reply_wait,
            self.reasoning_rounds,self.calendar_duration,
            self.watch_interval,self.watch_cap,
        ):
            widget.valueChanged.connect(self._schedule_settings_save)
        for listing in (self.allowed_folders,self.development_workspaces):
            listing.model().rowsInserted.connect(self._schedule_settings_save)
            listing.model().rowsRemoved.connect(self._schedule_settings_save)
        for field in (
            self.embedding_model,self.wake_word_field,self.ollama_host,
            self.spotify_client_id,self.spotify_secret,self.weather_city,
        ):
            field.editingFinished.connect(self._save_text_settings)
        for combo in (self.model_box,self.vision_model_box):
            combo.currentTextChanged.connect(self._save_text_settings)
        for button in (self.hotkey,self.screen_hotkey):
            button.captureStarted.connect(self._suspend_hotkeys)
            button.captureFinished.connect(self._resume_hotkeys)
            button.chordChanged.connect(self._apply_hotkey_change)
    def _schedule_settings_save(self,*_args):
        self._settings_save_timer.start()
    def _autosave_settings(self):
        self._save_settings(interactive=False)
    def _save_text_settings(self,*_args):
        self._save_settings(interactive=False, include_text=True)
    def _settings_updates(self,*,text_fields=True):
        updates = {
            "privacy": {
                "store_conversations": self.cb_store.isChecked(),
                "auto_memory": self.cb_auto_memory.isChecked(),
                "memory_enabled": self.cb_memory_enabled.isChecked(),
            },
            "permissions": {
                "allow_open_app": self.cb_apps.isChecked(),
                "allow_open_url": self.cb_web.isChecked(),
                "allow_web_research": self.cb_research.isChecked(),
                "allow_screen_capture": self.cb_screen.isChecked(),
                "allow_screen_control": self.cb_screen_control.isChecked(),
                "allow_active_window": self.cb_active_window.isChecked(),
                "allow_media_control": self.cb_media.isChecked(),
                "allow_browser_automation": self.cb_browser.isChecked(),
                "allow_watch_mode": self.cb_watch_mode.isChecked(),
                "allow_system_diagnostics": self.cb_diagnostics.isChecked(),
                "allow_vscode_state": self.cb_vscode_state.isChecked(),
                "allow_run_tests": self.cb_run_tests.isChecked(),
                "allow_run_command": False,
                "allow_write_file": self.cb_write.isChecked(),
                "allow_vision": self.cb_vision.isChecked(),
                "allowed_folders": [
                    self.allowed_folders.item(i).text()
                    for i in range(self.allowed_folders.count())
                ],
            },
            "development": {
                "workspaces": [
                    self.development_workspaces.item(i).text()
                    for i in range(self.development_workspaces.count())
                ],
            },
            "ollama": {
                "stream_timeout_seconds": self.reply_wait.value(),
                "preload_model": self.cb_preload.isChecked(),
                "deep_reasoning": self.cb_deep_reasoning.isChecked(),
            },
            "ui": {
                "chat_engine": self.chat_engine_box.currentData() or "web",
                "always_on_top": self.cb_always_on_top.isChecked(),
                "minimize_to_tray": self.cb_minimize_to_tray.isChecked(),
            },
            "voice": {
                "volume": self.vol.value()/100,
                "speak_replies": bool(self.voice_btn.isChecked()),
                "microphone_device": self.mic_box.currentData(),
                "output_device": self.out_box.currentData(),
                "wake_word_enabled": self.cb_wake.isChecked(),
                "sensitivity": max(0.1, min(1.0, self.sensitivity.value()/100)),
                "recognition_language": self._recognition_language(),
                "language": self._recognition_language(),
            },
            "screen": {
                "monitor": str(self.screen_area.currentData() or "primary"),
                "region": getattr(self, "_screen_region", None),
                "watch_interval_seconds": self.watch_interval.value(),
                "watch_max_minutes": self.watch_cap.value(),
            },
            "location": {
                "units": self.weather_units.currentData() or "metric",
                "auto_detect": self.cb_weather_auto.isChecked(),
            },
            "reasoning": {
                "profile": self.reasoning_profile.currentData() or "auto",
                "auto_escalate": self.cb_auto_escalate.isChecked(),
                "max_rounds": self.reasoning_rounds.value(),
            },
            "calendar": {
                "default_duration_minutes": self.calendar_duration.value(),
            },
        }
        if self.voice_box.count():
            updates["voice"]["tts_voice"] = self.voice_box.currentText()
        if not text_fields:
            return updates
        updates["location"]["city"] = self.weather_city.text().strip()
        updates["spotify"] = {
            "client_id": self.spotify_client_id.text().strip(),
            "client_secret": self.spotify_secret.text().strip(),
        }
        updates["ollama"]["vision_model"] = (
            self.vision_model_box.currentText().strip() or "qwen2.5vl:3b"
        )
        updates["memory"] = {
            "embedding_model": self.embedding_model.text().strip(),
        }
        updates["voice"]["push_to_talk_key"] = _chord_value(self.hotkey, "f9")
        updates["voice"]["wake_word"] = self.wake_word_field.text().strip() or "Himari"
        updates["screen"]["capture_hotkey"] = _chord_value(
            self.screen_hotkey, "f10"
        )
        host = self.ollama_host.text().strip()
        if host.startswith(("http://", "https://")):
            updates["ollama"]["host"] = host
        model = self.model_box.currentText().strip()
        if model:
            updates["ollama"]["chat_model"] = model
        return updates
    def _save_settings(self,*,interactive=False,include_text=None):
        if include_text is None:
            include_text = bool(interactive)
        try:
            updates = self._settings_updates(text_fields=include_text)
        except RuntimeError as exc:
            # Widgets are torn down one by one at shutdown; a pending
            # editingFinished save can then read an already-deleted sibling.
            log.debug("Settings save skipped during teardown: %s", exc)
            return False
        try:
            control_settings.SettingsService().update(updates)
        except control_settings.SettingsError as exc:
            log.warning("Settings were not saved: %s", exc)
            if interactive:
                QMessageBox.warning(
                    self, "Settings not saved",
                    f"Himari kept the previous settings because a value was invalid:\n{exc}",
                )
            elif not getattr(self, "_settings_save_warned", False):
                self._settings_save_warned = True
                self._status("A setting change could not be saved automatically.")
            return False
        self._settings_save_warned = False
        return True
    def _suspend_hotkeys(self):
        self._remove_hotkeys()
    def _resume_hotkeys(self):
        self._bind_hotkeys()
    def _apply_hotkey_change(self,*_args):
        ptt = _chord_value(self.hotkey, "f9")
        capture = _chord_value(self.screen_hotkey, "f10")
        if ptt != self.hotkey.currentChord():
            self.hotkey.setChord(ptt, emit=False)
        if capture != self.screen_hotkey.currentChord():
            self.screen_hotkey.setChord(capture, emit=False)
        if ptt.casefold() == capture.casefold():
            self._status("Push-to-talk and screen capture need different shortcuts.")
            self._bind_hotkeys()
            return
        try:
            control_settings.SettingsService().update({
                "voice": {"push_to_talk_key": ptt},
                "screen": {"capture_hotkey": capture},
            })
        except control_settings.SettingsError as exc:
            log.warning("Shortcuts were not saved: %s", exc)
            self._status(f"Shortcut not saved: {exc}")
            self._bind_hotkeys()
            return
        self._bind_hotkeys()
        self._update_shortcut_hint(ptt, capture)
        problems = [
            message for message in (self.hotkey_error, self.screen_hotkey_error)
            if message
        ]
        if problems:
            self._status(" ".join(problems))
        else:
            self._status(
                f"Shortcuts saved — {ptt.upper()} to talk, "
                f"{capture.upper()} to capture."
            )
    def _select_screen_region(self):
        if not self.cb_screen.isChecked():
            self._status("Enable screen capture before choosing a region.")
            return
        from .region_select import select_region

        region, error = select_region(None, self.theme_name)
        if error:
            self._status(error)
            return
        if region is None:
            self._status("Region selection cancelled.")
            return
        previous_region = self._screen_region
        previous_index = self.screen_area.currentIndex()
        self._screen_region = region
        region_index = self.screen_area.findData("region")
        if region_index >= 0:
            blocked = self.screen_area.blockSignals(True)
            self.screen_area.setCurrentIndex(region_index)
            self.screen_area.blockSignals(blocked)
        self._refresh_region_label()
        if not self._save_settings(interactive=False):
            self._screen_region = previous_region
            blocked = self.screen_area.blockSignals(True)
            self.screen_area.setCurrentIndex(previous_index)
            self.screen_area.blockSignals(blocked)
            self._refresh_region_label()
            return
        self._status(
            "Custom capture region saved — press the screen key to try it."
        )
    def _clear_screen_region(self):
        previous_region = self._screen_region
        previous_index = self.screen_area.currentIndex()
        self._screen_region = None
        if self.screen_area.currentData() == "region":
            primary_index = self.screen_area.findData("primary")
            blocked = self.screen_area.blockSignals(True)
            self.screen_area.setCurrentIndex(max(0, primary_index))
            self.screen_area.blockSignals(blocked)
        self._refresh_region_label()
        if not self._save_settings(interactive=False):
            self._screen_region = previous_region
            blocked = self.screen_area.blockSignals(True)
            self.screen_area.setCurrentIndex(previous_index)
            self.screen_area.blockSignals(blocked)
            self._refresh_region_label()
            return
        self._status("Custom region cleared — captures use the whole screen again.")
    def showEvent(self,event):
        super().showEvent(event)
        first_time = not getattr(self, "_window_shown_once", False)
        self._window_shown_once = True
        ui_effects.fade_window(self, first_time=first_time)
    def shutdown_web_engine(self):
        """Release QtWebEngine before the app exits.

        A live profile keeps QtWebEngineProcess.exe and its files in the
        PyInstaller temp folder, which makes the one-file bootloader report a
        failed _MEI cleanup. Tearing the view down first avoids that.
        """
        timer = getattr(self, "_settings_save_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        view = getattr(self, "chat", None)
        if view is None:
            return
        profile = getattr(view, "_profile", None)
        try:
            page = view.page()
            if page is not None:
                page.deleteLater()
        except (RuntimeError, AttributeError):
            pass
        try:
            view.setParent(None)
            view.deleteLater()
        except RuntimeError:
            pass
        self.chat = None
        if profile is not None:
            try:
                profile.deleteLater()
            except RuntimeError:
                pass
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
            time.sleep(0.25)
            app.processEvents()
    def closeEvent(self,e):
        self._release_confirmations()
        self._save_settings(interactive=True)
        self._cancel_event.set()
        self.tts.stop()
        if self.mic.rec: self.mic.stop()
        if self.tray is not None and self.cb_minimize_to_tray.isChecked() and not self._allow_quit:
            self._bind_hotkeys()
            self.hide();
            e.ignore();
            return
        self.wake_word_monitor.stop()
        if self.agent_running and self._agent_token is not None:
            self._agent_token.cancel()
        self._remove_hotkeys()
        if self.tray is not None:
            self.tray.hide()
        self.floating_avatar.hide()
        self._allow_quit = False
        from .browser.session import session as browser_session
        browser_session.shutdown()
        super().closeEvent(e)
def run():
    from .logging_setup import configure_logging

    configure_logging()
    app=QApplication(sys.argv)
    from .crash import install as install_crash_handlers

    install_crash_handlers(app)
    from .single_instance import SingleInstance

    guard=SingleInstance(app)
    if not guard.acquire():
        log.info("Himari is already running; asked the existing window to show.")
        return
    w=UI()
    guard.activated.connect(lambda:(w.show(),w.raise_(),w.activateWindow()))
    w.show()
    code=app.exec()
    try:
        w.shutdown_web_engine()
        import gc
        gc.collect()
        app.processEvents()
    except Exception as exc:
        log.debug("Web engine shutdown cleanup failed: %s", exc)
    sys.exit(code)
