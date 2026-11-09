import sys, threading, logging
from datetime import datetime
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QTextEdit,
 QLineEdit,QPushButton,QLabel,QListWidget,QCheckBox,QComboBox,QSlider,QTabWidget,QInputDialog,QFileDialog,
 QMessageBox,QSystemTrayIcon,QMenu,QScrollArea)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QTextCursor
from .config import load, save
from . import db, persona
from .avatar import AvatarWidget, FloatingAvatarWindow
from .llm import LLM
from .voice import STT, TTS, Mic, WakeWordMonitor, correct_known_voice_commands
from .screen import analyze
from .tools import TOOLS
log=logging.getLogger("himari.ui")
class UI(QMainWindow):
    token=Signal(str); status=Signal(str); done=Signal(str); tool=Signal(str)
    failed=Signal(str); voice_result=Signal(str); screen_result=Signal(str,str); screen_error=Signal(str)
    ollama_checked=Signal(object)
    hotkey_pressed=Signal(); screen_hotkey_pressed=Signal(); confirmation_requested=Signal(object)
    auto_stop_requested=Signal(); wake_word_detected_signal=Signal(str)
    def __init__(self):
        super().__init__(); self.setWindowTitle("Himari ひまり"); self.resize(1000,700)
        self.session="default"; self.llm=LLM(TOOLS)
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
        self.wake_word_monitor = WakeWordMonitor(
            on_detect=self.wake_word_detected_signal.emit,
            on_error=self.status.emit,
        )
        self.wake_word_status = QLabel("Wake-word: idle")
        self.wake_word_status.setStyleSheet("color: #8b8b8b;")
        self.floating_avatar = FloatingAvatarWindow(self)
        self.tray=None
        self.capture_tray_action=None
        self._allow_quit = False
        self._init_tray()
        self.token.connect(self._token); self.status.connect(self._status)
        self.done.connect(self._done); self.tool.connect(self._tool)
        self.failed.connect(self._failed); self.voice_result.connect(self._apply_voice_text)
        self.screen_result.connect(self._screen_result); self.screen_error.connect(self._screen_failed)
        self.hotkey_pressed.connect(self.toggle_mic)
        self.screen_hotkey_pressed.connect(self.screen_query)
        self.confirmation_requested.connect(self._confirm_tool)
        self.auto_stop_requested.connect(self._auto_stop_mic)
        self.wake_word_detected_signal.connect(self._wake_word_detected)
        self.ollama_checked.connect(self._apply_ollama_status)
        tabs=QTabWidget(); self.setCentralWidget(tabs)
        # Chat tab
        chat=QWidget(); v=QVBoxLayout(chat)
        header=QHBoxLayout()
        self.avatar=AvatarWidget(self); self.avatar.setFixedSize(88,88)
        title=QVBoxLayout()
        name=QLabel("Himari ひまり"); name.setStyleSheet("font-size: 22px; font-weight: 700; color: #b45182;")
        tagline=QLabel("Your local desktop companion"); tagline.setStyleSheet("color: #806b7c;")
        title.addWidget(name); title.addWidget(tagline); title.addStretch()
        self.floating_avatar_btn=QPushButton("Floating avatar")
        self.floating_avatar_btn.clicked.connect(self.toggle_floating_avatar)
        header.addWidget(self.avatar); header.addLayout(title); header.addStretch()
        header.addWidget(self.floating_avatar_btn); v.addLayout(header)
        self.chat=QTextEdit(); self.chat.setReadOnly(True)
        self.chat.setFont(QFont("Segoe UI",load()["ui"].get("font_size",14)))
        self.avatar_state = QLabel("● Idle")
        self.avatar_state.setStyleSheet("color: #d9bfed; background: rgba(125,90,146,0.20); border-radius: 10px; padding: 5px 10px;")
        self._set_avatar_state("Idle")
        v.addWidget(self.avatar_state)
        v.addWidget(self.chat)
        row=QHBoxLayout()
        self.mic_btn=QPushButton("🎤 Talk (F9)"); self.mic_btn.clicked.connect(self.toggle_mic)
        self.stop_btn=QPushButton("⏹ Stop Voice"); self.stop_btn.clicked.connect(self.tts.stop)
        screen_key = load().get("screen", {}).get("capture_hotkey", "f10").upper()
        self.analyze_btn=QPushButton(f"📷 Capture Screen ({screen_key})"); self.analyze_btn.clicked.connect(self.screen_query)
        self.clear_btn=QPushButton("🗑 Clear Chat"); self.clear_btn.clicked.connect(self.clear_chat)
        for b in [self.mic_btn,self.stop_btn,self.analyze_btn,self.clear_btn]: row.addWidget(b)
        v.addLayout(row)
        row2=QHBoxLayout(); self.input=QLineEdit(); self.input.setPlaceholderText("Talk to Himari…")
        self.input.returnPressed.connect(self.send)
        send=QPushButton("Send"); send.clicked.connect(self.send)
        row2.addWidget(self.input); row2.addWidget(send); v.addLayout(row2)
        self.status_label=QLabel("Starting…"); v.addWidget(self.status_label)
        v.addWidget(self.wake_word_status)
        tabs.addTab(chat,"Chat")
        activity_tab=QWidget(); activity_layout=QVBoxLayout(activity_tab)
        self.activity_list=QListWidget(); activity_layout.addWidget(self.activity_list)
        tabs.addTab(activity_tab,"Activity")
        # Memory tab
        mem=QWidget(); mv=QVBoxLayout(mem)
        self.memory_search=QLineEdit()
        self.memory_search.setPlaceholderText("Search saved memories")
        self.memory_search.textChanged.connect(self.refresh_mem)
        mv.addWidget(self.memory_search)
        self.mem_list=QListWidget(); mv.addWidget(self.mem_list)
        mrow=QHBoxLayout()
        add=QPushButton("Add"); add.clicked.connect(self.add_mem)
        edit=QPushButton("Edit"); edit.clicked.connect(self.edit_mem)
        dele=QPushButton("Delete"); dele.clicked.connect(self.del_mem)
        for b in [add,edit,dele]: mrow.addWidget(b)
        mv.addLayout(mrow)
        mv.addWidget(QLabel("Memory suggestions (review before saving):"))
        self.suggestion_list=QListWidget(); mv.addWidget(self.suggestion_list)
        suggestion_row=QHBoxLayout()
        approve=QPushButton("Approve suggestion")
        approve.clicked.connect(self.approve_memory_suggestion)
        reject=QPushButton("Reject suggestion")
        reject.clicked.connect(self.reject_memory_suggestion)
        suggestion_row.addWidget(approve); suggestion_row.addWidget(reject)
        mv.addLayout(suggestion_row); tabs.addTab(mem,"Memory")
        # Settings tab
        st=QWidget(); sv=QVBoxLayout(st)
        self.cb_store=QCheckBox("Store conversations locally"); self.cb_store.setChecked(load()["privacy"]["store_conversations"])
        self.cb_auto_memory=QCheckBox("Create pending memory suggestions on explicit requests")
        self.cb_auto_memory.setChecked(load()["privacy"].get("auto_memory", True))
        self.cb_apps=QCheckBox("Allow opening apps and Steam games"); self.cb_apps.setChecked(load()["permissions"]["allow_open_app"])
        self.cb_web=QCheckBox("Allow opening websites"); self.cb_web.setChecked(load()["permissions"]["allow_open_url"])
        self.cb_research=QCheckBox("Allow background web research (sends search terms to DuckDuckGo; does not open a browser)")
        self.cb_research.setChecked(load()["permissions"].get("allow_web_research", True))
        self.cb_screen=QCheckBox("Allow one-time screen capture (asks for confirmation each time)")
        self.cb_screen.setChecked(load()["permissions"].get("allow_screen_capture", True))
        self.cb_active_window=QCheckBox("Allow requested active-window detection")
        self.cb_active_window.setChecked(load()["permissions"].get("allow_active_window", False))
        self.cb_media=QCheckBox("Allow Windows media controls (may affect the active media app)")
        self.cb_media.setChecked(load()["permissions"].get("allow_media_control", False))
        self.cb_cmd=QCheckBox("Allow shell commands (disabled for safety)")
        self.cb_cmd.setChecked(False)
        self.cb_cmd.setEnabled(False)
        self.cb_cmd.setToolTip(
            "Himari uses dedicated permission-checked tools "
            "instead of arbitrary shell execution."
        )
        self.cb_write=QCheckBox("Allow file writes"); self.cb_write.setChecked(load()["permissions"]["allow_write_file"])
        self.cb_wake=QCheckBox("Enable wake-word listening (Himari)"); self.cb_wake.setChecked(load()["voice"].get("wake_word_enabled",False))
        self.cb_wake.toggled.connect(self._toggle_wake_word)
        self.cb_always_on_top=QCheckBox("Always on top"); self.cb_always_on_top.setChecked(load()["ui"].get("always_on_top",False))
        self.cb_always_on_top.toggled.connect(self._set_always_on_top)
        self.cb_minimize_to_tray=QCheckBox("Minimize to tray"); self.cb_minimize_to_tray.setChecked(load()["ui"].get("minimize_to_tray",True))
        self._set_always_on_top(self.cb_always_on_top.isChecked())
        self.allowed_folders=QListWidget()
        self.allowed_folders.addItems(load()["permissions"].get("allowed_folders",[]))
        folder_row=QHBoxLayout()
        add_folder=QPushButton("Add allowed folder")
        add_folder.clicked.connect(self.add_allowed_folder)
        remove_folder=QPushButton("Remove selected folder")
        remove_folder.clicked.connect(lambda:self.allowed_folders.takeItem(self.allowed_folders.currentRow())
                                      if self.allowed_folders.currentRow()>=0 else None)
        folder_row.addWidget(add_folder); folder_row.addWidget(remove_folder)
        self.mic_box=QComboBox()
        self.mic_box.addItem("System default",None)
        try:
            import sounddevice as sd
            selected_device=load()["voice"].get("microphone_device")
            for index,device in enumerate(sd.query_devices()):
                if device["max_input_channels"]>0:
                    self.mic_box.addItem(f"{index}: {device['name']}",index)
                    if index==selected_device: self.mic_box.setCurrentIndex(self.mic_box.count()-1)
        except Exception as e: log.warning("Microphone list unavailable: %s",e)
        self.voice_box=QComboBox()
        available_voices = TTS().available_voices()
        configured_voice = load()["voice"].get("tts_voice")
        if (
            configured_voice == "en_US-lessac-medium"
            and "en_US-amy-medium" in available_voices
        ):
            configured_voice = "en_US-amy-medium"
        self.voice_box.addItems(available_voices or [configured_voice or "en_US-amy-medium"])
        if configured_voice in [self.voice_box.itemText(i) for i in range(self.voice_box.count())]:
            self.voice_box.setCurrentText(configured_voice)
        self.model_box=QComboBox()
        configured_model=load()["ollama"]["chat_model"]
        self.model_box.addItems(dict.fromkeys(["qwen3:8b",configured_model]))
        self.model_box.setCurrentText(configured_model)
        self.lang_box=QComboBox()
        self.lang_box.addItem("Automatic", "auto")
        self.lang_box.addItem("English", "en")
        self.lang_box.addItem("Russian", "ru")
        current_lang = (load()["voice"].get("recognition_language") or load()["voice"].get("language") or "en").lower()
        language_code = "ru" if current_lang.startswith("ru") else "en" if current_lang.startswith("en") else "auto"
        self.lang_box.setCurrentIndex(self.lang_box.findData(language_code))
        self.sensitivity=QSlider(Qt.Horizontal); self.sensitivity.setRange(10,100); self.sensitivity.setValue(int(float(load()["voice"].get("sensitivity",0.75))*100))
        self.wake_word_field=QLineEdit(load()["voice"].get("wake_word","Himari"))
        self.vol=QSlider(Qt.Horizontal); self.vol.setRange(0,100); self.vol.setValue(int(load()["voice"]["volume"]*100))
        self.hotkey=QLineEdit(load()["voice"]["push_to_talk_key"])
        self.screen_hotkey=QLineEdit(load().get("screen", {}).get("capture_hotkey", "f10"))
        self.screen_hotkey.textChanged.connect(
            lambda key:self.analyze_btn.setText(f"📷 Capture Screen ({key.strip().upper() or 'F10'})")
        )
        for w in [self.cb_store,self.cb_auto_memory,self.cb_apps,self.cb_web,self.cb_research,self.cb_screen,
                  self.cb_active_window,self.cb_media,
                  self.cb_cmd,self.cb_write,self.cb_wake,
                  self.cb_always_on_top,self.cb_minimize_to_tray,
                  QLabel("Folders available to file tools:"),self.allowed_folders]: sv.addWidget(w)
        sv.addLayout(folder_row)
        for w in [QLabel("Microphone:"),self.mic_box,
                  QLabel("Recognition language:"),self.lang_box,
                  QLabel("Wake word:"),self.wake_word_field,
                  QLabel("Wake-word sensitivity:"),self.sensitivity,
                  QLabel("Voice (English default; Russian falls back to Windows):"),self.voice_box,
                  QLabel("Chat model:"),self.model_box,
                  QLabel("TTS volume:"),self.vol,QLabel("Push-to-talk key:"),self.hotkey,
                  QLabel("Global screen-capture key:"),self.screen_hotkey]: sv.addWidget(w)
        sv.addStretch()
        settings_scroll=QScrollArea(); settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(st); tabs.addTab(settings_scroll,"Settings")
        self.refresh_mem()
        self.refresh_actions()
        QTimer.singleShot(300,self.check)
        self._bind_hotkeys()
        if self.cb_wake.isChecked():
            self._toggle_wake_word(True)
    def _bind_hotkeys(self):
        self._remove_hotkeys()
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
        threading.Thread(
            target=lambda:self.ollama_checked.emit(self.llm.model_status()),
            daemon=True,
        ).start()
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
        if self.hotkey_error:
            message = f"{message} {self.hotkey_error}"
        if self.screen_hotkey_error:
            message = f"{message} {self.screen_hotkey_error}"
        self._status(message)
        self._refresh_wake_word_status()
    def _set_avatar_state(self, state):
        states = {
            "Idle": ("● Idle", "#d9bfed"),
            "Listening": ("● Listening", "#8ef0b9"),
            "Thinking": ("● Thinking", "#ffd59d"),
            "Speaking": ("● Speaking", "#ff9ed6"),
            "Working": ("● Working", "#9cc9ff"),
            "Error": ("● Error", "#ff7b7b"),
        }
        label, color = states.get(state, states["Idle"])
        self.avatar_state.setText(label)
        self.avatar_state.setStyleSheet(f"color: {color}; background: rgba(125,90,146,0.20); border-radius: 10px; padding: 5px 10px;")
        avatar_state = {
            "Listening": "listening",
            "Thinking": "thinking",
            "Speaking": "speaking",
            "Working": "thinking",
            "Error": "error",
        }.get(state, "idle")
        self.avatar.set_state(avatar_state)
        self.floating_avatar.set_state(avatar_state)
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
        elif "generating" in s.lower() or "thinking" in s.lower() or "checking" in s.lower():
            self._set_avatar_state("Thinking")
        elif "speaking" in s.lower():
            self._set_avatar_state("Speaking")
        elif "tool" in s.lower() or "completed" in s.lower() or "working" in s.lower():
            self._set_avatar_state("Working")
        else:
            self._set_avatar_state("Idle")
    def _refresh_wake_word_status(self, state="idle"):
        if state == "listening":
            self.wake_word_status.setText("Wake-word: listening")
            self.wake_word_status.setStyleSheet("color: #5fe7a8; font-weight: 600;")
        elif state == "triggered":
            self.wake_word_status.setText("Wake-word: detected")
            self.wake_word_status.setStyleSheet("color: #ffb86c; font-weight: 600;")
        else:
            self.wake_word_status.setText("Wake-word: idle")
            self.wake_word_status.setStyleSheet("color: #8b8b8b;")
    def _init_tray(self):
        if self.tray is not None:
            return
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
    def _token(self,t):
        self._streamed_response += t
        self._status("Generating response…")
        cursor=self.chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(t)
        self.chat.setTextCursor(cursor)
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())
    def _tool(self,s):
        self.chat.append(f"\n[tool] {s}\n")
        self._status("Completed a requested action; continuing response…")
        self.refresh_actions()
    def _done(self,t):
        self.busy=False
        if t.strip() and not self._streamed_response.rstrip().endswith(t.strip()):
            self.chat.append(f"\nHimari: {t}")
            self._streamed_response = t
        self.chat.ensureCursorVisible()
        if load()["privacy"].get("store_conversations",True): db.add_message(self.session,"assistant",t)
        self._speak(t)
    def _speak(self,t):
        try:
            if t.strip():
                self.status.emit("Speaking… click Stop Voice to interrupt.")
                self.tts.speak(t)
            else:
                self._status("No response to speak.")
        except Exception as e: self._status(f"TTS unavailable: {e}")
    def send(self, screen_context=None):
        if self.busy: return
        text=self.input.text().strip()
        if not text: return
        self.input.clear(); self.busy=True
        self._streamed_response = ""
        self._status("Hmm, let me think.")
        self.chat.append(f"\nYou: {text}\nHimari: ")
        if load()["privacy"].get("store_conversations",True): db.add_message(self.session,"user",text)
        privacy = load()["privacy"]
        if privacy.get("store_conversations", True) and privacy.get("auto_memory", True):
            try:
                if db.suggest_memory(text):
                    self.refresh_mem()
            except Exception as exc:
                log.exception("Could not save a memory suggestion")
                self.status.emit(f"Memory suggestion error: {exc}")
        relevant = db.relevant_memories(text, limit=8)
        summary = db.summary_for_session(self.session)
        msgs=persona.build(
            db.history(self.session),
            relevant,
            user_query=text,
            summary=summary,
            screen_context=screen_context,
        )
        threading.Thread(target=self._run,args=(msgs,),daemon=True).start()
    def _run(self,msgs):
        try:
            out=[]
            def on_token(t): out.append(t); self.token.emit(t)
            def confirm(name,args,msg):
                result={"allowed":False,"event":threading.Event()}
                self.confirmation_requested.emit((name,args,msg,result))
                result["event"].wait()
                return result["allowed"]
            self.llm.stream_chat(msgs,on_token,on_tool=lambda n,a,r: self.tool.emit(f"{n} {a} → {r}"),confirm=confirm)
            self.done.emit("".join(out))
        except Exception as e:
            self.failed.emit(f"LLM error: {e}")
    def _confirm_tool(self,request):
        name,args,message,result=request
        if name == "write_desktop_file":
            content = args.get("content", "")
            details = (
                f"File: {args.get('filename', '')}\n"
                f"Characters: {len(content) if isinstance(content, str) else 0}\n\n"
                f"Preview: {content[:500] if isinstance(content, str) else ''}"
            )
        else:
            details = str(args)
        answer=QMessageBox.question(self,"Confirm Himari action",
            f"{message}\n\n{name}:\n{details}",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        result["allowed"]=answer==QMessageBox.Yes
        result["event"].set()
    def _failed(self,message):
        self.busy=False
        self.status_label.setText(message)
        self.chat.append(f"\n{message}\n")
    def _auto_stop_mic(self):
        if self.mic.rec:
            audio=self.mic.stop(); self.mic_btn.setText("🎤 Talk (F9)")
            self._status("Voice detected; transcribing locally…")
            threading.Thread(
                target=self._transcribe,
                args=(audio, self._recognition_language()),
                daemon=True,
            ).start()

    def toggle_mic(self):
        if self.mic.rec:
            audio=self.mic.stop(); self.mic_btn.setText("🎤 Talk (F9)")
            self._status("Transcribing locally…")
            threading.Thread(
                target=self._transcribe,
                args=(audio, self._recognition_language()),
                daemon=True,
            ).start()
        else:
            try:
                self.mic.start(on_silence=None)
                self.mic_btn.setText("⏹ Stop & Transcribe")
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
                self.mic.start(on_silence=self.auto_stop_requested.emit)
                self.mic_btn.setText("⏹ Stop & Transcribe")
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

        answer = QMessageBox.question(
            self,
            "Allow one-time screen capture?",
            (
                "Himari will capture your primary screen once, "
                "extract visible text locally, and discard the screenshot.\n\n"
                "The extracted text will be sent to your local Ollama model.\n\n"
                "Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            self._status("Screen capture cancelled.")
            return

        question = self.input.text().strip()
        self.analyze_btn.setEnabled(False)
        self._status("Capturing the primary screen and reading its text locally…")

        def work():
            try:
                self.screen_result.emit(analyze(), question)
            except Exception as e:
                self.screen_error.emit(f"Screen error: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _screen_result(self,text,question):
        self.analyze_btn.setEnabled(True)
        if self.isHidden():
            self.show(); self.raise_(); self.activateWindow()
        self.chat.append(f"\n[Screen text extracted; screenshot discarded]\n{text[:2000]}\n")
        self.input.setText(question or "Please read the text captured from my screen and explain what it shows.")
        self.send(screen_context=text)
    def _screen_failed(self,message):
        self.analyze_btn.setEnabled(True)
        if self.isHidden():
            self.show(); self.raise_(); self.activateWindow()
        self._status(message)
    def clear_chat(self):
        self.chat.clear(); db.clear_session(self.session)
    def refresh_mem(self):
        query=self.memory_search.text().strip().casefold()
        self.mem_list.clear()
        for m in db.memories():
            if not query or query in m["text"].casefold():
                self.mem_list.addItem(f"{m['id'][:8]} — {m['text']}")
        self.suggestion_list.clear()
        for suggestion in db.memory_suggestions():
            self.suggestion_list.addItem(
                f"{suggestion['id'][:8]} — {suggestion['text']}"
            )
    def _selected_memory_suggestion(self):
        row=self.suggestion_list.currentRow()
        suggestions=db.memory_suggestions()
        return suggestions[row] if 0 <= row < len(suggestions) else None
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
    def add_mem(self):
        text,ok=QInputDialog.getText(self,"Add memory","Memory:")
        if ok and text: db.add_memory(text); self.refresh_mem()
    def edit_mem(self):
        row=self.mem_list.currentRow()
        if row<0: return
        m=db.memories()[row]
        text,ok=QInputDialog.getText(self,"Edit memory","Memory:",text=m["text"])
        if ok and text: db.update_memory(m["id"],text); self.refresh_mem()
    def del_mem(self):
        row=self.mem_list.currentRow()
        if row<0: return
        m=db.memories()[row]; db.delete_memory(m["id"]); self.refresh_mem()
    def closeEvent(self,e):
        cfg=load()
        cfg["privacy"]["store_conversations"]=self.cb_store.isChecked()
        cfg["privacy"]["auto_memory"]=self.cb_auto_memory.isChecked()
        cfg["permissions"]["allow_open_app"]=self.cb_apps.isChecked()
        cfg["permissions"]["allow_open_url"]=self.cb_web.isChecked()
        cfg["permissions"]["allow_web_research"]=self.cb_research.isChecked()
        cfg["permissions"]["allow_screen_capture"]=self.cb_screen.isChecked()
        cfg["permissions"]["allow_active_window"]=self.cb_active_window.isChecked()
        cfg["permissions"]["allow_media_control"]=self.cb_media.isChecked()
        cfg["permissions"]["allow_run_command"] = False
        cfg["permissions"]["allow_write_file"]=self.cb_write.isChecked()
        cfg["ui"]["always_on_top"]=self.cb_always_on_top.isChecked()
        cfg["ui"]["minimize_to_tray"]=self.cb_minimize_to_tray.isChecked()
        cfg["permissions"]["allowed_folders"]=[
            self.allowed_folders.item(i).text() for i in range(self.allowed_folders.count())
        ]
        cfg["ollama"]["chat_model"]=self.model_box.currentText()
        cfg["voice"]["volume"]=self.vol.value()/100
        cfg["voice"]["tts_voice"]=self.voice_box.currentText() if self.voice_box.count() else cfg["voice"].get("tts_voice", "en_US-amy-medium")
        cfg["voice"]["push_to_talk_key"]=self.hotkey.text().strip() or "f9"
        cfg["voice"]["microphone_device"]=self.mic_box.currentData()
        cfg["voice"]["wake_word_enabled"]=self.cb_wake.isChecked()
        cfg["voice"]["wake_word"]=self.wake_word_field.text().strip() or "Himari"
        cfg["voice"]["sensitivity"]=max(0.1, min(1.0, self.sensitivity.value()/100))
        cfg["voice"]["recognition_language"] = self._recognition_language()
        cfg["voice"]["language"] = cfg["voice"]["recognition_language"]
        cfg.setdefault("screen", {})["capture_hotkey"] = self.screen_hotkey.text().strip() or "f10"
        save(cfg)
        self.tts.stop()
        if self.mic.rec: self.mic.stop()
        if self.tray is not None and self.cb_minimize_to_tray.isChecked() and not self._allow_quit:
            self._bind_hotkeys()
            self.hide();
            e.ignore();
            return
        self.wake_word_monitor.stop()
        self._remove_hotkeys()
        if self.tray is not None:
            self.tray.hide()
        self.floating_avatar.hide()
        self._allow_quit = False
        super().closeEvent(e)
def run():
    from .logging_setup import configure_logging

    configure_logging()
    app=QApplication(sys.argv); w=UI(); w.show(); sys.exit(app.exec())
