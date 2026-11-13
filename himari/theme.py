"""Application palette and stylesheet.

Kept free of Qt imports so it can be tested and reused by the chat renderer.
"""

PALETTES = {
    "dark": {
        "bg": "#120f17",
        "surface": "#1a1521",
        "card": "#231c2c",
        "card_alt": "#2c2336",
        "text": "#f3eaf6",
        "muted": "#a99ab4",
        "accent": "#e08bb5",
        "accent_strong": "#f2a7cc",
        "accent_dim": "#7c4a63",
        "border": "#3a2d45",
        "success": "#7bd8a4",
        "warning": "#ffc17a",
        "error": "#ff8a8a",
        "code_bg": "#100d15",
        "user_bubble": "#2d2238",
        "assistant_bubble": "#201926",
        "tool_bubble": "#19151f",
        "error_bubble": "#382029",
        "system_bubble": "#1d1a22",
    },
    "light": {
        "bg": "#f7f1f6",
        "surface": "#ffffff",
        "card": "#f3e7ef",
        "card_alt": "#eadbe6",
        "text": "#2a2030",
        "muted": "#74647d",
        "accent": "#b45182",
        "accent_strong": "#8f3c66",
        "accent_dim": "#e7c4d5",
        "border": "#e3d2de",
        "success": "#2f7d57",
        "warning": "#a4611b",
        "error": "#b23b3b",
        "code_bg": "#f4eef5",
        "user_bubble": "#f6e7ef",
        "assistant_bubble": "#ffffff",
        "tool_bubble": "#f1edf3",
        "error_bubble": "#fbe9e9",
        "system_bubble": "#f4eff4",
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

QTabWidget::pane {{ border: 1px solid {p['border']}; background-color: {p['surface']};
                    border-radius: 12px; top: -1px; }}
QTabWidget::tab-bar {{ left: 10px; }}
QTabBar::tab {{ background: transparent; color: {p['muted']};
                padding: 8px 18px; margin: 4px 2px 0 2px; border-radius: 8px; }}
QTabBar::tab:selected {{ background-color: {p['card']}; color: {p['accent_strong']};
                         font-weight: 600; }}
QTabBar::tab:hover {{ color: {p['text']}; }}

QFrame#HeaderCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 {p['card']}, stop:1 {p['card_alt']});
                     border: 1px solid {p['border']}; border-radius: 16px; }}
QFrame#Sidebar {{ background-color: {p['surface']}; border: 1px solid {p['border']};
                  border-radius: 12px; }}
QLabel#AppTitle {{ font-size: 24px; font-weight: 700; color: {p['accent_strong']}; }}
QLabel#Tagline {{ color: {p['muted']}; font-size: 12px; }}
QLabel#SidebarTitle {{ color: {p['muted']}; font-size: 10px; font-weight: 700;
                       letter-spacing: 1px; padding: 2px 4px 6px 4px; }}
QLabel#StatusChip {{ background-color: {p['card_alt']}; color: {p['accent']};
                     border-radius: 9px; padding: 5px 11px; font-weight: 600; }}
QLabel#StatusLine {{ color: {p['muted']}; font-size: 12px; padding: 2px; }}
QLabel#MutedLine {{ color: {p['muted']}; font-size: 11px; padding: 0 2px; }}

QTextBrowser#ChatView {{ background-color: {p['surface']}; border: 1px solid {p['border']};
                         border-radius: 12px; padding: 6px; }}
QListWidget#SessionList {{ background-color: transparent; border: none; padding: 0; }}
QListWidget#SessionList::item {{ padding: 9px 8px; border-radius: 7px; color: {p['muted']}; }}
QListWidget#SessionList::item:hover {{ background-color: {p['card']}; color: {p['text']}; }}
QListWidget#SessionList::item:selected {{ background-color: {p['card_alt']};
                                           color: {p['accent_strong']}; font-weight: 600; }}

QLineEdit, QTextEdit, QTextBrowser, QComboBox, QListWidget {{
    background-color: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px; padding: 6px;
    selection-background-color: {p['accent']}; selection-color: #ffffff;
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
QComboBox QAbstractItemView {{ background-color: {p['card']}; color: {p['text']};
                               selection-background-color: {p['accent_dim']};
                               selection-color: #ffffff; }}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background-color: {p['card_alt']}; color: {p['accent_strong']}; }}

QPushButton {{ background-color: {p['card_alt']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 8px;
               padding: 7px 13px; }}
QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent_strong']}; }}
QPushButton:pressed {{ background-color: {p['card']}; }}
QPushButton:checked {{ background-color: {p['accent_dim']}; color: #ffffff;
                       border-color: {p['accent']}; }}
QPushButton:disabled {{ color: {p['muted']}; background-color: {p['surface']}; }}
QPushButton#PrimaryButton {{ background-color: {p['accent']}; color: #1b1017;
                             border: none; font-weight: 700; padding: 8px 18px; }}
QPushButton#PrimaryButton:hover {{ background-color: {p['accent_strong']}; }}
QPushButton#PrimaryButton:disabled {{ background-color: {p['accent_dim']}; color: {p['muted']}; }}
QPushButton#StopButton {{ color: {p['error']}; border-color: {p['error']}; }}
QPushButton#StopButton:hover {{ background-color: {p['error_bubble']}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
                        border: 1px solid {p['border']}; background-color: {p['surface']}; }}
QCheckBox::indicator:checked {{ background-color: {p['accent']}; border-color: {p['accent']}; }}

QSlider::groove:horizontal {{ height: 5px; background-color: {p['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px;
                              background-color: {p['accent']}; }}
QSlider::sub-page:horizontal {{ background-color: {p['accent_dim']}; border-radius: 2px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background-color: {p['border']}; border-radius: 5px;
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
