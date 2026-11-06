import sys, threading, io, logging
from datetime import datetime
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QTextEdit,
 QLineEdit,QPushButton,QLabel,QListWidget,QCheckBox,QComboBox,QSlider,QTabWidget,QInputDialog,QFileDialog,
 QMessageBox,QSystemTrayIcon,QMenu)
from PySide6.QtCore import Qt, Signal, QTimer, QByteArray
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QTextCursor
from PySide6.QtSvg import QSvgRenderer
from .config import load, save
from . import db, persona
from .llm import LLM
from .voice import STT, TTS, Mic, WakeWordMonitor
from .screen import capture, analyze
from .tools import TOOLS
log=logging.getLogger("himari.ui")
class UI(QMainWindow):
    token=Signal(str); status=Signal(str); done=Signal(str); tool=Signal(str)
    failed=Signal(str); voice_result=Signal(str); screen_result=Signal(str); screen_error=Signal(str)
    hotkey_pressed=Signal(); confirmation_requested=Signal(object)
    auto_stop_requested=Signal(); wake_word_detected_signal=Signal(str)
    def __init__(self):
        super().__init__(); self.setWindowTitle("Himari ひまり"); self.resize(1000,700)
        self.session="default"; self.llm=LLM(TOOLS)
        self.tts=TTS(
            on_error=lambda message:self.status.emit(f"TTS error: {message}"),
            on_finished=lambda:self.status.emit("Ready."),
        )
        self.mic=Mic(); self.stt=None; self.busy=False; self.hotkey_id=None
        self.hotkey_error = None
        self.wake_word_monitor = WakeWordMonitor(
            on_detect=self.wake_word_detected_signal.emit,
            on_error=self.status.emit,
        )
        self.wake_word_status = QLabel("Wake-word: idle")
        self.wake_word_status.setStyleSheet("color: #8b8b8b;")
        self.tray=None
        self._allow_quit = False
        self._init_tray()
        self.token.connect(self._token); self.status.connect(self._status)
        self.done.connect(self._done); self.tool.connect(self._tool)
        self.failed.connect(self._failed); self.voice_result.connect(self._apply_voice_text)
        self.screen_result.connect(self._screen_result); self.screen_error.connect(self._status)
        self.hotkey_pressed.connect(self.toggle_mic)
        self.confirmation_requested.connect(self._confirm_tool)
        self.auto_stop_requested.connect(self._auto_stop_mic)
        self.wake_word_detected_signal.connect(self._wake_word_detected)
        tabs=QTabWidget(); self.setCentralWidget(tabs)
        # Chat tab
        chat=QWidget(); v=QVBoxLayout(chat)
        header=QHBoxLayout()
        avatar=QLabel(); avatar.setFixedSize(88,88)
        svg=b"""<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
        <defs><linearGradient id="bg" x2="0" y2="1"><stop stop-color="#ffe4f1"/><stop offset="1" stop-color="#f8b8d4"/></linearGradient>
        <linearGradient id="hair" x2="0" y2="1"><stop stop-color="#81466f"/><stop offset="1" stop-color="#422b59"/></linearGradient></defs>
        <circle cx="64" cy="64" r="62" fill="url(#bg)"/>
        <path d="M25 121V96c0-22 16-33 39-33s39 11 39 33v25z" fill="#76528c"/>
        <path d="M35 64C24 39 37 15 64 14c28-1 42 21 32 52l-7 34H39z" fill="url(#hair)"/>
        <ellipse cx="64" cy="56" rx="26" ry="32" fill="#ffe0d2"/>
        <path d="M38 52c0-26 13-38 30-36 13 1 22 11 23 25-11-2-17-10-19-17-7 13-19 20-34 21z" fill="url(#hair)"/>
        <path d="M40 43c7-4 14-4 20 0-5 3-10 4-20 4m28-4c7-4 14-3 20 1-7 3-13 3-20 1" fill="#ffe0d2"/>
        <ellipse cx="51" cy="56" rx="5" ry="7" fill="#573958"/><ellipse cx="77" cy="56" rx="5" ry="7" fill="#573958"/>
        <circle cx="53" cy="54" r="2" fill="white"/><circle cx="79" cy="54" r="2" fill="white"/>
        <path d="M60 72q4 4 8 0" fill="none" stroke="#c96d83" stroke-width="2" stroke-linecap="round"/>
        <path d="M30 33l-5-13 14 5 7-10 7 15m30-13 9-9 3 15 13 4-12 9" fill="#e88bb2" stroke="#81466f" stroke-width="3" stroke-linejoin="round"/>
        <path d="M49 89l15 11 15-11-4 32H53z" fill="#fff1f7"/>
        <path d="M42 121l8-21 14 10 14-10 8 21" fill="#a878a9"/>
        </svg>"""
        pixmap=QPixmap(avatar.size()); pixmap.fill(Qt.transparent)
        painter=QPainter(pixmap); QSvgRenderer(QByteArray(svg)).render(painter); painter.end()
        avatar.setPixmap(pixmap)
        title=QVBoxLayout()
        name=QLabel("Himari ひまり"); name.setStyleSheet("font-size: 22px; font-weight: 700; color: #b45182;")
        tagline=QLabel("Your local desktop companion"); tagline.setStyleSheet("color: #806b7c;")
        title.addWidget(name); title.addWidget(tagline); title.addStretch()
        header.addWidget(avatar); header.addLayout(title); header.addStretch(); v.addLayout(header)
        self.chat=QTextEdit(); self.chat.setReadOnly(True)
        self.chat.setFont(QFont("Segoe UI",load()["ui"].get("font_size",14)))
        self.avatar_state = QLabel("● Idle")
        self.avatar_state.setStyleSheet("color: #d9bfed; background: rgba(125,90,146,0.20); border-radius: 10px; padding: 5px 10px;")
        self._set_avatar_state("Idle")
        v.addWidget(self.avatar_state)
        v.addWidget(self.chat)
        self.screen_preview=QLabel("Live screen preview is off")
        self.screen_preview.setAlignment(Qt.AlignCenter)
        self.screen_preview.setMinimumHeight(160); self.screen_preview.setMaximumHeight(240)
        self.screen_preview.setStyleSheet("background: #211b27; color: #c8b9c9; border-radius: 8px;")
        self.screen_preview.hide(); v.addWidget(self.screen_preview)
        self.screen_timer=QTimer(self); self.screen_timer.setInterval(1000)
        self.screen_timer.timeout.connect(self._update_live_screen)
        row=QHBoxLayout()
        self.mic_btn=QPushButton("🎤 Talk (F9)"); self.mic_btn.clicked.connect(self.toggle_mic)
        self.stop_btn=QPushButton("⏹ Stop Voice"); self.stop_btn.clicked.connect(self.tts.stop)
        self.screen_btn=QPushButton("▶ Live Screen"); self.screen_btn.clicked.connect(self.toggle_live_screen)
        self.analyze_btn=QPushButton("🔎 Analyze Screen"); self.analyze_btn.clicked.connect(self.screen_query)
        self.clear_btn=QPushButton("🗑 Clear Chat"); self.clear_btn.clicked.connect(self.clear_chat)
        for b in [self.mic_btn,self.stop_btn,self.screen_btn,self.analyze_btn,self.clear_btn]: row.addWidget(b)
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
        mem=QWidget(); mv=QVBoxLayout(mem); self.mem_list=QListWidget(); mv.addWidget(self.mem_list)
        mrow=QHBoxLayout()
        add=QPushButton("Add"); add.clicked.connect(self.add_mem)
        edit=QPushButton("Edit"); edit.clicked.connect(self.edit_mem)
        dele=QPushButton("Delete"); dele.clicked.connect(self.del_mem)
        for b in [add,edit,dele]: mrow.addWidget(b)
        mv.addLayout(mrow); tabs.addTab(mem,"Memory")
        # Settings tab
        st=QWidget(); sv=QVBoxLayout(st)
        self.cb_capture=QCheckBox("Allow screen capture"); self.cb_capture.setChecked(load()["screen"]["allow_capture"])
        self.cb_capture.toggled.connect(self._capture_permission_changed)
        self.cb_vision=QCheckBox("Use vision model for screen understanding"); self.cb_vision.setChecked(load()["screen"]["vision_enabled"])
        self.cb_store=QCheckBox("Store conversations locally"); self.cb_store.setChecked(load()["privacy"]["store_conversations"])
        self.cb_apps=QCheckBox("Allow opening apps and Steam games"); self.cb_apps.setChecked(load()["permissions"]["allow_open_app"])
        self.cb_web=QCheckBox("Allow opening websites"); self.cb_web.setChecked(load()["permissions"]["allow_open_url"])
        self.cb_cmd=QCheckBox("Allow shell commands (dangerous)"); self.cb_cmd.setChecked(load()["permissions"]["allow_run_command"])
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
        self.voice_box.addItems(TTS().available_voices() or [load()["voice"].get("tts_voice","en_US-lessac-medium")])
        configured_voice = load()["voice"].get("tts_voice")
        if configured_voice in [self.voice_box.itemText(i) for i in range(self.voice_box.count())]:
            self.voice_box.setCurrentText(configured_voice)
        self.model_box=QComboBox(); self.model_box.addItems(self.llm.list_models() or ["qwen3:8b"])
        self.model_box.setCurrentText(load()["ollama"]["chat_model"])
        self.vision_box=QComboBox(); self.vision_box.addItems(self.llm.list_models() or ["qwen3:8b"])
        self.vision_box.setCurrentText(load()["ollama"]["vision_model"])
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
        for w in [self.cb_capture,self.cb_vision,self.cb_store,self.cb_apps,self.cb_web,self.cb_cmd,self.cb_write,self.cb_wake,
                  self.cb_always_on_top,self.cb_minimize_to_tray,
                  QLabel("Folders available to file tools:"),self.allowed_folders]: sv.addWidget(w)
        sv.addLayout(folder_row)
        for w in [QLabel("Microphone:"),self.mic_box,
                  QLabel("Recognition language:"),self.lang_box,
                  QLabel("Wake word:"),self.wake_word_field,
                  QLabel("Wake-word sensitivity:"),self.sensitivity,
                  QLabel("Voice:"),self.voice_box,
                  QLabel("Chat model:"),self.model_box,QLabel("Vision model:"),self.vision_box,
                  QLabel("TTS volume:"),self.vol,QLabel("Push-to-talk key:"),self.hotkey]: sv.addWidget(w)
        sv.addStretch(); tabs.addTab(st,"Settings")
        self.refresh_mem()
        self.refresh_actions()
        QTimer.singleShot(300,self.check)
        self._bind_hotkey()
        if self.cb_wake.isChecked():
            self._toggle_wake_word(True)
    def _bind_hotkey(self):
        key = "f9"
        try:
            import keyboard
            key=load()["voice"]["push_to_talk_key"]
            self.hotkey_id=keyboard.add_hotkey(key,lambda:self.hotkey_pressed.emit())
        except Exception as e:
            self.hotkey_error = f"Push-to-talk hotkey '{key}' is unavailable; use the microphone button. ({e})"
            log.warning("Hotkey bind failed: %s",e)
    def check(self):
        message = "Ollama connected ✓" if self.llm.ping() else "Ollama unreachable — start Ollama and pull qwen3:8b."
        if self.hotkey_error:
            message = f"{message} {self.hotkey_error}"
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
    def _status(self,s):
        self.status_label.setText(s)
        if "error" in s.lower() or "failed" in s.lower():
            self._set_avatar_state("Error")
        elif "listening" in s.lower():
            self._set_avatar_state("Listening")
        elif "generating" in s.lower() or "thinking" in s.lower() or "checking" in s.lower():
            self._set_avatar_state("Thinking")
        elif "speaking" in s.lower() or "ready" in s.lower():
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
        hide_action = menu.addAction("Hide")
        hide_action.triggered.connect(self.hide)
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_from_tray)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isHidden():
                self.show(); self.raise_(); self.activateWindow()
            else:
                self.hide()
    def _quit_from_tray(self):
        self._allow_quit = True
        QApplication.instance().quit()
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
        if load()["privacy"].get("store_conversations",True): db.add_message(self.session,"assistant",t)
        if len(db.history(self.session, limit=40)) >= 6 and load()["privacy"].get("auto_memory", True):
            recent = " | ".join(f"{m['role']}: {m['content']}" for m in db.history(self.session, limit=40))
            db.save_summary(self.session, recent[:3000])
        self._speak(t)
    def _speak(self,t):
        try:
            if t.strip():
                self.status.emit("Speaking… click Stop Voice to interrupt.")
                self.tts.speak(t)
            else:
                self._status("No response to speak.")
        except Exception as e: self._status(f"TTS unavailable: {e}")
    def send(self):
        if self.busy: return
        text=self.input.text().strip()
        if not text: return
        self.input.clear(); self.busy=True
        self._status("Hmm, let me think.")
        self.chat.append(f"\nYou: {text}\nHimari: ")
        if load()["privacy"].get("store_conversations",True): db.add_message(self.session,"user",text)
        relevant = db.relevant_memories(text, limit=8)
        summary = db.summary_for_session(self.session)
        msgs=persona.build(db.history(self.session), relevant, user_query=text, summary=summary)
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
        answer=QMessageBox.question(self,"Confirm Himari action",
            f"{message}\n\n{name}: {args}",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
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
        self.input.setText(text)
        self.send()
    def _capture_permission_changed(self,allowed):
        cfg=load(); cfg["screen"]["allow_capture"]=allowed; save(cfg)
        if not allowed:
            self.screen_timer.stop(); self.screen_preview.hide()
            self.screen_btn.setText("▶ Live Screen")
    def toggle_live_screen(self):
        if self.screen_timer.isActive():
            self.screen_timer.stop(); self.screen_preview.hide()
            self.screen_btn.setText("▶ Live Screen")
            return
        if not self.cb_capture.isChecked():
            self._status("Enable 'Allow screen capture' in Settings first.")
            return
        self.screen_preview.show(); self.screen_btn.setText("■ Stop Live Screen")
        self._update_live_screen(); self.screen_timer.start()
    def _update_live_screen(self):
        try:
            image=capture(monitor="1")
            buffer=io.BytesIO(); image.save(buffer,format="PNG")
            pixmap=QPixmap()
            if not pixmap.loadFromData(buffer.getvalue(),"PNG"):
                raise RuntimeError("Could not display the captured screen.")
            self.screen_preview.setPixmap(pixmap.scaled(
                self.screen_preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        except Exception as e:
            self.screen_timer.stop(); self.screen_preview.hide()
            self.screen_btn.setText("▶ Live Screen")
            self._status(f"Live screen error: {e}")
    def screen_query(self):
        if not self.cb_capture.isChecked():
            self._status("Enable 'Allow screen capture' in Settings first.")
            return
        self.analyze_btn.setEnabled(False); self._status("Analyzing the screen…")
        def work():
            try: self.screen_result.emit(analyze())
            except Exception as e: self.screen_error.emit(f"Screen error: {e}")
        threading.Thread(target=work,daemon=True).start()
    def _screen_result(self,text):
        self.analyze_btn.setEnabled(True)
        self.chat.append(f"\n[Screen analysis]\n{text[:2000]}\n")
        self.input.setText("Please explain this screen analysis and suggest useful next steps:\n"+text[:4000])
        self.send()
    def clear_chat(self):
        self.chat.clear(); db.clear_session(self.session)
    def refresh_mem(self):
        self.mem_list.clear()
        for m in db.memories(): self.mem_list.addItem(f"{m['id'][:8]} — {m['text']}")
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
        self.screen_timer.stop()
        self.tts.stop()
        if self.mic.rec: self.mic.stop()
        if self.hotkey_id is not None:
            try:
                import keyboard
                keyboard.remove_hotkey(self.hotkey_id)
            except Exception as err: log.warning("Hotkey cleanup failed: %s",err)
        cfg=load()
        cfg["screen"]["allow_capture"]=self.cb_capture.isChecked()
        cfg["screen"]["vision_enabled"]=self.cb_vision.isChecked()
        cfg["privacy"]["store_conversations"]=self.cb_store.isChecked()
        cfg["permissions"]["allow_open_app"]=self.cb_apps.isChecked()
        cfg["permissions"]["allow_open_url"]=self.cb_web.isChecked()
        cfg["permissions"]["allow_run_command"]=self.cb_cmd.isChecked()
        cfg["permissions"]["allow_write_file"]=self.cb_write.isChecked()
        cfg["ui"]["always_on_top"]=self.cb_always_on_top.isChecked()
        cfg["ui"]["minimize_to_tray"]=self.cb_minimize_to_tray.isChecked()
        cfg["permissions"]["allowed_folders"]=[
            self.allowed_folders.item(i).text() for i in range(self.allowed_folders.count())
        ]
        cfg["ollama"]["chat_model"]=self.model_box.currentText()
        cfg["ollama"]["vision_model"]=self.vision_box.currentText()
        cfg["voice"]["volume"]=self.vol.value()/100
        cfg["voice"]["tts_voice"]=self.voice_box.currentText() if self.voice_box.count() else cfg["voice"].get("tts_voice", "en_US-lessac-medium")
        cfg["voice"]["push_to_talk_key"]=self.hotkey.text().strip() or "f9"
        cfg["voice"]["microphone_device"]=self.mic_box.currentData()
        cfg["voice"]["wake_word_enabled"]=self.cb_wake.isChecked()
        cfg["voice"]["wake_word"]=self.wake_word_field.text().strip() or "Himari"
        cfg["voice"]["sensitivity"]=max(0.1, min(1.0, self.sensitivity.value()/100))
        cfg["voice"]["recognition_language"] = self._recognition_language()
        cfg["voice"]["language"] = cfg["voice"]["recognition_language"]
        save(cfg)
        if self.tray is not None and self.cb_minimize_to_tray.isChecked() and not self._allow_quit:
            self.hide();
            e.ignore();
            return
        self._allow_quit = False
        super().closeEvent(e)
def run():
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app=QApplication(sys.argv); w=UI(); w.show(); sys.exit(app.exec())
