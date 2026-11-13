"""Build the Settings tab.

Grouping lives here so the main window stays a chat shell instead of a second
settings application. Every control is attached to the window with the same
attribute names the persistence code already uses.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import load
from .region_select import describe_region
from .ui_effects import CollapsibleSection
from .ui_widgets import KeyCaptureButton

log = logging.getLogger("himari.ui_settings")

SCREEN_AREAS = (
    ("Primary screen", "primary"),
    ("Custom region", "region"),
    ("Active window", "active"),
    ("All screens", "all"),
)


def _hint(text):
    label = QLabel(str(text))
    label.setObjectName("SectionHint")
    label.setWordWrap(True)
    return label


def _row(*widgets):
    row = QHBoxLayout()
    row.setSpacing(8)
    for widget in widgets:
        if widget is None:
            row.addStretch()
        else:
            row.addWidget(widget)
    return row


def _section(layout, title, expanded=True):
    section = CollapsibleSection(title, expanded=expanded)
    layout.addWidget(section)
    return section


def _device_box(kind, selected):
    box = QComboBox()
    box.addItem("System default", None)
    try:
        import sounddevice as sd

        for index, device in enumerate(sd.query_devices()):
            channels = device.get(
                "max_input_channels" if kind == "input" else "max_output_channels",
                0,
            )
            if channels > 0:
                box.addItem(f"{index}: {device['name']}", index)
                if index == selected:
                    box.setCurrentIndex(box.count() - 1)
    except Exception as exc:
        log.warning("%s device list unavailable: %s", kind.title(), exc)
    return box


def _build_voice(ui, cfg, section):
    voice = cfg.get("voice", {}) or {}
    section.addHint(
        "Pick the microphone and voice Himari should use, and choose the keys "
        "you want to press for talking or capturing the screen."
    )

    ui.mic_box = _device_box("input", voice.get("microphone_device"))
    ui.out_box = _device_box("output", voice.get("output_device"))
    section.addWidget(QLabel("Microphone:"))
    section.addWidget(ui.mic_box)
    section.addWidget(QLabel("Speaker (Himari's voice):"))
    section.addWidget(ui.out_box)

    ui.lang_box = QComboBox()
    ui.lang_box.addItem("Automatic", "auto")
    ui.lang_box.addItem("English", "en")
    ui.lang_box.addItem("Russian", "ru")
    current_lang = (
        voice.get("recognition_language") or voice.get("language") or "en"
    ).lower()
    language_code = (
        "ru" if current_lang.startswith("ru")
        else "en" if current_lang.startswith("en")
        else "auto"
    )
    ui.lang_box.setCurrentIndex(ui.lang_box.findData(language_code))
    section.addWidget(QLabel("Recognition language:"))
    section.addWidget(ui.lang_box)

    ui.voice_box = QComboBox()
    available_voices = []
    try:
        from .voice import TTS

        available_voices = TTS().available_voices()
    except Exception as exc:
        log.warning("Voice list unavailable: %s", exc)
    configured_voice = voice.get("tts_voice")
    if configured_voice == "en_US-lessac-medium" and "en_US-amy-medium" in available_voices:
        configured_voice = "en_US-amy-medium"
    ui.voice_box.addItems(
        available_voices or [configured_voice or "en_US-amy-medium"]
    )
    if configured_voice in [
        ui.voice_box.itemText(index) for index in range(ui.voice_box.count())
    ]:
        ui.voice_box.setCurrentText(configured_voice)
    section.addWidget(QLabel("Voice (English default; Russian falls back to Windows):"))
    section.addWidget(ui.voice_box)

    ui.vol = QSlider(Qt.Orientation.Horizontal)
    ui.vol.setRange(0, 100)
    ui.vol.setValue(int(float(voice.get("volume", 1.0)) * 100))
    section.addWidget(QLabel("Voice volume:"))
    section.addWidget(ui.vol)

    ui.hotkey = KeyCaptureButton(voice.get("push_to_talk_key") or "f9")
    section.addWidget(QLabel("Push-to-talk key:"))
    section.addWidget(ui.hotkey)
    section.addHint(
        "Click the button and press the shortcut. It applies immediately and "
        "works even while Himari is in the background."
    )

    ui.cb_wake = QCheckBox("Enable wake-word listening (Himari)")
    ui.cb_wake.setChecked(bool(voice.get("wake_word_enabled", False)))
    ui.cb_wake.toggled.connect(ui._toggle_wake_word)
    section.addWidget(ui.cb_wake)

    ui.wake_word_field = QLineEdit(voice.get("wake_word", "Himari"))
    section.addWidget(QLabel("Wake word:"))
    section.addWidget(ui.wake_word_field)

    ui.sensitivity = QSlider(Qt.Orientation.Horizontal)
    ui.sensitivity.setRange(10, 100)
    ui.sensitivity.setValue(int(float(voice.get("sensitivity", 0.75)) * 100))
    ui.sensitivity.setToolTip(
        "Higher values pick up quieter speech; lower values ignore more room noise."
    )
    section.addWidget(QLabel("Microphone sensitivity (higher hears quieter speech):"))
    section.addWidget(ui.sensitivity)
    return ui.hotkey


def _build_screen(ui, cfg, section):
    screen = cfg.get("screen", {}) or {}
    permissions = cfg.get("permissions", {}) or {}
    section.addHint(
        "Screen captures happen once, only after you confirm, and are never "
        "saved to disk. Choose what Himari should see when you press the key."
    )

    ui.cb_screen = QCheckBox(
        "Allow one-time screen capture (asks for confirmation each time)"
    )
    ui.cb_screen.setChecked(bool(permissions.get("allow_screen_capture", True)))
    section.addWidget(ui.cb_screen)

    ui.screen_area = QComboBox()
    for label, value in SCREEN_AREAS:
        ui.screen_area.addItem(label, value)
    configured_area = str(screen.get("monitor") or "primary").casefold()
    area_index = ui.screen_area.findData(configured_area)
    ui.screen_area.setCurrentIndex(max(0, area_index))
    section.addWidget(QLabel("Capture area:"))
    section.addWidget(ui.screen_area)

    ui._screen_region = screen.get("region")
    ui.region_label = QLabel(describe_region(ui._screen_region))
    ui.region_label.setObjectName("SectionHint")
    ui.region_label.setWordWrap(True)
    ui.region_select_btn = QPushButton("Select region…")
    ui.region_select_btn.setToolTip(
        "Choose a rectangle on the primary screen. This also switches the "
        "capture area to Custom region."
    )
    ui.region_clear_btn = QPushButton("Clear region")
    ui.region_clear_btn.setToolTip("Go back to capturing the whole screen.")
    section.addWidget(ui.region_label)
    section.addLayout(_row(ui.region_select_btn, ui.region_clear_btn, None))
    ui.region_select_btn.clicked.connect(ui._select_screen_region)
    ui.region_clear_btn.clicked.connect(ui._clear_screen_region)

    def refresh_region_label():
        ui.region_label.setText(describe_region(ui._screen_region))
        ui.region_clear_btn.setEnabled(bool(ui._screen_region))
        ui.region_select_btn.setEnabled(ui.cb_screen.isChecked())

    ui._refresh_region_label = refresh_region_label
    ui.cb_screen.toggled.connect(lambda _checked: refresh_region_label())
    refresh_region_label()

    ui.screen_hotkey = KeyCaptureButton(screen.get("capture_hotkey") or "f10")
    section.addWidget(QLabel("Global screen-capture key:"))
    section.addWidget(ui.screen_hotkey)

    ui.cb_active_window = QCheckBox("Allow requested active-window capture")
    ui.cb_active_window.setChecked(
        bool(permissions.get("allow_active_window", False))
    )
    ui.cb_active_window.setToolTip(
        "Needed only when the capture area is set to Active window."
    )
    section.addWidget(ui.cb_active_window)

    ui.cb_screen_control = QCheckBox(
        "Allow screen control (click, type and press keys in open apps)"
    )
    ui.cb_screen_control.setChecked(
        bool(permissions.get("allow_screen_control", False))
    )
    ui.cb_screen_control.setToolTip(
        "Lets Himari list the controls of an open window, click a named control, "
        "type text, and send key presses through Windows UI Automation. Every "
        "input action asks for confirmation first, and the Windows key is never "
        "sent. Disabled by default."
    )
    section.addWidget(ui.cb_screen_control)
    return ui.screen_hotkey


def _build_privacy(ui, cfg, section):
    privacy = cfg.get("privacy", {}) or {}
    section.addHint(
        "Everything is stored in a local SQLite file. Nothing is uploaded to a "
        "cloud service."
    )
    ui.cb_store = QCheckBox("Store conversations locally")
    ui.cb_store.setChecked(bool(privacy.get("store_conversations", True)))
    ui.cb_auto_memory = QCheckBox(
        "Create pending memory suggestions on explicit requests"
    )
    ui.cb_auto_memory.setChecked(bool(privacy.get("auto_memory", True)))
    ui.cb_memory_enabled = QCheckBox("Enable long-term memory")
    ui.cb_memory_enabled.setChecked(bool(privacy.get("memory_enabled", True)))
    section.addWidget(ui.cb_store)
    section.addWidget(ui.cb_auto_memory)
    section.addWidget(ui.cb_memory_enabled)

    ui.embedding_model = QLineEdit(
        (cfg.get("memory", {}) or {}).get("embedding_model", "")
    )
    ui.embedding_model.setPlaceholderText(
        "e.g. nomic-embed-text (leave empty for keyword search)"
    )
    ui.embedding_model.setToolTip(
        "Optional. An embedding model already installed in local Ollama enables "
        "semantic memory search alongside keyword matching. Himari never "
        "downloads a model. Changes apply to the next reply."
    )
    section.addWidget(QLabel("Memory embedding model (optional, local Ollama):"))
    section.addWidget(ui.embedding_model)


def _build_permissions(ui, cfg, section):
    permissions = cfg.get("permissions", {}) or {}
    section.addHint(
        "Himari only uses a capability you enable here, and it still asks before "
        "doing something that changes your PC."
    )

    ui.cb_apps = QCheckBox("Allow opening apps and Steam games")
    ui.cb_apps.setChecked(bool(permissions.get("allow_open_app", True)))
    ui.cb_web = QCheckBox("Allow opening websites")
    ui.cb_web.setChecked(bool(permissions.get("allow_open_url", True)))
    ui.cb_research = QCheckBox("Automatically check the web for factual questions")
    ui.cb_research.setChecked(bool(permissions.get("allow_web_research", True)))
    ui.cb_research.setToolTip(
        "Quietly checks public sources for questions about people, games, media, "
        "places, events, and other facts before answering. Search terms are sent "
        "to DuckDuckGo; no browser window is opened."
    )
    ui.cb_write = QCheckBox("Allow file writes")
    ui.cb_write.setChecked(bool(permissions.get("allow_write_file", False)))
    ui.cb_vision = QCheckBox("Let the local vision model read attached images")
    ui.cb_vision.setChecked(bool(permissions.get("allow_vision", True)))
    ui.cb_vision.setToolTip(
        "Images go to your local Ollama vision model only when you press Send. "
        "Nothing is uploaded to a cloud service."
    )
    ui.cb_browser = QCheckBox(
        "Allow browser automation (Himari opens its own Chrome window)"
    )
    ui.cb_browser.setChecked(
        bool(permissions.get("allow_browser_automation", False))
    )
    ui.cb_browser.setToolTip(
        "Lets Himari search, open results, read pages, and manage tabs in its own "
        "visible Chrome window. That window uses a separate profile without your "
        "saved logins, and your everyday Chrome tabs are never touched. Payments "
        "and logins are refused. Disabled by default."
    )
    ui.cb_media = QCheckBox(
        "Allow Windows media controls (may affect the active media app)"
    )
    ui.cb_media.setChecked(bool(permissions.get("allow_media_control", False)))

    for widget in (
        ui.cb_apps,
        ui.cb_web,
        ui.cb_research,
        ui.cb_write,
        ui.cb_vision,
        ui.cb_browser,
        ui.cb_media,
    ):
        section.addWidget(widget)
    section.addHint(
        "Screenshots still work without a vision model: Himari falls back to "
        "on-device Windows OCR and still asks before capturing."
    )

    ui.allowed_folders = QListWidget()
    ui.allowed_folders.addItems(permissions.get("allowed_folders", []))
    add_folder = QPushButton("Add allowed folder")
    add_folder.clicked.connect(ui.add_allowed_folder)
    remove_folder = QPushButton("Remove selected folder")
    remove_folder.clicked.connect(
        lambda: ui.allowed_folders.takeItem(ui.allowed_folders.currentRow())
        if ui.allowed_folders.currentRow() >= 0
        else None
    )
    section.addWidget(QLabel("Folders available to file tools:"))
    section.addWidget(ui.allowed_folders)
    section.addLayout(_row(add_folder, remove_folder, None))


def _build_advanced(ui, cfg, section):
    ollama = cfg.get("ollama", {}) or {}
    section.addHint(
        "Only change these if you use a different local Ollama setup. Himari "
        "never downloads a model automatically."
    )
    ui.ollama_host = QLineEdit(
        ollama.get("host", "http://127.0.0.1:11434")
    )
    section.addWidget(QLabel("Ollama server URL:"))
    section.addWidget(ui.ollama_host)

    ui.model_box = QComboBox()
    configured_model = ollama.get("chat_model", "qwen3:8b")
    ui.model_box.addItems(dict.fromkeys(["qwen3:8b", configured_model]))
    ui.model_box.setCurrentText(configured_model)
    section.addWidget(QLabel("Chat model:"))
    section.addWidget(ui.model_box)

    ui.reply_wait = QSpinBox()
    ui.reply_wait.setRange(60, 1800)
    ui.reply_wait.setSingleStep(60)
    ui.reply_wait.setSuffix(" s")
    ui.reply_wait.setValue(int(ollama.get("stream_timeout_seconds", 900)))
    ui.reply_wait.setToolTip(
        "How long Himari waits for one reply, including the first model load. "
        "The Stop button still cancels immediately."
    )
    section.addWidget(QLabel("Reply wait limit (seconds):"))
    section.addWidget(ui.reply_wait)

    ui.cb_preload = QCheckBox(
        "Preload the chat model at startup (faster first reply)"
    )
    ui.cb_preload.setChecked(bool(ollama.get("preload_model", True)))
    ui.cb_preload.setToolTip(
        "Loads the already-installed local model into Ollama memory when Himari "
        "starts. Nothing is downloaded. The first reply after launch is the "
        "slowest one because the model has to wake up."
    )
    section.addWidget(ui.cb_preload)

    ui.cb_deep_reasoning = QCheckBox(
        "Think deeply before answering or controlling apps (slower, more accurate)"
    )
    ui.cb_deep_reasoning.setChecked(bool(ollama.get("deep_reasoning", True)))
    ui.cb_deep_reasoning.setToolTip(
        "Lets the local model reason step by step before factual questions, "
        "multi-step requests, planning, code, attached images, and app or screen "
        "actions. Replies take longer but are more accurate; greetings stay fast."
    )
    section.addWidget(ui.cb_deep_reasoning)

    ui.vision_model_box = QComboBox()
    ui.vision_model_box.setEditable(True)
    configured_vision = ollama.get("vision_model") or "qwen2.5vl:3b"
    ui.vision_model_box.addItems(
        dict.fromkeys(["qwen2.5vl:3b", configured_vision])
    )
    ui.vision_model_box.setCurrentText(configured_vision)
    ui.vision_model_box.setToolTip(
        "Ollama vision-language model used to read screenshots and photos. "
        "Install it with: ollama pull qwen2.5vl:3b"
    )
    section.addWidget(QLabel("Vision model (optional):"))
    section.addWidget(ui.vision_model_box)

    ui.chat_engine_box = QComboBox()
    ui.chat_engine_box.addItem("Rich (math, diagrams, tables)", "web")
    ui.chat_engine_box.addItem("Classic (plain text)", "classic")
    ui.chat_engine_box.setCurrentIndex(
        max(0, ui.chat_engine_box.findData(cfg.get("ui", {}).get("chat_engine", "web")))
    )
    ui.chat_engine_box.setToolTip(
        "Rich mode draws Markdown, formulas and Mermaid diagrams in an embedded "
        "browser view. Changes apply after restarting Himari."
    )
    section.addWidget(QLabel("Chat rendering:"))
    section.addWidget(ui.chat_engine_box)
    section.addHint("Chat rendering changes take effect after a restart.")

    ui.development_workspaces = QListWidget()
    ui.development_workspaces.addItems(
        (cfg.get("development", {}) or {}).get("workspaces", [])
    )
    add_workspace = QPushButton("Add development workspace")
    add_workspace.clicked.connect(ui.add_development_workspace)
    remove_workspace = QPushButton("Remove selected workspace")
    remove_workspace.clicked.connect(
        lambda: ui.development_workspaces.takeItem(
            ui.development_workspaces.currentRow()
        )
        if ui.development_workspaces.currentRow() >= 0
        else None
    )
    section.addWidget(
        QLabel("Development workspaces (for VS Code project tools):")
    )
    section.addWidget(ui.development_workspaces)
    section.addLayout(_row(add_workspace, remove_workspace, None))


def _build_window_and_data(ui, cfg, section):
    ui_cfg = cfg.get("ui", {}) or {}
    ui.cb_always_on_top = QCheckBox("Always on top")
    ui.cb_always_on_top.setChecked(bool(ui_cfg.get("always_on_top", False)))
    ui.cb_always_on_top.toggled.connect(ui._set_always_on_top)
    ui.cb_minimize_to_tray = QCheckBox("Minimize to tray")
    ui.cb_minimize_to_tray.setChecked(bool(ui_cfg.get("minimize_to_tray", True)))
    section.addWidget(ui.cb_always_on_top)
    section.addWidget(ui.cb_minimize_to_tray)
    ui._set_always_on_top(ui.cb_always_on_top.isChecked())

    ui.view_logs = QPushButton("View application log")
    ui.view_logs.clicked.connect(ui.open_log_viewer)
    ui.open_logs = QPushButton("Open log folder")
    ui.open_logs.clicked.connect(ui.open_log_folder)
    section.addWidget(QLabel("Diagnostics:"))
    section.addLayout(_row(ui.view_logs, ui.open_logs, None))

    ui.clear_history_btn = QPushButton("Clear all chat history…")
    ui.clear_history_btn.setObjectName("StopButton")
    ui.clear_history_btn.setToolTip(
        "Deletes chats and summaries; saved memories and settings stay"
    )
    ui.clear_history_btn.clicked.connect(ui.clear_all_history)
    section.addWidget(QLabel("Local data:"))
    section.addWidget(ui.clear_history_btn)


def build_settings_page(ui):
    cfg = load()
    page = QWidget()
    page.setObjectName("SettingsPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(4, 4, 10, 8)
    layout.setSpacing(10)

    intro = QLabel(
        "Changes save automatically. Hover any option for the details, and use "
        "the arrows to fold a group away."
    )
    intro.setObjectName("SettingsIntro")
    intro.setWordWrap(True)
    layout.addWidget(intro)

    _build_voice(ui, cfg, _section(layout, "Voice & microphone", True))
    _build_screen(ui, cfg, _section(layout, "Screen & shortcuts", True))
    _build_privacy(ui, cfg, _section(layout, "Privacy & memory", True))
    _build_permissions(ui, cfg, _section(layout, "Permissions", False))
    _build_advanced(ui, cfg, _section(layout, "Advanced", False))
    _build_window_and_data(ui, cfg, _section(layout, "Window & data", False))
    layout.addStretch()

    scroll = QScrollArea()
    scroll.setObjectName("SettingsScroll")
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    return scroll
