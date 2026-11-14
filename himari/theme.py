"""Application palette and stylesheet.

Kept free of Qt imports so it can be tested and reused by the chat renderer.
"""

PALETTES = {
    "dark": {
        "bg": "#0a0611",
        "surface": "#120c1d",
        "card": "#1a1128",
        "card_alt": "#241936",
        "text": "#f6eefb",
        "muted": "#a795b8",
        "accent": "#ff7ebd",
        "accent_strong": "#ffa6d2",
        "accent_dim": "#6d3557",
        "accent_2": "#b79cf5",
        "accent_2_dim": "#4a3a6b",
        "border": "#352747",
        "border_bright": "#543c70",
        "success": "#7fe3b0",
        "warning": "#ffc98a",
        "error": "#ff8f9c",
        "code_bg": "#0b0713",
        "user_bubble": "#33204a",
        "assistant_bubble": "#1c1429",
        "tool_bubble": "#151021",
        "error_bubble": "#3a1e2a",
        "system_bubble": "#191223",
    },
    "light": {
        "bg": "#f7f0f7",
        "surface": "#ffffff",
        "card": "#f5e9f3",
        "card_alt": "#eedcec",
        "text": "#2c2033",
        "muted": "#75647f",
        "accent": "#c0167f",
        "accent_strong": "#980f65",
        "accent_dim": "#efc9e0",
        "accent_2": "#6d4fd0",
        "accent_2_dim": "#ded5fa",
        "border": "#e6d5e4",
        "border_bright": "#cfb7d6",
        "success": "#2f7d57",
        "warning": "#a4611b",
        "error": "#b23b3b",
        "code_bg": "#f6eff7",
        "user_bubble": "#f9e8f3",
        "assistant_bubble": "#ffffff",
        "tool_bubble": "#f2edf5",
        "error_bubble": "#fbe9e9",
        "system_bubble": "#f5eff5",
    },
}


def palette(name="dark"):
    return dict(PALETTES.get(str(name).casefold(), PALETTES["dark"]))


def stylesheet(name="dark", font_size=14):
    p = palette(name)
    return f"""
QMainWindow, QDialog {{ background-color: {p['bg']}; color: {p['text']}; }}
QWidget {{ color: {p['text']}; }}
QToolTip {{ background-color: {p['card_alt']}; color: {p['text']};
            border: 1px solid {p['border']}; padding: 4px 8px; }}

QTabWidget {{ background: transparent; }}
QTabWidget::pane {{ border: none; background: transparent; top: 0px; }}
QTabWidget::tab-bar {{ left: 14px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {p['muted']};
                padding: 8px 18px; margin: 6px 3px 2px 3px; border-radius: 14px;
                font-weight: 600; }}
QTabBar::tab:selected {{ background-color: {p['card_alt']}; color: {p['accent_strong']}; }}
QTabBar::tab:hover:!selected {{ color: {p['text']}; background-color: {p['card']}; }}

QFrame#Sidebar, QFrame#NavSidebar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {p['card']}, stop:1 {p['surface']});
    border: 1px solid {p['border']}; border-radius: 22px; }}
QFrame#HeaderCard, QFrame#HeroCard, QFrame#GlassCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {p['card']}, stop:1 {p['card_alt']});
    border: 1px solid {p['border_bright']}; border-radius: 24px; }}
QFrame#AvatarStage {{
    background: qradialgradient(cx:0.5, cy:0.42, radius:0.85,
                stop:0 {p['card_alt']}, stop:0.6 {p['card']}, stop:1 {p['surface']});
    border: 1px solid {p['border_bright']}; border-radius: 28px; }}
QFrame#ComposerFrame {{
    background-color: {p['surface']}; border: 1px solid {p['border_bright']};
    border-radius: 18px; }}
QFrame#Divider {{ background-color: {p['border']}; border: none; max-height: 1px;
                  min-height: 1px; }}

QLabel#AppTitle {{ font-size: 26px; font-weight: 700; color: {p['accent_strong']}; }}
QLabel#PageTitle {{ font-size: 22px; font-weight: 700; color: {p['text']}; }}
QLabel#PageSubtitle {{ color: {p['muted']}; font-size: 12px; }}
QLabel#Tagline {{ color: {p['muted']}; font-size: 12px; }}
QLabel#SidebarTitle, QLabel#SectionLabel {{ color: {p['muted']}; font-size: 10px;
    font-weight: 700; letter-spacing: 1.4px; padding: 2px 4px 6px 4px; }}
QLabel#StatusChip {{ background-color: {p['card_alt']}; color: {p['accent_strong']};
                     border: 1px solid {p['border_bright']}; border-radius: 12px;
                     padding: 5px 12px; font-weight: 600; }}
QLabel#StatusLine {{ color: {p['muted']}; font-size: 12px; padding: 2px; }}
QLabel#MutedLine {{ color: {p['muted']}; font-size: 11px; padding: 0 2px; }}
QLabel#HeroName {{ font-size: 30px; font-weight: 700; color: {p['text']}; }}
QLabel#CardTitle {{ font-size: 16px; font-weight: 600; color: {p['text']}; }}
QLabel#HeroMood {{ color: {p['accent_2']}; font-size: 13px; font-weight: 600; }}
QLabel#EmptyHint {{ color: {p['muted']}; font-size: 12px; }}
QLabel#StatValue {{ font-size: 20px; font-weight: 700; color: {p['accent_strong']}; }}
QLabel#StatLabel {{ color: {p['muted']}; font-size: 10px; font-weight: 700;
                    letter-spacing: 1px; }}

QWidget#Page {{ background: transparent; }}
QTextBrowser#ChatView {{ background-color: {p['surface']}; border: 1px solid {p['border']};
                         border-radius: 22px; padding: 6px; }}
QTextEdit#DashboardText {{ background: transparent; border: none; padding: 0; }}
QListWidget#SessionList {{ background-color: transparent; border: none; padding: 0; }}
QListWidget#SessionList::item {{ padding: 10px 10px; margin: 1px 0; border-radius: 12px;
                                 color: {p['muted']}; }}
QListWidget#SessionList::item:hover {{ background-color: {p['card']}; color: {p['text']}; }}
QListWidget#SessionList::item:selected {{ background-color: {p['card_alt']};
                                           color: {p['accent_strong']}; font-weight: 600; }}

QLineEdit, QTextEdit, QTextBrowser, QComboBox, QListWidget {{
    background-color: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 12px; padding: 8px 10px;
    selection-background-color: {p['accent']}; selection-color: #1b0f18;
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
QLineEdit#ComposerInput {{ background: transparent; border: none; padding: 10px 8px;
                           font-size: {int(font_size) + 1}px; }}
QComboBox QAbstractItemView {{ background-color: {p['card']}; color: {p['text']};
                               border: 1px solid {p['border_bright']};
                               border-radius: 10px;
                               selection-background-color: {p['accent_dim']};
                               selection-color: {p['text']}; }}
QListWidget::item {{ padding: 7px; border-radius: 10px; }}
QListWidget::item:selected {{ background-color: {p['card_alt']}; color: {p['accent_strong']}; }}

QTreeWidget {{ background-color: {p['surface']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 14px;
               alternate-background-color: {p['card']}; outline: none;
               selection-background-color: {p['card_alt']};
               selection-color: {p['accent_strong']}; }}
QTreeWidget::item {{ padding: 6px 6px; border-radius: 8px; }}
QTreeWidget::item:selected {{ background-color: {p['card_alt']}; color: {p['accent_strong']}; }}
QHeaderView::section {{ background-color: {p['card']}; color: {p['muted']};
                        border: none; border-bottom: 1px solid {p['border']};
                        padding: 7px 8px; font-weight: 600; }}
QSpinBox {{ background-color: {p['surface']}; color: {p['text']};
            border: 1px solid {p['border']}; border-radius: 10px; padding: 5px 8px; }}

QPushButton {{ background-color: {p['card_alt']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 14px;
               padding: 8px 15px; font-weight: 600; }}
QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent_strong']};
                     background-color: {p['card']}; }}
QPushButton:pressed {{ background-color: {p['surface']}; }}
QPushButton:checked {{ background-color: {p['accent_dim']}; color: {p['text']};
                       border-color: {p['accent']}; }}
QPushButton:disabled {{ color: {p['muted']}; background-color: {p['surface']};
                        border-color: {p['border']}; }}
QPushButton#PrimaryButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                             stop:0 {p['accent']}, stop:1 {p['accent_2']});
                             color: #1b0f18; border: none; font-weight: 700;
                             padding: 9px 20px; border-radius: 15px; }}
QPushButton#PrimaryButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                  stop:0 {p['accent_strong']}, stop:1 {p['accent_2']}); }}
QPushButton#PrimaryButton:disabled {{ background: {p['accent_dim']}; color: {p['muted']}; }}
QPushButton#SoftButton {{ background: transparent; border: 1px solid {p['border']};
                          color: {p['muted']}; border-radius: 14px; }}
QPushButton#SoftButton:hover {{ color: {p['accent_strong']}; border-color: {p['accent']};
                                background-color: {p['card']}; }}
QPushButton#IconButton {{ background-color: {p['card']}; border: 1px solid {p['border']};
                          border-radius: 16px; padding: 8px 10px; font-size: 15px; }}
QPushButton#IconButton:hover {{ border-color: {p['accent']}; color: {p['accent_strong']}; }}
QPushButton#IconButton:checked {{ background-color: {p['accent_dim']};
                                  border-color: {p['accent']}; color: {p['text']}; }}
QPushButton#NavButton {{ background: transparent; border: none; text-align: left;
                         padding: 8px 13px; border-radius: 12px; color: {p['muted']};
                         font-weight: 600; font-size: 12px; }}
QPushButton#NavButton:hover {{ background-color: {p['card']}; color: {p['text']}; }}
QPushButton#NavButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                               stop:0 {p['card_alt']}, stop:1 {p['card']});
                               color: {p['accent_strong']}; }}
QPushButton#ChipButton {{ background-color: {p['card']}; border: 1px solid {p['border']};
                           border-radius: 13px; padding: 6px 12px; color: {p['muted']};
                           font-size: 11px; font-weight: 600; }}
QPushButton#ChipButton:hover {{ border-color: {p['accent']}; color: {p['accent_strong']}; }}
QPushButton#StopButton {{ color: {p['error']}; border-color: {p['error']};
                          background-color: {p['error_bubble']}; }}
QPushButton#StopButton:hover {{ background-color: {p['error_bubble']};
                                border-color: {p['error']}; color: {p['text']}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px;
                        border: 1px solid {p['border_bright']};
                        background-color: {p['surface']}; }}
QCheckBox::indicator:checked {{ background-color: {p['accent']}; border-color: {p['accent']}; }}

QSlider::groove:horizontal {{ height: 5px; background-color: {p['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px;
                              background-color: {p['accent']}; }}
QSlider::sub-page:horizontal {{ background-color: {p['accent_dim']}; border-radius: 2px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background-color: {p['border_bright']}; border-radius: 5px;
                               min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background-color: {p['accent_dim']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background-color: {p['border']}; border-radius: 5px;
                                 min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QMessageBox {{ background-color: {p['surface']}; }}
QMenu {{ background-color: {p['card']}; color: {p['text']}; border: 1px solid {p['border']}; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {p['accent_dim']}; color: #ffffff; }}
QScrollArea {{ border: none; background: transparent; }}

QWidget#SettingsPage {{ background: transparent; }}
QLabel#SettingsIntro {{ color: {p['muted']}; font-size: 12px;
                        background-color: {p['card']}; border: 1px solid {p['border']};
                        border-radius: 10px; padding: 9px 12px; }}
QFrame#SettingsSection {{ background-color: {p['card']}; border: 1px solid {p['border']};
                          border-radius: 12px; }}
QPushButton#SectionHeader {{ background: transparent; border: none; text-align: left;
                             padding: 11px 14px; border-radius: 11px;
                             font-weight: 700; font-size: 13px; color: {p['text']}; }}
QPushButton#SectionHeader:hover {{ background-color: {p['card_alt']}; color: {p['accent_strong']}; }}
QPushButton#SectionHeader:pressed {{ background-color: {p['card']}; }}
QPushButton#SectionHeader:checked {{ background-color: transparent; color: {p['accent_strong']}; }}
QWidget#SectionBody {{ background: transparent; }}
QLabel#SectionHint {{ color: {p['muted']}; font-size: 11px; }}
QPushButton#KeyCaptureButton {{ font-family: "Cascadia Mono", "Consolas", monospace;
                                padding: 6px 12px; min-width: 96px; }}
QPushButton#KeyCaptureButton[capturing="true"] {{ border: 1px dashed {p['accent']};
                                                  color: {p['accent_strong']};
                                                  background-color: {p['card_alt']}; }}
"""
