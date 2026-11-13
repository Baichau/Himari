import sys, threading, logging, time, io
from datetime import datetime
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QTextEdit,
 QLineEdit,QPushButton,QLabel,QListWidget,QListWidgetItem,QCheckBox,QComboBox,QSlider,QTabWidget,
 QInputDialog,QFileDialog,QMessageBox,QSystemTrayIcon,QMenu,QScrollArea,QFrame,QSizePolicy,
 QSpinBox)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QDesktopServices
from .config import load, save
from .paths import user_data_dir
from . import db, persona, chat_web, theme, ui_effects, ui_settings
from .agent import AgentOrchestrator, CancellationToken
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
log=logging.getLogger("himari.ui")


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
        self._first_token_seen=True
        self._wait_started=0.0
        self._waiting_label="Waiting for Ollama…"
        self.security=SecurityLayer(confirm_callback=self._confirm_security_action)
        self.llm=LLM(TOOLS, security=self.security)
        self.tts=TTS(
            on_error=lambda message:self.status.emit(f"TTS error: {message}"),
            on_finished=lambda:self.status.emit("Ready."),
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
        self.agent_status.connect(self._agent_progress)
        self.agent_finished.connect(self._agent_done)
        self.tabs=ui_effects.AnimatedTabWidget(); tabs=self.tabs; self.setCentralWidget(tabs)
        # Chat tab
        chat=QWidget(); root=QHBoxLayout(chat)
        root.setContentsMargins(14,14,14,14); root.setSpacing(14)

        sidebar=QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(238)
        side=QVBoxLayout(sidebar); side.setContentsMargins(12,12,12,12); side.setSpacing(8)
        side_brand=QLabel("Himari"); side_brand.setObjectName("AppTitle")
        side_caption=QLabel("Local chats"); side_caption.setObjectName("MutedLine")
        self.new_chat_btn=QPushButton("+ New chat"); self.new_chat_btn.setObjectName("PrimaryButton")
        self.new_chat_btn.clicked.connect(self.new_chat)
        side_title=QLabel("RECENT"); side_title.setObjectName("SidebarTitle")
        self.session_list=QListWidget(); self.session_list.setObjectName("SessionList")
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._session_menu)
        self.session_list.itemClicked.connect(self._session_changed)
        self.session_list.itemActivated.connect(self._session_changed)
        side.addWidget(side_brand); side.addWidget(side_caption)
        side.addWidget(self.new_chat_btn); side.addSpacing(4)
        side.addWidget(side_title); side.addWidget(self.session_list, 1)
        side_hint=QLabel("Right-click a chat to delete it")
        side_hint.setObjectName("MutedLine"); side_hint.setWordWrap(True)
        side.addWidget(side_hint)
        side_privacy=QLabel("Private · stored only on this PC")
        side_privacy.setObjectName("MutedLine"); side_privacy.setWordWrap(True)
        side.addWidget(side_privacy)
        root.addWidget(sidebar)

        main=QVBoxLayout(); main.setSpacing(10)
        header_card=QFrame(); header_card.setObjectName("HeaderCard")
        header=QHBoxLayout(header_card); header.setContentsMargins(14,12,14,12); header.setSpacing(16)
        self.avatar=AvatarWidget(self); self.avatar.setFixedSize(104,168)
        self.avatar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.avatar.clicked.connect(self.toggle_floating_avatar)
        title=QVBoxLayout(); title.setSpacing(4)
        name=QLabel("Himari ひまり"); name.setObjectName("AppTitle")
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tagline=QLabel("Warm, local companion — nothing leaves your PC")
        tagline.setObjectName("Tagline")
        tagline.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.avatar_state = QLabel("● Idle"); self.avatar_state.setObjectName("StatusChip")
        self.avatar_state.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        title.addWidget(name); title.addWidget(tagline); title.addWidget(self.avatar_state)
        title.addStretch()
        header.addWidget(
            self.avatar, 0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        header.addLayout(title, 1)
        actions_widget=QWidget()
        actions_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        header_actions=QVBoxLayout(actions_widget)
        header_actions.setContentsMargins(0,0,0,0); header_actions.setSpacing(6)
        self.voice_btn=QPushButton(); self.voice_btn.setCheckable(True)
        self.voice_btn.setChecked(self._voice_replies())
        self.voice_btn.setToolTip("Speak replies aloud using the local Piper voice")
        self.voice_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.voice_btn.toggled.connect(self._toggle_voice_replies)
        self._update_voice_button(self.voice_btn.isChecked())
        self.floating_avatar_btn=QPushButton("Float avatar")
        self.floating_avatar_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.floating_avatar_btn.clicked.connect(self.toggle_floating_avatar)
        header_actions.addWidget(self.voice_btn)
        header_actions.addWidget(self.floating_avatar_btn)
        header_actions.addStretch()
        header.addWidget(
            actions_widget, 0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        main.addWidget(header_card)

        toolbar=QHBoxLayout(); toolbar.setSpacing(8)
        self.mic_btn=QPushButton(self._talk_label()); self.mic_btn.clicked.connect(self.toggle_mic)
        self.stop_btn=QPushButton("Stop voice"); self.stop_btn.clicked.connect(self.tts.stop)
        screen_key = str(load().get("screen", {}).get("capture_hotkey", "f10") or "").upper()
        self.analyze_btn=QPushButton(f"Screen ({screen_key})" if screen_key else "Screen")
        self.analyze_btn.clicked.connect(self.screen_query)
        self.show_tools_btn=QPushButton("Tools"); self.show_tools_btn.setCheckable(True)
        self.show_tools_btn.setToolTip("Show tool calls in the transcript")
        self.show_tools_btn.toggled.connect(lambda _: self._render_chat(force_scroll=True))
        self.save_memory_btn=QPushButton("Save memory")
        self.save_memory_btn.setToolTip("Save selected chat text (or a new note) as a long-term memory")
        self.save_memory_btn.clicked.connect(self.save_chat_memory)
        self.clear_btn=QPushButton("Delete chat")
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

        self.status_label=QLabel("Starting…"); self.status_label.setObjectName("StatusLine")
        self.wake_word_status.setObjectName("MutedLine")
        main.addWidget(self.status_label); main.addWidget(self.wake_word_status)

        self.attachments_widget=QWidget()
        self.attachments_row=QHBoxLayout(self.attachments_widget)
        self.attachments_row.setContentsMargins(0,0,0,0); self.attachments_row.setSpacing(6)
        self.attachments_widget.setVisible(False)
        main.addWidget(self.attachments_widget)

        row2=QHBoxLayout(); row2.setSpacing(8)
        self.attach_btn=QPushButton("Attach")
        self.attach_btn.setToolTip(
            "Attach images, PDF, Word, spreadsheet, or text/code files. "
            "Files stay local and are read only for this message."
        )
        self.attach_btn.clicked.connect(self.attach_files)
        self.input=QLineEdit(); self.input.setPlaceholderText("Message Himari…  (Enter to send)")
        self.input.returnPressed.connect(self.send)
        self.send_btn=QPushButton("Send"); self.send_btn.setObjectName("PrimaryButton")
        self.send_btn.clicked.connect(self.send)
        self.stop_generation_btn=QPushButton("Stop"); self.stop_generation_btn.setObjectName("StopButton")
        self.stop_generation_btn.clicked.connect(self.stop_generation)
        self.stop_generation_btn.setVisible(False)
        self.retry_btn=QPushButton("Retry")
        self.retry_btn.setToolTip("Send the last message again without adding a duplicate")
        self.retry_btn.clicked.connect(self.retry_last)
        self.retry_btn.setVisible(False)
        row2.addWidget(self.attach_btn)
        row2.addWidget(self.input, 1); row2.addWidget(self.retry_btn)
        row2.addWidget(self.send_btn)
        row2.addWidget(self.stop_generation_btn)
        main.addLayout(row2)
        self.shortcut_hint=QLabel("")
        self.shortcut_hint.setObjectName("MutedLine")
        main.addWidget(self.shortcut_hint)
        self.input.textChanged.connect(self._refresh_send_button)
        self._refresh_send_button()
        root.addLayout(main, 1)
        tabs.addTab(chat,"Chat")
        # Dashboard tab
        dash=QWidget(); dv=QVBoxLayout(dash)
        dash_row=QHBoxLayout()
        refresh_dash=QPushButton("Refresh dashboard")
        refresh_dash.clicked.connect(self.refresh_dashboard)
        dash_row.addWidget(refresh_dash); dash_row.addStretch()
        dv.addLayout(dash_row)
        self.dashboard_text=QTextEdit(); self.dashboard_text.setReadOnly(True)
        self.dashboard_text.setPlainText("Dashboard not loaded yet. Press Refresh dashboard.")
        dv.addWidget(self.dashboard_text, 2)
        self.dash_activity=QListWidget(); dv.addWidget(QLabel("Recent activity:")); dv.addWidget(self.dash_activity, 1)
        task_row=QHBoxLayout()
        self.agent_input=QLineEdit()
        self.agent_input.setPlaceholderText("Describe a task for Himari to work on…")
        self.agent_input.returnPressed.connect(self.run_agent_task)
        self.agent_run_btn=QPushButton("Run task"); self.agent_run_btn.clicked.connect(self.run_agent_task)
        self.agent_cancel_btn=QPushButton("Cancel task"); self.agent_cancel_btn.clicked.connect(self.cancel_agent_task)
        self.agent_cancel_btn.setEnabled(False)
        task_row.addWidget(self.agent_input); task_row.addWidget(self.agent_run_btn); task_row.addWidget(self.agent_cancel_btn)
        dv.addLayout(task_row)
        self.agent_status_label=QLabel("Agent: idle"); dv.addWidget(self.agent_status_label)
        tabs.addTab(dash,"Dashboard")
        activity_tab=QWidget(); activity_layout=QVBoxLayout(activity_tab)
        self.activity_list=QListWidget(); activity_layout.addWidget(self.activity_list)
        tabs.addTab(activity_tab,"Activity")
        # Memory tab
        mem=QWidget(); mv=QVBoxLayout(mem)
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
        mv.addLayout(search_row)
        self.mem_list=QListWidget(); mv.addWidget(self.mem_list)
        mrow=QHBoxLayout()
        add=QPushButton("Add"); add.clicked.connect(self.add_mem)
        edit=QPushButton("Edit"); edit.clicked.connect(self.edit_mem)
        dele=QPushButton("Delete"); dele.clicked.connect(self.del_mem)
        conflicts=QPushButton("Check contradictions")
        conflicts.setToolTip(
            "Look for saved memories that appear to disagree. Nothing is changed automatically."
        )
        conflicts.clicked.connect(self.check_memory_conflicts)
        for b in [add,edit,dele,conflicts]: mrow.addWidget(b)
        mv.addLayout(mrow)
        mv.addWidget(QLabel("Memory suggestions (review before saving):"))
        self.suggestion_list=QListWidget(); mv.addWidget(self.suggestion_list)
        suggestion_row=QHBoxLayout()
        approve=QPushButton("Approve suggestion")
        approve.clicked.connect(self.approve_memory_suggestion)
        reject=QPushButton("Reject suggestion")
        reject.clicked.connect(self.reject_memory_suggestion)
        suggestion_row.addWidget(approve); suggestion_row.addWidget(reject)
        mv.addLayout(suggestion_row); self.memory_tab_index=tabs.addTab(mem,"Memory")
        # Settings tab
        settings_scroll=ui_settings.build_settings_page(self)
        self.settings_tab_index=tabs.addTab(settings_scroll,"Settings")
        diag=QWidget(); dv2=QVBoxLayout(diag)
        self.diag_btn=QPushButton("Run diagnostics"); self.diag_btn.clicked.connect(self.run_diagnostics)
        self.diag_text=QTextEdit(); self.diag_text.setReadOnly(True)
        self.diag_text.setPlainText("Run diagnostics to check local dependencies, Ollama, the database, and permissions.")
        dv2.addWidget(self.diag_btn); dv2.addWidget(self.diag_text)
        tabs.addTab(diag,"Diagnostics")
        self._restore_last_session()
        self.refresh_mem()
        self.refresh_actions()
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
        if total < 48 or total - self._summary_at < 24:
            return
        self._summary_at = total
        self._summary_running = True
        session = self.session

        def work():
            try:
                summarize_older(session, keep_recent=32)
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
        avatar_state = {
            "Listening": "listening",
            "Thinking": "thinking",
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
            self.floating_avatar_btn.setText("Floating avatar")
        else:
            self.floating_avatar.show()
            self.floating_avatar_btn.setText("Hide avatar")
    def _status(self,s):
        self.status_label.setText(s)
        if "error" in s.lower() or "failed" in s.lower():
            self._set_avatar_state("Error")
        elif "listening" in s.lower():
            self._set_avatar_state("Listening")
        elif (
            "generating" in s.lower()
            or "responding" in s.lower()
            or "thinking" in s.lower()
            or "checking" in s.lower()
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
    def _speak(self,t):
        if not self._voice_replies():
            self._status("Ready.")
            return
        try:
            if t.strip():
                self.status.emit("Speaking… click Stop voice to interrupt.")
                self.tts.speak(t)
            else:
                self._status("Ready.")
        except Exception as e: self._status(f"TTS unavailable: {e}")
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
                if db.suggest_memory(text):
                    self.refresh_mem()
            except Exception as exc:
                log.exception("Could not save a memory suggestion")
                self.status.emit(f"Memory suggestion error: {exc}")
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
            think = deep_reasoning and (
                needs_research or bool(image_atts) or persona.should_think(text)
            )
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
            relevant = db.relevant_memories(text, limit=8)
            if MemoryManager().enabled():
                try:
                    relevant = [
                        {"text": memory.text}
                        for memory in retrieve_memories(text, limit=8)
                    ] or relevant
                except Exception as exc:
                    log.warning("Memory retrieval failed: %s", exc)
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
                directive=persona.diagram_directive(text),
            )
        except Exception as exc:
            log.exception("Chat preparation failed")
            self.failed.emit(f"Chat preparation failed: {exc}")
            return
        if cancel_event.is_set():
            self.cancelled.emit("")
            return
        self._run(msgs, cancel_event, think=think)
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
    def _run(self,msgs,cancel_event=None,think=False):
        out=[]
        def on_token(t): out.append(t); self.token.emit(t)
        try:
            self.llm.stream_chat(
                msgs,
                on_token,
                on_tool=lambda n,a,r: self.tool.emit(f"{n} {a} → {r}"),
                cancel_event=cancel_event,
                on_status=self.status.emit,
                think=think,
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
            self._status("Voice detected; transcribing locally…")
            threading.Thread(
                target=self._transcribe,
                args=(audio, self._recognition_language()),
                daemon=True,
            ).start()

    def toggle_mic(self):
        if self.mic.rec:
            audio=self.mic.stop(); self.mic_btn.setText(self._talk_label())
            self._status("Transcribing locally…")
            threading.Thread(
                target=self._transcribe,
                args=(audio, self._recognition_language()),
                daemon=True,
            ).start()
        else:
            try:
                self.tts.stop()
                self.mic.start(on_silence=None)
                self.mic_btn.setText("Stop & Transcribe")
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
            self.activity_list.addItem(
                f"{timestamp}  {action['tool']}  allowed={bool(action['approved'])}\n{action['result']}")
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
            self.dash_activity.addItem(
                f"{row['display_time']}  {row['tool']}  [{status}]\n{row['result'][:200]}"
            )
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
        self.agent_status_label.setText("Agent: planning")
        self.status_label.setText("Working on the task…")
        self._set_avatar_state("Working")
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
            self.agent_status_label.setText("Agent: cancelling…")
    def _agent_progress(self, event):
        self.agent_status_label.setText(f"Agent: {event['status']} — {event['detail']}")
        if event["status"] in (
            "understanding", "planning", "waiting_for_permission",
            "executing", "observing", "verifying",
        ):
            self._set_avatar_state("Working")
    def _agent_done(self, state):
        self.agent_running = False
        self.busy = False
        self._agent_token = None
        self.agent_run_btn.setEnabled(True); self.agent_cancel_btn.setEnabled(False)
        status = state.get("status", "failed")
        verified = state.get("verified", True)
        if status == "completed" and not verified:
            self.agent_status_label.setText("Agent: completed (some steps unverified)")
        else:
            self.agent_status_label.setText(f"Agent: {status}")
        if state.get("final_answer"):
            self._append_message("assistant", state["final_answer"])
            self._persist_message("assistant", state["final_answer"])
        if status == "completed" and not verified:
            self._append_message(
                "system",
                "This task finished, but at least one step was denied, invalid, or "
                "failed. Check the steps above before trusting the result.",
            )
        if status == "failed" and state.get("error"):
            self._append_message("error", f"Agent error: {state['error']}")
        self._render_chat(force_scroll=True)
        self._load_sessions(select=self.session)
        self._set_avatar_state("Error" if status == "failed" else "Idle")
        self.refresh_actions(); self.refresh_mem(); self.refresh_dashboard()
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
            self.cb_write,self.cb_vision,
            self.cb_preload,self.cb_deep_reasoning,
            self.cb_always_on_top,self.cb_minimize_to_tray,
        ):
            box.toggled.connect(self._schedule_settings_save)
        for box in (
            self.mic_box,self.out_box,self.lang_box,self.voice_box,
            self.chat_engine_box,self.screen_area,
        ):
            box.currentIndexChanged.connect(self._schedule_settings_save)
        for widget in (self.vol,self.sensitivity,self.reply_wait):
            widget.valueChanged.connect(self._schedule_settings_save)
        for listing in (self.allowed_folders,self.development_workspaces):
            listing.model().rowsInserted.connect(self._schedule_settings_save)
            listing.model().rowsRemoved.connect(self._schedule_settings_save)
        for field in (self.embedding_model,self.wake_word_field,self.ollama_host):
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
            },
        }
        if self.voice_box.count():
            updates["voice"]["tts_voice"] = self.voice_box.currentText()
        if not text_fields:
            return updates
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
            control_settings.SettingsService().update(
                self._settings_updates(text_fields=include_text)
            )
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
    sys.exit(app.exec())
