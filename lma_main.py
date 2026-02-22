"""
LMA - Local Audio Sample Manager [2026.1.10 updated]
================================

MIGRATION NOTE:

This application merges the UI/UX design of 'LMA_0.0.2_GUI_test' with the
performance architecture of 'lma_app'.

Technical Changes:
1. Framework: Migrated from PyQt5 to PyQt6 (Current Standard).
2. Database: Replaced JSON indexing with SQLite for high-performance querying.
3. Audio: Replaced Pygame with QtMultimedia (Native System Audio).
4. Threading: Implemented QThread for non-blocking file scanning.
5. Drag & Drop: Preserved custom logic for DAW compatibility.
"""

import sys
import os
import json
import sqlite3
import shutil
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog,
                             QLineEdit, QLabel, QHBoxLayout, QRadioButton, QButtonGroup,
                             QSlider, QMenu, QTableWidget, QTableWidgetItem, QHeaderView,
                             QDialog, QTabWidget, QMessageBox, QAbstractItemView, QFormLayout,
                             QComboBox, QSpinBox, QCheckBox, QFrame, QAbstractSpinBox)
from PyQt6.QtCore import Qt, QUrl, QMimeData, QTimer, QThread, pyqtSignal, QStandardPaths, QEvent
from PyQt6.QtGui import QDrag, QFont, QIcon, QAction, QColor, QPalette, QDesktopServices
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# Import Parsers
from sample_parser import scan_folder
from midi_parser import scan_midi_folder
from music_key import normalize_key_query


APP_NAME = "LMA"
APP_VERSION = "2026.2.22"
APP_GITHUB_URL = "https://github.com/Kircerta/LocalAudioSampleManager"


# --- Database Manager (SQLite) ---
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        self.connect()
        self.init_tables()

    def connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def init_tables(self):
        cur = self.conn.cursor()
        # Samples Table
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS samples
                    (
                        path
                        TEXT
                        PRIMARY
                        KEY,
                        filename
                        TEXT,
                        bpm
                        INTEGER,
                        key_signature
                        TEXT,
                        sound_type
                        TEXT,
                        form
                        TEXT,
                        duration
                        TEXT,
                        is_favorite
                        INTEGER
                        DEFAULT
                        0
                    )
                    """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_filename ON samples(filename)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_bpm ON samples(bpm)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_key ON samples(key_signature)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_form ON samples(form)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_favorite ON samples(is_favorite)")

        # MIDI Table
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS midi
                    (
                        path
                        TEXT
                        PRIMARY
                        KEY,
                        filename
                        TEXT,
                        bpm
                        INTEGER,
                        key_signature
                        TEXT,
                        is_favorite
                        INTEGER
                        DEFAULT
                        0
                    )
                    """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_midi_filename ON midi(filename)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_midi_bpm ON midi(bpm)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_midi_key ON midi(key_signature)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_midi_favorite ON midi(is_favorite)")
        self.conn.commit()

    def replace_samples(self, samples_data):
        favorite_paths = {
            row["path"] for row in self.conn.execute(
                "SELECT path FROM samples WHERE is_favorite = 1"
            ).fetchall()
        }
        data_tuples = [
            (
                s["path"], s["filename"], s.get("bpm"),
                s.get("key"), s.get("type"), s.get("form"),
                s.get("time"), 1 if s["path"] in favorite_paths else 0
            ) for s in samples_data
        ]
        sql = """
              INSERT INTO samples
            (path, filename, bpm, key_signature, sound_type, form, duration, is_favorite)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
              """
        with self.conn:
            self.conn.execute("DELETE FROM samples")
            if data_tuples:
                self.conn.executemany(sql, data_tuples)

    def replace_midi(self, midi_data):
        favorite_paths = {
            row["path"] for row in self.conn.execute(
                "SELECT path FROM midi WHERE is_favorite = 1"
            ).fetchall()
        }
        data_tuples = [
            (
                s["path"], s["filename"], s.get("bpm"),
                s.get("key"), 1 if s["path"] in favorite_paths else 0
            )
            for s in midi_data
        ]
        sql = """
              INSERT INTO midi
            (path, filename, bpm, key_signature, is_favorite)
            VALUES (?, ?, ?, ?, ?)
              """
        with self.conn:
            self.conn.execute("DELETE FROM midi")
            if data_tuples:
                self.conn.executemany(sql, data_tuples)

    def search_samples(self, keywords, bpm_min, bpm_max, key, form, show_favorites_only, limit=2000):
        limit = max(100, min(int(limit), 20000))
        query = "SELECT * FROM samples WHERE 1=1"
        params = []

        if keywords:
            for kw in keywords:
                query += " AND lower(filename) LIKE ?"
                params.append(f"%{kw.lower()}%")

        if bpm_min is not None:
            query += " AND bpm >= ?"
            params.append(bpm_min)

        if bpm_max is not None:
            query += " AND bpm <= ?"
            params.append(bpm_max)

        if key:
            normalized_key = normalize_key_query(key)
            if normalized_key is None:
                query += " AND 1=0"
            else:
                query += " AND key_signature = ?"
                params.append(normalized_key)

        if form and form != 'all':
            query += " AND form = ?"
            params.append(form)

        if show_favorites_only:
            query += " AND is_favorite = 1"

        query += " ORDER BY filename LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def search_midi(self, keywords, bpm_min, bpm_max, key, show_favorites_only, limit=2000):
        limit = max(100, min(int(limit), 20000))
        query = "SELECT * FROM midi WHERE 1=1"
        params = []

        if keywords:
            for kw in keywords:
                query += " AND lower(filename) LIKE ?"
                params.append(f"%{kw.lower()}%")

        if bpm_min is not None:
            query += " AND bpm >= ?"
            params.append(bpm_min)

        if bpm_max is not None:
            query += " AND bpm <= ?"
            params.append(bpm_max)

        if key:
            normalized_key = normalize_key_query(key)
            if normalized_key is None:
                query += " AND 1=0"
            else:
                query += " AND key_signature = ?"
                params.append(normalized_key)

        if show_favorites_only:
            query += " AND is_favorite = 1"

        query += " ORDER BY filename LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def toggle_favorite(self, table, path):
        cur = self.conn.execute(f"SELECT is_favorite FROM {table} WHERE path = ?", (path,))
        row = cur.fetchone()
        if row:
            new_status = 0 if row['is_favorite'] == 1 else 1
            with self.conn:
                self.conn.execute(f"UPDATE {table} SET is_favorite = ? WHERE path = ?", (new_status, path))
            return True
        return False


# --- Scanning Worker ---
class ScanWorker(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, folder_path, mode, db_manager):
        super().__init__()
        self.folder_path = folder_path
        self.mode = mode
        self.db = db_manager

    def run(self):
        if not self.folder_path or not os.path.exists(self.folder_path):
            return

        self.progress_signal.emit(f"Scanning...")
        entries = []
        try:
            if self.mode == 'sample':
                entries = scan_folder(self.folder_path)
                self.db.replace_samples(entries)
            elif self.mode == 'midi':
                entries = scan_midi_folder(self.folder_path)
                self.db.replace_midi(entries)
            self.progress_signal.emit(f"Indexed {len(entries)} files")
        except Exception as e:
            print(f"Scan Error: {e}")

        self.progress_signal.emit("Ready")
        self.finished_signal.emit()


# --- Draggable Table Widget ---
class DraggableTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setFont(QFont("Arial", 10))
        self.setAlternatingRowColors(True)

    def startDrag(self, supportedActions):
        selected_rows = self.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        filename_item = self.item(row, 1)
        if not filename_item:
            return

        filepath = filename_item.data(Qt.ItemDataRole.UserRole)
        if not filepath: return

        # Create temp file for drag compatibility
        temp_dir = tempfile.gettempdir()
        temp_copy = os.path.join(temp_dir, os.path.basename(filepath))

        try:
            shutil.copy(filepath, temp_copy)
        except Exception as e:
            print(f"Error copying file for drag: {e}")
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(temp_copy)])
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

        def cleanup_temp_file():
            try:
                if os.path.exists(temp_copy):
                    os.remove(temp_copy)
            except:
                pass

        QTimer.singleShot(5000, cleanup_temp_file)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Follow System", "system")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        current_theme_index = max(0, self.theme_combo.findData(self.parent_app.theme_mode))
        self.theme_combo.setCurrentIndex(current_theme_index)

        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(100, 20000)
        self.max_results_spin.setSingleStep(100)
        self.max_results_spin.setValue(self.parent_app.max_results)
        self.max_results_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        self.default_volume_spin = QSpinBox()
        self.default_volume_spin.setRange(0, 100)
        self.default_volume_spin.setValue(self.parent_app.volume_slider.value())
        self.default_volume_spin.setSuffix("%")
        self.default_volume_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        self.hide_title_checkbox = QCheckBox("Hide title text in macOS title bar")
        self.hide_title_checkbox.setChecked(self.parent_app.hide_title_text)
        if sys.platform != "darwin":
            self.hide_title_checkbox.setEnabled(False)

        open_data_btn = QPushButton("Open Data Folder")
        open_data_btn.clicked.connect(self.open_data_folder)

        form.addRow("Theme", self.theme_combo)
        form.addRow("Max Search Results", self.max_results_spin)
        form.addRow("Default Preview Volume", self.default_volume_spin)
        form.addRow("Window", self.hide_title_checkbox)
        form.addRow("Data", open_data_btn)
        layout.addLayout(form)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        about_label = QLabel(
            """
            <h3>LMA</h3>
            <p><b>Version:</b> {version}</p>
            <p>Local Audio Sample Manager</p>
            <p>PyQt6 / SQLite / Native Audio</p>
            <p><a href="{github}">GitHub Repository</a></p>
            <p><b>Developer:</b> Zixiang Zhang (Alexxon)</p>
            """.format(version=APP_VERSION, github=APP_GITHUB_URL)
        )
        about_label.setOpenExternalLinks(True)
        about_label.setWordWrap(True)
        layout.addWidget(about_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        save_btn = QPushButton("Save")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.parent_app.app_data_dir)))

    def get_settings(self):
        return {
            "theme_mode": self.theme_combo.currentData(),
            "max_results": self.max_results_spin.value(),
            "default_volume": self.default_volume_spin.value(),
            "hide_title_text": self.hide_title_checkbox.isChecked(),
        }


# --- Main Application ---
class SampleManagerApp(QWidget):
    def __init__(self):
        super().__init__()

        # 1. Paths
        self.app_dir = Path(__file__).resolve().parent
        self.app_data_dir = self._ensure_app_data_dir()
        self.db_path = self.app_data_dir / "lma_library.sqlite"
        self.config_file = self.app_data_dir / "lma_config_v2.json"
        self._migrate_legacy_user_data()

        # 2. Database Init
        self.db = DatabaseManager(str(self.db_path))

        # 3. Config State
        self.selected_sample_folder = ''
        self.selected_midi_folder = ''
        self.theme_mode = "system"
        self.max_results = 2000
        self.hide_title_text = True
        self._is_applying_style = False
        self._active_style_mode = None

        # 4. Audio Engine (PyQt6)
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.current_playing_file = None

        # 5. Icon
        if sys.platform == "darwin":
            icon_path = self.app_dir / "LMA.icns"
        else:
            icon_path = self.app_dir / "LMA.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._apply_window_title_visibility()
        self.init_ui()
        self.apply_visual_style()

        # 6. Load State
        self.load_config()

    def _ensure_app_data_dir(self):
        if sys.platform == "darwin":
            data_dir = Path.home() / "Library" / "Application Support" / APP_NAME
        else:
            base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
            data_dir = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME.lower()}"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    def _migrate_legacy_user_data(self):
        legacy_db = self.app_dir / "lma_library.sqlite"
        legacy_config = self.app_dir / "lma_config_v2.json"

        if not self.db_path.exists() and legacy_db.exists():
            shutil.copy2(legacy_db, self.db_path)
        if not self.config_file.exists() and legacy_config.exists():
            shutil.copy2(legacy_config, self.config_file)

    def _apply_window_title_visibility(self):
        if sys.platform == "darwin" and self.hide_title_text:
            self.setWindowTitle("")
        else:
            self.setWindowTitle("LMA")

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)
        self.tabs = QTabWidget()

        # Tabs
        self.sample_tab = self.create_sample_tab()
        self.tabs.addTab(self.sample_tab, "Samples")

        self.midi_tab = self.create_midi_tab()
        self.tabs.addTab(self.midi_tab, "MIDI")

        main_layout.addWidget(self.tabs)

        # Bottom Bar
        bottom_layout = QHBoxLayout()
        vol_label = QLabel("Vol:")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.valueChanged.connect(self.set_volume)

        settings_btn = QPushButton("Settings")
        settings_btn.setFixedWidth(100)
        settings_btn.clicked.connect(self.open_settings)

        bottom_layout.addWidget(vol_label)
        bottom_layout.addWidget(self.volume_slider, 1)
        bottom_layout.addWidget(settings_btn)

        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

        self.set_volume(80)

    def apply_visual_style(self, force=False):
        if self._is_applying_style:
            return

        dark_mode = self._is_dark_mode()
        target_mode = "dark" if dark_mode else "light"
        if not force and self._active_style_mode == target_mode:
            return

        self._is_applying_style = True
        try:
            if dark_mode:
                self.setStyleSheet(self._build_dark_stylesheet())
            else:
                self.setStyleSheet(self._build_light_stylesheet())
            self._active_style_mode = target_mode
        finally:
            self._is_applying_style = False

    def _is_dark_mode(self):
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        palette = QApplication.instance().palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        return window_color.lightness() < 128

    def _build_light_stylesheet(self):
        return """
            QWidget {
                background: #eceef2;
                color: #101418;
                font-family: "SF Pro Text", "Helvetica Neue", "PingFang SC", sans-serif;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #d8dee6;
                border-radius: 10px;
                background: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #e9edf2;
                border: 1px solid #d8dee6;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 110px;
                padding: 8px 14px;
                margin-right: 4px;
                color: #2e3a46;
                font-weight: 500;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f1720;
                font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                background: #dfe6ee;
            }
            QLabel {
                background: transparent;
            }
            QLineEdit {
                background: #ffffff;
                border: 1px solid #d0d7e0;
                border-radius: 8px;
                padding: 7px 10px;
                selection-background-color: #2b6de0;
                selection-color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #2b6de0;
            }
            QComboBox, QSpinBox {
                background: #ffffff;
                border: 1px solid #d0d7e0;
                border-radius: 8px;
                padding: 6px 10px;
            }
            QComboBox:focus, QSpinBox:focus {
                border: 1px solid #2b6de0;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QCheckBox {
                color: #1c2630;
                spacing: 7px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
            QPushButton {
                background: #2b6de0;
                border: 1px solid #235bc0;
                border-radius: 8px;
                color: #ffffff;
                padding: 7px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #2f76f2;
            }
            QPushButton:pressed {
                background: #245ec2;
            }
            QRadioButton {
                spacing: 7px;
                color: #1c2630;
            }
            QRadioButton::indicator {
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 1px solid #a8b5c4;
                background: #ffffff;
            }
            QRadioButton::indicator:checked {
                border: 1px solid #2b6de0;
                background: #2b6de0;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 4px;
                background: #cad3de;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #2b6de0;
                border: 1px solid #245ec2;
                width: 15px;
                margin: -6px 0;
                border-radius: 7px;
            }
            QTableWidget {
                background: #ffffff;
                border: 1px solid #d8dee6;
                border-radius: 8px;
                gridline-color: #edf1f5;
                alternate-background-color: #f8fafc;
                selection-background-color: #dbe8ff;
                selection-color: #0f1720;
            }
            QHeaderView::section {
                background: #eef2f6;
                color: #25303b;
                border: none;
                border-bottom: 1px solid #d8dee6;
                border-right: 1px solid #e2e8ef;
                padding: 6px;
                font-weight: 600;
            }
            QMenu {
                background: #ffffff;
                border: 1px solid #d8dee6;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: #e8f0ff;
                color: #0f1720;
            }
        """

    def _build_dark_stylesheet(self):
        return """
            QWidget {
                background: #1e1f27;
                color: #e5ebf2;
                font-family: "SF Pro Text", "Helvetica Neue", "PingFang SC", sans-serif;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #2e3640;
                border-radius: 10px;
                background: #1d2229;
                top: -1px;
            }
            QTabBar::tab {
                background: #252c35;
                border: 1px solid #323b47;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 110px;
                padding: 8px 14px;
                margin-right: 4px;
                color: #aeb8c5;
                font-weight: 500;
            }
            QTabBar::tab:selected {
                background: #1d2229;
                color: #f3f7fc;
                font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                background: #2a3240;
            }
            QLabel {
                background: transparent;
                color: #d6dde6;
            }
            QLineEdit {
                background: #11151b;
                border: 1px solid #364252;
                border-radius: 8px;
                padding: 7px 10px;
                color: #e4ebf3;
                selection-background-color: #4d8dff;
                selection-color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #4d8dff;
            }
            QComboBox, QSpinBox {
                background: #11151b;
                border: 1px solid #364252;
                border-radius: 8px;
                padding: 6px 10px;
                color: #e4ebf3;
            }
            QComboBox:focus, QSpinBox:focus {
                border: 1px solid #4d8dff;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QCheckBox {
                color: #d8e0ea;
                spacing: 7px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
            QPushButton {
                background: #2f73e8;
                border: 1px solid #2a64cb;
                border-radius: 8px;
                color: #ffffff;
                padding: 7px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #4080ed;
            }
            QPushButton:pressed {
                background: #295fc0;
            }
            QRadioButton {
                spacing: 7px;
                color: #d8e0ea;
            }
            QRadioButton::indicator {
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 1px solid #556172;
                background: #11151b;
            }
            QRadioButton::indicator:checked {
                border: 1px solid #4d8dff;
                background: #4d8dff;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 4px;
                background: #435162;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #4d8dff;
                border: 1px solid #3b73d7;
                width: 15px;
                margin: -6px 0;
                border-radius: 7px;
            }
            QTableWidget {
                background: #11151b;
                border: 1px solid #2e3640;
                border-radius: 8px;
                gridline-color: #202833;
                alternate-background-color: #191f27;
                selection-background-color: #233c68;
                selection-color: #f2f7ff;
            }
            QHeaderView::section {
                background: #222a34;
                color: #d2dbe6;
                border: none;
                border-bottom: 1px solid #2f3946;
                border-right: 1px solid #2b3440;
                padding: 6px;
                font-weight: 600;
            }
            QMenu {
                background: #1d2229;
                border: 1px solid #2f3946;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 6px;
                color: #dce3eb;
            }
            QMenu::item:selected {
                background: #2b436d;
                color: #ffffff;
            }
        """

    def changeEvent(self, event):
        event_type = event.type()
        if (
            not self._is_applying_style
            and self.theme_mode == "system"
            and (
                event_type == QEvent.Type.PaletteChange
                or event_type == QEvent.Type.ApplicationPaletteChange
            )
        ):
            self.apply_visual_style()
        super().changeEvent(event)

    # --- Sample Tab ---
    def create_sample_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        # Folder Selection
        folder_layout = QHBoxLayout()
        folder_btn = QPushButton("Select Folder")
        folder_btn.clicked.connect(self.select_sample_folder)
        rescan_btn = QPushButton("Rescan")
        rescan_btn.clicked.connect(self.rescan_samples)
        self.sample_folder_label = QLabel("No folder selected.")
        folder_layout.addWidget(folder_btn)
        folder_layout.addWidget(rescan_btn)
        folder_layout.addWidget(self.sample_folder_label, 1)
        layout.addLayout(folder_layout)

        # Search Inputs
        search_layout = QHBoxLayout()
        self.sample_keyword_entry = QLineEdit()
        self.sample_keyword_entry.setPlaceholderText("Search...")
        self.sample_key_entry = QLineEdit()
        self.sample_key_entry.setPlaceholderText("Key")

        self.sample_bpm_from = QLineEdit()
        self.sample_bpm_from.setPlaceholderText("BPM From")
        self.sample_bpm_from.setFixedWidth(80)
        self.sample_bpm_to = QLineEdit()
        self.sample_bpm_to.setPlaceholderText("BPM To")
        self.sample_bpm_to.setFixedWidth(80)

        search_layout.addWidget(self.sample_keyword_entry)
        search_layout.addWidget(self.sample_key_entry)
        search_layout.addWidget(self.sample_bpm_from)
        search_layout.addWidget(self.sample_bpm_to)
        layout.addLayout(search_layout)

        # Filters
        bottom_search_layout = QHBoxLayout()
        self.sample_form_filter_group = QButtonGroup(self)
        for i, text in enumerate(["All", "Loop", "One-shot", "Fill", "Favorite"]):
            btn = QRadioButton(text)
            if text == "All": btn.setChecked(True)
            self.sample_form_filter_group.addButton(btn, i)
            bottom_search_layout.addWidget(btn)

        self.sample_form_filter_group.buttonClicked.connect(self.update_sample_results)

        sample_search_btn = QPushButton("Search")
        sample_search_btn.clicked.connect(self.update_sample_results)
        bottom_search_layout.addStretch()
        bottom_search_layout.addWidget(sample_search_btn)
        layout.addLayout(bottom_search_layout)

        # Connections
        self.sample_keyword_entry.returnPressed.connect(self.update_sample_results)
        self.sample_key_entry.returnPressed.connect(self.update_sample_results)
        self.sample_bpm_from.returnPressed.connect(self.update_sample_results)
        self.sample_bpm_to.returnPressed.connect(self.update_sample_results)

        # Table
        self.sample_result_table = DraggableTableWidget()
        self.sample_result_table.setColumnCount(5)
        self.sample_result_table.setHorizontalHeaderLabels(["★", "Filename", "Time", "Key", "BPM"])
        self.sample_result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sample_result_table.setColumnWidth(0, 30)
        self.sample_result_table.setColumnWidth(2, 75)
        self.sample_result_table.setColumnWidth(3, 60)
        self.sample_result_table.setColumnWidth(4, 60)
        self.sample_result_table.verticalHeader().setVisible(False)
        self.sample_result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.sample_result_table.cellClicked.connect(self.handle_sample_click)
        self.sample_result_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sample_result_table.customContextMenuRequested.connect(lambda p: self.show_context_menu(p, 'samples'))

        layout.addWidget(self.sample_result_table)
        return container

    # --- MIDI Tab ---
    def create_midi_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        # Folder
        folder_layout = QHBoxLayout()
        midi_folder_btn = QPushButton("Select Folder")
        midi_folder_btn.clicked.connect(self.select_midi_folder)
        midi_rescan_btn = QPushButton("Rescan")
        midi_rescan_btn.clicked.connect(self.rescan_midi)
        self.midi_folder_label = QLabel("No folder selected.")
        folder_layout.addWidget(midi_folder_btn)
        folder_layout.addWidget(midi_rescan_btn)
        folder_layout.addWidget(self.midi_folder_label, 1)
        layout.addLayout(folder_layout)

        # Search Inputs
        search_layout = QHBoxLayout()
        self.midi_keyword_entry = QLineEdit()
        self.midi_keyword_entry.setPlaceholderText("Search...")
        self.midi_key_entry = QLineEdit()
        self.midi_key_entry.setPlaceholderText("Key")
        self.midi_bpm_from = QLineEdit()
        self.midi_bpm_from.setPlaceholderText("BPM From")
        self.midi_bpm_from.setFixedWidth(80)
        self.midi_bpm_to = QLineEdit()
        self.midi_bpm_to.setPlaceholderText("BPM To")
        self.midi_bpm_to.setFixedWidth(80)

        search_layout.addWidget(self.midi_keyword_entry)
        search_layout.addWidget(self.midi_key_entry)
        search_layout.addWidget(self.midi_bpm_from)
        search_layout.addWidget(self.midi_bpm_to)
        layout.addLayout(search_layout)

        # Filters
        bottom_search_layout = QHBoxLayout()
        self.midi_form_filter_group = QButtonGroup(self)
        for i, text in enumerate(["All", "Favorite"]):
            btn = QRadioButton(text)
            if text == "All": btn.setChecked(True)
            self.midi_form_filter_group.addButton(btn, i)
            bottom_search_layout.addWidget(btn)

        self.midi_form_filter_group.buttonClicked.connect(self.update_midi_results)
        midi_search_btn = QPushButton("Search")
        midi_search_btn.clicked.connect(self.update_midi_results)
        bottom_search_layout.addStretch()
        bottom_search_layout.addWidget(midi_search_btn)
        layout.addLayout(bottom_search_layout)

        # Connections
        self.midi_keyword_entry.returnPressed.connect(self.update_midi_results)
        self.midi_key_entry.returnPressed.connect(self.update_midi_results)

        # Table
        self.midi_result_table = DraggableTableWidget()
        self.midi_result_table.setColumnCount(4)
        self.midi_result_table.setHorizontalHeaderLabels(["★", "Filename", "Key", "BPM"])
        self.midi_result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.midi_result_table.setColumnWidth(0, 30)
        self.midi_result_table.setColumnWidth(2, 80)
        self.midi_result_table.setColumnWidth(3, 80)
        self.midi_result_table.verticalHeader().setVisible(False)
        self.midi_result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.midi_result_table.cellClicked.connect(self.handle_midi_click)
        self.midi_result_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.midi_result_table.customContextMenuRequested.connect(lambda p: self.show_context_menu(p, 'midi'))

        layout.addWidget(self.midi_result_table)
        return container

    # --- Actions: Folder Selection ---
    def select_sample_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.selected_sample_folder = folder
            self.sample_folder_label.setText(folder)
            self.save_config()
            self.start_worker(folder, 'sample')

    def rescan_samples(self):
        if self.selected_sample_folder:
            self.start_worker(self.selected_sample_folder, 'sample')

    def select_midi_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.selected_midi_folder = folder
            self.midi_folder_label.setText(folder)
            self.save_config()
            self.start_worker(folder, 'midi')

    def rescan_midi(self):
        if self.selected_midi_folder:
            self.start_worker(self.selected_midi_folder, 'midi')

    def start_worker(self, folder, mode):
        self.worker = ScanWorker(folder, mode, self.db)
        lbl = self.sample_folder_label if mode == 'sample' else self.midi_folder_label
        self.worker.progress_signal.connect(lambda s: lbl.setText(f"{folder} ({s})"))

        if mode == 'sample':
            self.worker.finished_signal.connect(self.update_sample_results)
            self.worker.finished_signal.connect(lambda: lbl.setText(folder))
        else:
            self.worker.finished_signal.connect(self.update_midi_results)
            self.worker.finished_signal.connect(lambda: lbl.setText(folder))

        self.worker.start()

    # --- Actions: Search ---
    def update_sample_results(self):
        keywords = self.sample_keyword_entry.text().strip().lower().split()
        key = self.sample_key_entry.text().strip()

        try:
            bpm_min = int(self.sample_bpm_from.text()) if self.sample_bpm_from.text() else None
            bpm_max = int(self.sample_bpm_to.text()) if self.sample_bpm_to.text() else None
        except ValueError:
            bpm_min = bpm_max = None

        btn = self.sample_form_filter_group.checkedButton()
        selected_text = btn.text().lower() if btn else "all"

        form = selected_text
        fav_only = False

        if selected_text == "favorite":
            fav_only = True
            form = "all"

        results = self.db.search_samples(
            keywords, bpm_min, bpm_max, key, form, fav_only, self.max_results
        )

        self.sample_result_table.setRowCount(0)
        self.sample_result_table.setRowCount(len(results))

        for i, row_data in enumerate(results):
            fav_icon = "★" if row_data['is_favorite'] else ""
            self.sample_result_table.setItem(i, 0, QTableWidgetItem(fav_icon))
            self.sample_result_table.item(i, 0).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            fname_item = QTableWidgetItem(row_data['filename'])
            fname_item.setData(Qt.ItemDataRole.UserRole, row_data['path'])
            self.sample_result_table.setItem(i, 1, fname_item)

            self.sample_result_table.setItem(i, 2, QTableWidgetItem(str(row_data.get('duration', '--'))))
            self.sample_result_table.setItem(i, 3, QTableWidgetItem(str(row_data.get('key_signature', '--'))))

            bpm_val = str(row_data.get('bpm')) if row_data.get('bpm') else '--'
            self.sample_result_table.setItem(i, 4, QTableWidgetItem(bpm_val))

    def update_midi_results(self):
        keywords = self.midi_keyword_entry.text().strip().lower().split()
        key = self.midi_key_entry.text().strip()

        try:
            bpm_min = int(self.midi_bpm_from.text()) if self.midi_bpm_from.text() else None
            bpm_max = int(self.midi_bpm_to.text()) if self.midi_bpm_to.text() else None
        except ValueError:
            bpm_min = bpm_max = None

        btn = self.midi_form_filter_group.checkedButton()
        fav_only = (btn.text().lower() == "favorite") if btn else False

        results = self.db.search_midi(
            keywords, bpm_min, bpm_max, key, fav_only, self.max_results
        )

        self.midi_result_table.setRowCount(0)
        self.midi_result_table.setRowCount(len(results))

        for i, row_data in enumerate(results):
            fav_icon = "★" if row_data['is_favorite'] else ""
            self.midi_result_table.setItem(i, 0, QTableWidgetItem(fav_icon))
            self.midi_result_table.item(i, 0).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            fname_item = QTableWidgetItem(row_data['filename'])
            fname_item.setData(Qt.ItemDataRole.UserRole, row_data['path'])
            self.midi_result_table.setItem(i, 1, fname_item)

            self.midi_result_table.setItem(i, 2, QTableWidgetItem(str(row_data.get('key_signature', '--'))))

            bpm_val = str(row_data.get('bpm')) if row_data.get('bpm') else '--'
            self.midi_result_table.setItem(i, 3, QTableWidgetItem(bpm_val))

    # --- Actions: Playback & Context Menu ---
    def handle_sample_click(self, row, col):
        filepath = self.sample_result_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        if not filepath or not os.path.exists(filepath):
            return

        if self.current_playing_file == filepath and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.stop()
        else:
            self.current_playing_file = filepath
            self.play_sound(filepath)

    def handle_midi_click(self, row, col):
        self.player.stop()

    def play_sound(self, filepath):
        self.player.setSource(QUrl.fromLocalFile(filepath))
        self.player.play()

    def set_volume(self, value):
        self.audio_output.setVolume(value / 100.0)

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        settings = dialog.get_settings()
        self.theme_mode = settings["theme_mode"]
        self.max_results = self._clamp_max_results(settings["max_results"])
        self.hide_title_text = bool(settings["hide_title_text"])
        self._apply_window_title_visibility()

        target_volume = settings["default_volume"]
        if self.volume_slider.value() != target_volume:
            self.volume_slider.setValue(target_volume)
        else:
            self.set_volume(target_volume)

        self.save_config()
        self.apply_visual_style()
        self.update_sample_results()
        self.update_midi_results()

    @staticmethod
    def _clamp_max_results(value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 2000
        return max(100, min(parsed, 20000))

    def show_context_menu(self, pos, table_type):
        table = self.sample_result_table if table_type == 'samples' else self.midi_result_table
        item = table.itemAt(pos)
        if not item: return

        row = item.row()
        path = table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        is_fav = (table.item(row, 0).text() == "★")

        menu = QMenu()
        action_text = "Remove from Collection" if is_fav else "Add to Collection"
        action = menu.addAction(action_text)

        res = menu.exec(table.mapToGlobal(pos))

        if res == action:
            self.db.toggle_favorite(table_type, path)
            if table_type == 'samples':
                self.update_sample_results()
            else:
                self.update_midi_results()

    # --- Config ---
    def load_config(self):
        if self.config_file.exists():
            try:
                with self.config_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.selected_sample_folder = data.get("sample_folder", "")
                    self.selected_midi_folder = data.get("midi_folder", "")
                    configured_theme = data.get("theme_mode", "system")
                    if configured_theme in {"system", "light", "dark"}:
                        self.theme_mode = configured_theme
                    self.max_results = self._clamp_max_results(data.get("max_results", 2000))
                    self.hide_title_text = bool(data.get("hide_title_text", True))
                    startup_volume = data.get("default_volume", self.volume_slider.value())
                    if isinstance(startup_volume, int):
                        startup_volume = max(0, min(startup_volume, 100))
                    else:
                        startup_volume = self.volume_slider.value()

                    self._apply_window_title_visibility()
                    self.apply_visual_style()
                    self.volume_slider.setValue(startup_volume)

                    if self.selected_sample_folder:
                        self.sample_folder_label.setText(self.selected_sample_folder)
                        self.update_sample_results()
                    if self.selected_midi_folder:
                        self.midi_folder_label.setText(self.selected_midi_folder)
                        self.update_midi_results()
            except:
                pass

    def save_config(self):
        data = {
            "sample_folder": self.selected_sample_folder,
            "midi_folder": self.selected_midi_folder,
            "theme_mode": self.theme_mode,
            "max_results": self.max_results,
            "hide_title_text": self.hide_title_text,
            "default_volume": self.volume_slider.value(),
        }
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with self.config_file.open('w', encoding='utf-8') as f:
            json.dump(data, f)


if __name__ == '__main__':
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)

    window = SampleManagerApp()
    window.resize(850, 650)
    window.show()

    sys.exit(app.exec())
