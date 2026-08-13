from __future__ import annotations

from functools import partial
import html
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

from PySide6.QtCore import QLocale, QSize, Qt, QStandardPaths
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .godot_variant import TaggedValue, is_color_value
from .localization import resolve_translation_key
from .mods import (
    MissingDependenciesError,
    ModInfo,
    RepositoryMod,
    compare_versions,
    extract_dependency_ids_from_manifest,
    fetch_latest_manifest,
    fetch_repository_catalog,
    get_runtime_value,
    install_mod_from_path,
    install_mod_from_url,
    load_runtime_config,
    save_runtime_value,
    scan_mods,
    toggle_mod,
)
from .steam import discover_delta_v_install, discover_delta_v_user_dir


class ModListRowWidget(QWidget):
    def __init__(self, title: str, buttons: QWidget) -> None:
        super().__init__()
        self._full_title = title
        self._buttons = buttons

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.title_label = QLabel(self._full_title)
        self.title_label.setToolTip(self._full_title)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(0)
        layout.addWidget(self.title_label, 1)

        self._buttons.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._buttons, 0, Qt.AlignmentFlag.AlignRight)

    def _update_title_elide(self) -> None:
        layout = self.layout()
        if not isinstance(layout, QHBoxLayout):
            return
        available = self.width()
        available -= layout.contentsMargins().left() + layout.contentsMargins().right()
        available -= self._buttons.sizeHint().width()
        available -= layout.spacing()
        available = max(available, 10)
        self.title_label.setText(self.title_label.fontMetrics().elidedText(self._full_title, Qt.TextElideMode.ElideRight, available))

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._update_title_elide()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._update_title_elide()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MME - ModMenuExt")
        self.resize(1380, 860)
        self.settings_path = self._settings_file_path()

        self.game_dir: Path | None = None
        self.user_dir: Path | None = None
        self.mods_dir: Path | None = None
        self.mods_dir_override: Path | None = None
        self.config_path: Path | None = None
        self.mods: list[ModInfo] = []
        self.repository_mods: list[RepositoryMod] = []
        self.runtime_config: dict[str, dict[str, Any]] = {}
        self.current_locale = QLocale.system().name()
        self.shared_translations: dict[str, dict[str, Any]] = {}
        self.shared_master_locale = "en"
        self.dark_mode = True
        self.auto_detect_paths_on_startup = True
        self.game_dir_edit: QLineEdit | None = None
        self.user_dir_edit: QLineEdit | None = None
        self.mods_dir_edit: QLineEdit | None = None
        self._load_app_settings()

        self._build_ui()
        self._apply_theme()
        if self.auto_detect_paths_on_startup:
            self._autodetect_paths()
        elif self.game_dir is not None or self.user_dir is not None:
            self._sync_paths()
            self.refresh_state()
        else:
            self._sync_paths()
            self.refresh_state()
        self._prompt_create_mods_dir_on_startup()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_column())
        splitter.addWidget(self._build_details_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 900])
        root_layout.addWidget(splitter)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar(self))
        self._build_menus()

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.clear()

        file_menu = menu_bar.addMenu("File")
        install_url_action = QAction("Install From URL", self)
        install_url_action.triggered.connect(self._install_from_url)
        install_zip_action = QAction("Install Zip", self)
        install_zip_action.triggered.connect(self._install_from_file)
        check_dependencies_action = QAction("Check Dependencies", self)
        check_dependencies_action.triggered.connect(self._check_dependencies)
        update_all_action = QAction("Update All", self)
        update_all_action.triggered.connect(self._update_all_mods)
        file_menu.addAction(install_url_action)
        file_menu.addAction(install_zip_action)
        file_menu.addSeparator()
        file_menu.addAction(check_dependencies_action)
        file_menu.addAction(update_all_action)

        properties_menu = menu_bar.addMenu("Properties")
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_state)
        autodetect_action = QAction("Auto Detect Paths", self)
        autodetect_action.triggered.connect(self._autodetect_paths)
        self.auto_detect_startup_action = QAction("Auto Detect Paths On Startup", self)
        self.auto_detect_startup_action.setCheckable(True)
        self.auto_detect_startup_action.setChecked(self.auto_detect_paths_on_startup)
        self.auto_detect_startup_action.triggered.connect(self._toggle_auto_detect_on_startup)
        self.theme_toggle_action = QAction("Dark/Light Mode", self)
        self.theme_toggle_action.setCheckable(True)
        self.theme_toggle_action.triggered.connect(self._toggle_theme)

        paths_menu_action = QAction("Paths Menu", self)
        paths_menu_action.triggered.connect(self._show_paths_popup)

        properties_menu.addAction(refresh_action)
        properties_menu.addAction(self.theme_toggle_action)
        properties_menu.addAction(autodetect_action)
        properties_menu.addAction(self.auto_detect_startup_action)
        properties_menu.addAction(paths_menu_action)

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("heroCard")
        self._set_panel_frame(card)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)

        copy = QVBoxLayout()
        layout.addLayout(copy, 1)

        layout.addStretch(1)
        return card

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._build_mods_panel(), 1)
        return column

    def _show_paths_popup(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Paths Menu")
        dialog.setModal(True)
        dialog.resize(860, 420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        game_edit = QLineEdit()
        game_edit.setReadOnly(True)
        user_edit = QLineEdit()
        user_edit.setReadOnly(True)
        mods_edit = QLineEdit()
        mods_edit.setReadOnly(True)

        def update_fields() -> None:
            game_edit.setText(str(self.game_dir or ""))
            user_edit.setText(str(self.user_dir or ""))
            mods_edit.setText(str(self.mods_dir or ""))

        layout.addWidget(QLabel("Game directory"))
        layout.addWidget(game_edit)

        select_game_button = QPushButton("Select Game Folder")

        def select_game() -> None:
            self._browse_game_dir()
            update_fields()

        select_game_button.clicked.connect(select_game)
        open_game_button = QPushButton("Open Game Folder")

        def open_game() -> None:
            if self.game_dir is None:
                QMessageBox.warning(dialog, "No game folder", "No game folder is currently selected.")
                return
            if not self.game_dir.exists():
                QMessageBox.warning(dialog, "Missing game folder", f"Folder not found:\n{self.game_dir}")
                return
            os.startfile(self.game_dir)

        open_game_button.clicked.connect(open_game)
        game_buttons = QHBoxLayout()
        game_buttons.addWidget(select_game_button)
        game_buttons.addWidget(open_game_button)
        game_buttons.addStretch(1)
        layout.addLayout(game_buttons)

        layout.addWidget(QLabel("User data directory"))
        layout.addWidget(user_edit)

        select_user_button = QPushButton("Select Userdata Folder")

        def select_user() -> None:
            self._browse_user_dir()
            update_fields()

        select_user_button.clicked.connect(select_user)
        open_user_button = QPushButton("Open Userdata Folder")

        def open_user() -> None:
            if self.user_dir is None:
                QMessageBox.warning(dialog, "No userdata folder", "No userdata folder is currently selected.")
                return
            if not self.user_dir.exists():
                QMessageBox.warning(dialog, "Missing userdata folder", f"Folder not found:\n{self.user_dir}")
                return
            os.startfile(self.user_dir)

        open_user_button.clicked.connect(open_user)
        user_buttons = QHBoxLayout()
        user_buttons.addWidget(select_user_button)
        user_buttons.addWidget(open_user_button)
        user_buttons.addStretch(1)
        layout.addLayout(user_buttons)

        layout.addWidget(QLabel("Mods directory"))
        layout.addWidget(mods_edit)

        select_mods_button = QPushButton("Select Mods Folder")

        def select_mods() -> None:
            self._browse_mods_dir()
            update_fields()

        select_mods_button.clicked.connect(select_mods)
        open_mods_button = QPushButton("Open Mods Folder")
        open_mods_button.clicked.connect(self._open_mods_folder)
        mods_buttons = QHBoxLayout()
        mods_buttons.addWidget(select_mods_button)
        mods_buttons.addWidget(open_mods_button)
        mods_buttons.addStretch(1)
        layout.addLayout(mods_buttons)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)

        controls = QHBoxLayout()
        controls.addStretch(1)
        controls.addWidget(close_button)
        layout.addLayout(controls)

        update_fields()
        dialog.exec()

    def _build_paths_box(self) -> QWidget:
        box = QFrame()
        box.setObjectName("sectionCard")
        self._set_panel_frame(box)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Paths")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        game_dir_edit = QLineEdit()
        game_dir_edit.setReadOnly(True)
        user_dir_edit = QLineEdit()
        user_dir_edit.setReadOnly(True)
        mods_dir_edit = QLineEdit()
        mods_dir_edit.setReadOnly(True)

        game_dir_edit.setPlaceholderText("Delta-V install directory")
        user_dir_edit.setPlaceholderText("Delta-V user data directory")
        mods_dir_edit.setPlaceholderText("Mods directory")

        layout.addWidget(self._build_path_row("Game directory", game_dir_edit))
        layout.addWidget(self._build_path_row("User data directory", user_dir_edit))
        layout.addWidget(self._build_path_row("Mods directory", mods_dir_edit))

        game_buttons = QHBoxLayout()
        browse_game_button = QPushButton("Browse Game Folder")
        browse_game_button.clicked.connect(self._browse_game_dir)
        browse_user_button = QPushButton("Browse Userdata Folder")
        browse_user_button.clicked.connect(self._browse_user_dir)
        open_mods_button = QPushButton("Browse Mods Folder")
        open_mods_button.clicked.connect(self._open_mods_folder)
        game_buttons.addWidget(browse_game_button)
        game_buttons.addWidget(browse_user_button)
        game_buttons.addWidget(open_mods_button)
        game_buttons.addStretch(1)

        layout.addLayout(game_buttons)
        return box

    def _build_path_row(self, label_text: str, editor: QLineEdit) -> QWidget:
        card = QFrame()
        card.setObjectName("pathCard")
        self._set_panel_frame(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        label = QLabel(label_text)
        label.setObjectName("pathLabel")
        layout.addWidget(label)
        layout.addWidget(editor)
        return card

    def _build_mods_panel(self) -> QWidget:
        widget = QFrame()
        widget.setObjectName("sectionCard")
        self._set_panel_frame(widget)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        heading_row = QHBoxLayout()
        title = QLabel("Installed Mods")
        title.setObjectName("sectionTitle")
        self.mod_count_label = QLabel("0 mods")
        self.mod_count_label.setObjectName("metaLabel")
        heading_row.addWidget(title)
        heading_row.addStretch(1)
        heading_row.addWidget(self.mod_count_label)
        layout.addLayout(heading_row)

        self.mod_list = QListWidget()
        self.mod_list.setObjectName("modList")
        self.mod_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mod_list.currentItemChanged.connect(self._on_mod_selected)
        self.mod_list.itemDoubleClicked.connect(self._on_mod_double_clicked)
        layout.addWidget(self.mod_list)
        return widget

    def _build_details_panel(self) -> QWidget:
        widget = QFrame()
        widget.setObjectName("sectionCard")
        self._set_panel_frame(widget)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Inspector")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("Review the selected mod or browse the repository.")
        subtitle.setObjectName("metaLabel")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(subtitle)
        layout.addLayout(title_row)

        self.details_tabs = QTabWidget()
        self.details_tabs.setDocumentMode(True)

        mod_tab = QWidget()
        mod_tab_layout = QVBoxLayout(mod_tab)
        mod_tab_layout.setContentsMargins(0, 8, 0, 0)
        mod_tab_layout.setSpacing(12)
        self.summary_box = QTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.setMinimumHeight(170)
        self.summary_box.setObjectName("summaryBox")
        mod_tab_layout.addWidget(self.summary_box)
        self.config_scroll = QScrollArea()
        self.config_scroll.setWidgetResizable(True)
        self.config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.config_container = QWidget()
        self.config_layout = QVBoxLayout(self.config_container)
        self.config_layout.addWidget(QLabel("Select a mod to edit its configs."))
        self.config_layout.addStretch(1)
        self.config_scroll.setWidget(self.config_container)
        mod_tab_layout.addWidget(self.config_scroll)
        self.details_tabs.addTab(mod_tab, "Selected Mod")

        repository_tab = QWidget()
        repository_layout = QVBoxLayout(repository_tab)
        repository_layout.setContentsMargins(0, 8, 0, 0)
        repository_layout.setSpacing(12)
        self.repository_list = QListWidget()
        self.repository_list.setObjectName("repositoryList")
        self.repository_list.currentItemChanged.connect(self._on_repository_selected)
        self.repository_summary = QTextEdit()
        self.repository_summary.setReadOnly(True)
        self.repository_summary.setObjectName("summaryBox")
        self.install_repo_button = QPushButton("Install Selected Repository Mod")
        self.install_repo_button.clicked.connect(self._install_selected_repository_mod)
        self.refresh_repo_button = QPushButton("Refresh Repository")
        self.refresh_repo_button.clicked.connect(self._refresh_repository)
        repo_buttons = QHBoxLayout()
        repo_buttons.addWidget(self.install_repo_button)
        repo_buttons.addWidget(self.refresh_repo_button)
        repository_layout.addWidget(self.repository_list)
        repository_layout.addWidget(self.repository_summary)
        repository_layout.addWidget(self._wrap_layout(repo_buttons))
        self.details_tabs.addTab(repository_tab, "Repository")

        layout.addWidget(self.details_tabs)
        return widget

    def _wrap_layout(self, layout: QHBoxLayout) -> QWidget:
        wrapper = QWidget()
        wrapper.setLayout(layout)
        return wrapper

    def _set_panel_frame(self, frame: QFrame) -> None:
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setFrameShadow(QFrame.Shadow.Raised)
        frame.setLineWidth(1)

    def _autodetect_paths(self) -> None:
        self.game_dir = discover_delta_v_install()
        self.user_dir = discover_delta_v_user_dir()
        self.mods_dir_override = None
        self._sync_paths()
        self.refresh_state()
        self._save_app_settings()

    def _browse_game_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Delta-V install directory")
        if selected:
            self.game_dir = Path(selected)
            self.mods_dir_override = None
            self._sync_paths()
            self.refresh_state()
            self._save_app_settings()

    def _browse_user_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Delta-V user data directory")
        if selected:
            self.user_dir = Path(selected)
            self._sync_paths()
            self.refresh_state()
            self._save_app_settings()

    def _browse_mods_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Delta-V mods directory")
        if selected:
            mods_path = Path(selected)
            self.mods_dir_override = mods_path
            if mods_path.name.casefold() == "mods":
                self.game_dir = mods_path.parent
            self._sync_paths()
            self.refresh_state()
            self._save_app_settings()

    def _settings_file_path(self) -> Path:
        settings_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        if not settings_dir:
            return Path.home() / ".modmenuext" / "settings.json"
        return Path(settings_dir) / "settings.json"

    def _load_app_settings(self) -> None:
        try:
            if not self.settings_path.is_file():
                return
            with self.settings_path.open("r", encoding="utf-8") as handle:
                settings = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return

        cached_game = settings.get("game_dir")
        cached_user = settings.get("user_dir")
        if isinstance(cached_game, str) and cached_game.strip():
            candidate = Path(cached_game)
            if candidate.exists():
                self.game_dir = candidate
        if isinstance(cached_user, str) and cached_user.strip():
            candidate = Path(cached_user)
            if candidate.exists():
                self.user_dir = candidate
        cached_mods = settings.get("mods_dir_override")
        if isinstance(cached_mods, str) and cached_mods.strip():
            candidate = Path(cached_mods)
            if candidate.exists():
                self.mods_dir_override = candidate
        self.dark_mode = bool(settings.get("dark_mode", self.dark_mode))
        self.auto_detect_paths_on_startup = bool(settings.get("auto_detect_paths_on_startup", self.auto_detect_paths_on_startup))

    def _save_app_settings(self) -> None:
        payload = {
            "game_dir": str(self.game_dir) if self.game_dir else "",
            "user_dir": str(self.user_dir) if self.user_dir else "",
            "mods_dir_override": str(self.mods_dir_override) if self.mods_dir_override else "",
            "dark_mode": self.dark_mode,
            "auto_detect_paths_on_startup": self.auto_detect_paths_on_startup,
        }
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.settings_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except OSError:
            return

    def _sync_paths(self) -> None:
        self.mods_dir = self.mods_dir_override or (self.game_dir / "mods" if self.game_dir else None)
        self.config_path = self.user_dir / "cfg" / "Mod_Configurations.cfg" if self.user_dir else None
        if self.game_dir_edit is not None:
            self.game_dir_edit.setText(str(self.game_dir or ""))
        if self.user_dir_edit is not None:
            self.user_dir_edit.setText(str(self.user_dir or ""))
        if self.mods_dir_edit is not None:
            self.mods_dir_edit.setText(str(self.mods_dir or ""))

    def _prompt_create_mods_dir_on_startup(self) -> None:
        if self.mods_dir is None or self.mods_dir.exists():
            return
        answer = QMessageBox.question(
            self,
            "Create Mods Folder?",
            f"The mods folder was not found at:\n{self.mods_dir}\n\nCreate it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.mods_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Create Folder Failed", f"Could not create mods folder:\n{exc}")
            return
        self.statusBar().showMessage("Created mods folder", 3000)
        self._save_app_settings()

    def refresh_state(self) -> None:
        selected_archive_path = self._current_archive_path()
        if self.config_path:
            self.runtime_config = load_runtime_config(self.config_path)
        else:
            self.runtime_config = {}
        self.mods = scan_mods(self.mods_dir) if self.mods_dir else []
        self._rebuild_shared_translations()
        self._populate_mod_list(selected_archive_path)
        self.mod_count_label.setText(f"{len(self.mods)} mod{'s' if len(self.mods) != 1 else ''}")
        self.statusBar().showMessage("State refreshed", 3000)

    def _rebuild_shared_translations(self) -> None:
        shared: dict[str, dict[str, Any]] = {}
        master_locale = "en"
        for mod in self.mods:
            if not mod.enabled:
                continue
            if mod.master_locale:
                master_locale = mod.master_locale
            for locale, locale_entries in mod.translations.items():
                shared.setdefault(locale, {}).update(locale_entries)
        self.shared_translations = shared
        self.shared_master_locale = master_locale

    def _populate_mod_list(self, selected_archive_path: Path | None = None) -> None:
        self.mod_list.clear()
        target_row = -1
        for mod in self.mods:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, mod.archive_path)
            self.mod_list.addItem(item)
            row_widget = self._build_mod_list_row(mod)
            item.setSizeHint(QSize(0, row_widget.sizeHint().height()))
            self.mod_list.setItemWidget(item, row_widget)
            if selected_archive_path is not None and mod.archive_path == selected_archive_path:
                target_row = self.mod_list.count() - 1
        if self.mod_list.count() > 0:
            self.mod_list.setCurrentRow(target_row if target_row >= 0 else 0)
        else:
            self._set_formatted_text(self.summary_box, "No mod selected.")
            self._show_mod_details(None)

    def _build_mod_list_row(self, mod: ModInfo) -> QWidget:
        status = "[ON]" if mod.enabled else "[OFF]"
        title = f"{status} {mod.display_name}"

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(6)

        toggle_button = QPushButton()
        toggle_button.clicked.connect(partial(self._toggle_mod_by_archive, mod.archive_path))
        toggle_button.setToolTip("Disable mod" if mod.enabled else "Enable mod")
        toggle_button.setFixedSize(28, 28)
        toggle_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton if not mod.enabled else QStyle.StandardPixmap.SP_DialogNoButton))

        update_button = QPushButton()
        update_button.clicked.connect(partial(self._check_mod_update_by_archive, mod.archive_path))
        update_button.setToolTip("Check for update")
        update_button.setFixedSize(28, 28)
        update_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))

        delete_button = QPushButton()
        delete_button.clicked.connect(partial(self._delete_mod_by_archive, mod.archive_path))
        delete_button.setToolTip("Delete mod archive")
        delete_button.setFixedSize(28, 28)
        delete_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))

        buttons_layout.addWidget(toggle_button)
        buttons_layout.addWidget(update_button)
        buttons_layout.addWidget(delete_button)
        return ModListRowWidget(title, buttons)

    def _refresh_repository(self) -> None:
        try:
            self.repository_mods = fetch_repository_catalog()
        except Exception as exc:
            QMessageBox.critical(self, "Repository refresh failed", str(exc))
            return
        self.repository_list.clear()
        installed_ids = {mod.mod_id for mod in self.mods if mod.mod_id}
        for repo_mod in self.repository_mods:
            suffix = " [Installed]" if repo_mod.mod_id in installed_ids else ""
            item = QListWidgetItem(f"{repo_mod.name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, repo_mod.mod_id)
            self.repository_list.addItem(item)
        if self.repository_list.count() > 0:
            self.repository_list.setCurrentRow(0)
        else:
            self._set_formatted_text(self.repository_summary, "No repository mods found.")

    def _on_mod_selected(self, current: QListWidgetItem | None) -> None:
        if current is None:
            self._show_mod_details(None)
            return
        archive_path = current.data(Qt.ItemDataRole.UserRole)
        mod = next((entry for entry in self.mods if entry.archive_path == archive_path), None)
        self._show_mod_details(mod)

    def _on_mod_double_clicked(self, _: QListWidgetItem) -> None:
        self._toggle_selected_mod()

    def _show_mod_details(self, mod: ModInfo | None) -> None:
        self._clear_config_layout()
        if mod is None:
            self._set_formatted_text(self.summary_box, "No mod selected.")
            self.config_layout.addWidget(QLabel("Select a mod to edit its configs."))
            self.config_layout.addStretch(1)
            return

        summary_lines = [
            f"Name: {self._translate_for_mod(mod, mod.display_name)}",
            f"ID: {mod.mod_id or '-'}",
            f"Version: {mod.version or '-'}",
            f"Author: {self._translate_for_mod(mod, mod.author or '-')}",
            f"Archive: {mod.archive_path.name}",
            f"Enabled: {'yes' if mod.enabled else 'no'}",
            "",
            self._translate_for_mod(mod, mod.description) or "No manifest description found.",
        ]
        self._set_formatted_text(self.summary_box, "\n".join(summary_lines))

        if not mod.configs:
            self.config_layout.addWidget(QLabel("This mod does not expose ModMenu2 configs."))
            self.config_layout.addStretch(1)
            return

        for section_name, entries in sorted(mod.configs.items(), key=lambda item: str(item[0]).casefold()):
            section_box = QGroupBox(self._translate_for_mod(mod, section_name))
            section_layout = QFormLayout(section_box)
            sorted_entries = sorted(entries.items(), key=lambda item: int(item[1].get("display_order_position", 99999)))
            for entry_key, metadata in sorted_entries:
                row_widget = self._create_config_widget(mod, section_name, entry_key, metadata)
                description = self._translate_for_mod(mod, metadata.get("description", ""))
                if description:
                    row_widget.setToolTip(description)
                label = self._translate_for_mod(mod, metadata.get("name", entry_key))
                section_layout.addRow(str(label), row_widget)
            self.config_layout.addWidget(section_box)
        self.config_layout.addStretch(1)

    def _on_repository_selected(self, current: QListWidgetItem | None) -> None:
        if current is None:
            self._set_formatted_text(self.repository_summary, "No repository mod selected.")
            return
        mod_id = current.data(Qt.ItemDataRole.UserRole)
        repo_mod = next((entry for entry in self.repository_mods if entry.mod_id == mod_id), None)
        if repo_mod is None:
            self._set_formatted_text(self.repository_summary, "No repository mod selected.")
            return
        summary = [
            f"Name: {repo_mod.name}",
            f"ID: {repo_mod.mod_id}",
            f"Author: {repo_mod.author or '-'}",
            f"Zip: {repo_mod.zip_name or '-'}",
            "",
            repo_mod.readme or "No repository README available.",
        ]
        self._set_formatted_text(self.repository_summary, "\n".join(summary))

    def _create_config_widget(self, mod: ModInfo, section: str, entry: str, metadata: dict[str, Any]) -> QWidget:
        value = get_runtime_value(self.runtime_config, mod.mod_id or mod.name, section, entry)
        if value is None:
            value = metadata.get("default")
        widget_type = str(metadata.get("type", "")).casefold()

        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)

        editor: QWidget
        if widget_type == "bool":
            editor = QCheckBox()
            editor.setChecked(bool(value))
            editor.toggled.connect(partial(self._save_config_value, mod, section, entry, metadata))
        elif widget_type in {"int", "float"}:
            if widget_type == "int":
                spinbox: QSpinBox | QDoubleSpinBox = QSpinBox()
                if metadata.get("min") is not None:
                    spinbox.setMinimum(int(float(metadata["min"])))
                if metadata.get("max") is not None:
                    spinbox.setMaximum(int(float(metadata["max"])))
                spinbox.setSingleStep(max(1, int(float(metadata.get("step", 1)))))
                spinbox.setValue(int(float(value if value is not None else 0)))
            else:
                spinbox = QDoubleSpinBox()
                spinbox.setDecimals(3)
                spinbox.setMinimum(float(metadata.get("min", -999999.0)))
                spinbox.setMaximum(float(metadata.get("max", 999999.0)))
                spinbox.setSingleStep(float(metadata.get("step", 0.1)))
                spinbox.setValue(float(value if value is not None else 0.0))
            spinbox.valueChanged.connect(partial(self._save_config_value, mod, section, entry, metadata))
            editor = spinbox
        elif widget_type in {"option", "optionbutton"}:
            combo = QComboBox()
            options = list(metadata.get("options", []))
            for option in options:
                combo.addItem(self._translate_for_mod(mod, option))
            store_method = str(metadata.get("store_method", "int")).casefold()
            if store_method == "string":
                index = options.index(value) if value in options else 0
            else:
                index = int(value) if isinstance(value, (int, float)) else 0
                if index >= combo.count():
                    index = 0
            combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(partial(self._save_option_value, mod, section, entry, metadata, combo))
            editor = combo
        elif widget_type == "input":
            line_edit = QLineEdit()
            if isinstance(value, list):
                pieces = []
                for item in value:
                    if isinstance(item, list):
                        pieces.append("+".join(str(part) for part in item))
                    else:
                        pieces.append(str(item))
                line_edit.setText(", ".join(pieces))
            line_edit.editingFinished.connect(partial(self._save_input_value, mod, section, entry, line_edit))
            editor = line_edit
        elif widget_type == "color":
            button = QPushButton(self._format_color_label(value))
            button.clicked.connect(partial(self._pick_color, mod, section, entry, metadata, button))
            editor = button
        elif widget_type == "action":
            button = QPushButton(self._translate_for_mod(mod, metadata.get("button_label", "In-game only action")))
            button.setEnabled(False)
            editor = button
        elif widget_type == "display":
            label = QLabel(f"External display unsupported. Scene: {metadata.get('scene_path', '')}")
            label.setWordWrap(True)
            editor = label
        else:
            line_edit = QLineEdit("" if value is None else str(value))
            line_edit.setPlaceholderText(self._translate_for_mod(mod, metadata.get("placeholder", "")))
            max_length = int(metadata.get("max_length", 0) or 0)
            if max_length > 0:
                line_edit.setMaxLength(max_length)
            if bool(metadata.get("secret", False)):
                line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            line_edit.editingFinished.connect(partial(self._save_text_value, mod, section, entry, line_edit))
            editor = line_edit

        should_enable = self._is_entry_enabled(metadata)
        editor.setEnabled(should_enable and not bool(metadata.get("disabled", False)))
        layout.addWidget(editor)

        reset_button = QPushButton("Reset")
        reset_button.clicked.connect(partial(self._reset_config_value, mod, section, entry, metadata))
        layout.addWidget(reset_button)
        return wrapper

    def _is_entry_enabled(self, metadata: dict[str, Any]) -> bool:
        requirements = metadata.get("requires_bools", [])
        if not requirements:
            return True
        matching = 0
        true_count = 0
        for requirement in requirements:
            parts = str(requirement).split("/")
            if len(parts) != 3:
                continue
            value = self._get_effective_value(parts[0], parts[1], parts[2])
            if isinstance(value, bool):
                matching += 1
                if value:
                    true_count += 1
        if matching == 0:
            return True
        invert = bool(metadata.get("invert_bool_requirement", False))
        return true_count == 0 if invert else true_count > 0

    def _get_effective_value(self, mod_id: str, section: str, key: str) -> Any:
        runtime_value = get_runtime_value(self.runtime_config, mod_id, section, key)
        if runtime_value is not None:
            return runtime_value
        for mod in self.mods:
            candidate_ids = {mod.mod_id, mod.name, mod.display_name}
            if mod_id in candidate_ids:
                entry = mod.configs.get(section, {}).get(key)
                if entry is not None:
                    return entry.get("default")
        return None

    def _save_text_value(self, mod: ModInfo, section: str, entry: str, widget: QLineEdit) -> None:
        self._save_config_value(mod, section, entry, {}, widget.text())

    def _save_input_value(self, mod: ModInfo, section: str, entry: str, widget: QLineEdit) -> None:
        values = []
        for chunk in widget.text().split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "+" in chunk:
                values.append([piece.strip() for piece in chunk.split("+") if piece.strip()])
            else:
                values.append(chunk)
        self._save_config_value(mod, section, entry, {}, values)

    def _save_option_value(
        self,
        mod: ModInfo,
        section: str,
        entry: str,
        metadata: dict[str, Any],
        combo: QComboBox,
        index: int,
    ) -> None:
        store_method = str(metadata.get("store_method", "int")).casefold()
        value = combo.currentText() if store_method == "string" else index
        self._save_config_value(mod, section, entry, metadata, value)

    def _save_config_value(self, mod: ModInfo, section: str, entry: str, metadata: dict[str, Any], value: Any) -> None:
        if self.config_path is None:
            QMessageBox.warning(self, "No config path", "Set a Delta-V user data folder before editing configs.")
            return
        mod_key = mod.mod_id or mod.name or mod.display_name
        save_runtime_value(self.config_path, self.runtime_config, mod_key, section, entry, value)
        if bool(metadata.get("require_restart", False)):
            self.statusBar().showMessage("Saved. This setting requires a game restart.", 5000)
        else:
            self.statusBar().showMessage("Saved config value", 3000)
        self.runtime_config = load_runtime_config(self.config_path)
        current_item = self.mod_list.currentItem()
        if current_item is not None:
            self._on_mod_selected(current_item)

    def _reset_config_value(self, mod: ModInfo, section: str, entry: str, metadata: dict[str, Any]) -> None:
        self._save_config_value(mod, section, entry, metadata, metadata.get("default"))

    def _pick_color(self, mod: ModInfo, section: str, entry: str, metadata: dict[str, Any], button: QPushButton) -> None:
        current = get_runtime_value(self.runtime_config, mod.mod_id or mod.name, section, entry)
        if current is None:
            current = metadata.get("default")
        dialog_color = QColor(255, 255, 255)
        if isinstance(current, TaggedValue) and is_color_value(current):
            values = list(current.args)
            while len(values) < 4:
                values.append(1.0)
            dialog_color = QColor.fromRgbF(float(values[0]), float(values[1]), float(values[2]), float(values[3]))
        selected = QColorDialog.getColor(dialog_color, self, "Choose Color")
        if not selected.isValid():
            return
        alpha = selected.alphaF() if bool(metadata.get("edit_alpha", True)) else 1.0
        tagged = TaggedValue("Color", (selected.redF(), selected.greenF(), selected.blueF(), alpha))
        button.setText(self._format_color_label(tagged))
        self._save_config_value(mod, section, entry, metadata, tagged)

    def _format_color_label(self, value: Any) -> str:
        if is_color_value(value):
            rgba = [round(float(part), 3) for part in value.args]
            return f"Color {rgba}"
        return "Choose Color"

    def _set_formatted_text(self, widget: QTextEdit, text: str) -> None:
        widget.setHtml(self._format_display_text(text))

    def _toggle_theme(self, checked: bool) -> None:
        self.dark_mode = bool(checked)
        self._apply_theme()
        self._save_app_settings()

    def _toggle_auto_detect_on_startup(self, checked: bool) -> None:
        self.auto_detect_paths_on_startup = bool(checked)
        self._save_app_settings()

    def _apply_theme(self) -> None:
        self.theme_toggle_action.setChecked(self.dark_mode)
        self.auto_detect_startup_action.setChecked(self.auto_detect_paths_on_startup)
        app = QApplication.instance()
        if app is None:
            return
        app.setStyle("Fusion")
        app.setStyleSheet("")
        app.setPalette(self._dark_palette() if self.dark_mode else self._light_palette())

    def _dark_palette(self) -> QPalette:
        palette = QPalette()
        window = QColor(24, 26, 30)
        base = QColor(34, 36, 40)
        alt_base = QColor(44, 46, 50)
        text = QColor(230, 230, 230)
        button = QColor(44, 46, 50)
        highlight = QColor(42, 130, 218)
        disabled_text = QColor(130, 130, 130)

        palette.setColor(QPalette.ColorRole.Window, window)
        palette.setColor(QPalette.ColorRole.WindowText, text)
        palette.setColor(QPalette.ColorRole.Base, base)
        palette.setColor(QPalette.ColorRole.AlternateBase, alt_base)
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.Button, button)
        palette.setColor(QPalette.ColorRole.ButtonText, text)
        palette.setColor(QPalette.ColorRole.Highlight, highlight)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipBase, base)
        palette.setColor(QPalette.ColorRole.ToolTipText, text)
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
        palette.setColor(QPalette.ColorRole.Link, QColor(88, 166, 255))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(150, 120, 255))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(160, 160, 160))

        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(70, 70, 70))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(180, 180, 180))
        return palette

    def _light_palette(self) -> QPalette:
        palette = QPalette()
        window = QColor(250, 251, 253)
        base = QColor(255, 255, 255)
        alt_base = QColor(245, 247, 250)
        text = QColor(24, 29, 37)
        button = QColor(246, 248, 251)
        highlight = QColor(52, 132, 228)
        disabled_text = QColor(135, 141, 150)

        palette.setColor(QPalette.ColorRole.Window, window)
        palette.setColor(QPalette.ColorRole.WindowText, text)
        palette.setColor(QPalette.ColorRole.Base, base)
        palette.setColor(QPalette.ColorRole.AlternateBase, alt_base)
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.Button, button)
        palette.setColor(QPalette.ColorRole.ButtonText, text)
        palette.setColor(QPalette.ColorRole.Highlight, highlight)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipBase, base)
        palette.setColor(QPalette.ColorRole.ToolTipText, text)
        palette.setColor(QPalette.ColorRole.BrightText, QColor(180, 32, 32))
        palette.setColor(QPalette.ColorRole.Link, QColor(25, 91, 184))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(90, 63, 168))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(145, 150, 159))

        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(190, 200, 214))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(95, 102, 113))
        return palette

    @staticmethod
    def _format_display_text(text: str) -> str:
        normalized = MainWindow._normalize_display_text(text)
        escaped = html.escape(normalized)
        escaped = escaped.replace("\n", "<br>")
        escaped = re.sub(r"\[b\](.*?)\[/b\]", r"<b>\1</b>", escaped, flags=re.IGNORECASE | re.DOTALL)
        escaped = re.sub(r"\[i\](.*?)\[/i\]", r"<i>\1</i>", escaped, flags=re.IGNORECASE | re.DOTALL)
        escaped = re.sub(r"\[u\](.*?)\[/u\]", r"<u>\1</u>", escaped, flags=re.IGNORECASE | re.DOTALL)
        escaped = re.sub(
            r"\[center\](.*?)\[/center\]",
            r"\1",
            escaped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        escaped = re.sub(r"\[/?[^\]]+\]", "", escaped)
        return escaped

    @staticmethod
    def _normalize_display_text(text: Any) -> str:
        normalized = "" if text is None else str(text)
        normalized = normalized.replace("\\r\\n", "\n")
        normalized = normalized.replace("\\n", "\n")
        normalized = normalized.replace("\\t", "\t")
        normalized = normalized.replace("\\/", "/")
        return normalized

    def _translate_for_mod(self, mod: ModInfo, value: Any) -> str:
        translated = resolve_translation_key(value, mod.translations, self.current_locale, mod.master_locale)
        if translated != value:
            return translated
        return resolve_translation_key(value, self.shared_translations, self.current_locale, self.shared_master_locale)

    def _collect_dependent_mods(self, root_mod: ModInfo) -> list[ModInfo]:
        root_id = root_mod.mod_id.strip().casefold()
        if not root_id:
            return []

        discovered_ids = {root_id}
        dependents: dict[str, ModInfo] = {}
        searching = True
        while searching:
            searching = False
            for mod in self.mods:
                mod_id = mod.mod_id.strip().casefold()
                if not mod_id or mod_id in discovered_ids:
                    continue
                dependencies = {dependency.casefold() for dependency in self._extract_dependency_ids(mod)}
                if dependencies.intersection(discovered_ids):
                    dependents[mod_id] = mod
                    discovered_ids.add(mod_id)
                    searching = True
        return sorted(dependents.values(), key=lambda item: item.display_name.casefold())

    def _show_dependency_impact_dialog(self, action: str, dependents: list[ModInfo]) -> str:
        lines = [f"{mod.display_name} ({mod.mod_id or mod.archive_path.name})" for mod in dependents]
        message = "The following mod(s) depend on this mod:\n\n" + "\n".join(lines)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Dependency Warning")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        all_button = dialog.addButton(f"{action} all", QMessageBox.ButtonRole.AcceptRole)
        ignore_button = dialog.addButton("ignore", QMessageBox.ButtonRole.ActionRole)
        cancel_button = dialog.addButton("cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is all_button:
            return "all"
        if clicked is ignore_button:
            return "ignore"
        if clicked is cancel_button:
            return "cancel"
        return "cancel"

    def _toggle_selected_mod(self) -> None:
        mod = self._current_mod()
        if mod is None:
            return
        if mod.enabled:
            dependents = self._collect_dependent_mods(mod)
            if dependents:
                decision = self._show_dependency_impact_dialog("disable", dependents)
                if decision == "cancel":
                    return
                if decision == "all":
                    errors: list[str] = []
                    for dependent in dependents:
                        if not dependent.enabled:
                            continue
                        try:
                            toggle_mod(dependent)
                        except OSError as exc:
                            errors.append(f"{dependent.display_name}: {exc}")
                    if errors:
                        QMessageBox.critical(self, "Disable failed", "\n".join(errors))
                        return

        selected_archive = mod.archive_path
        try:
            toggle_mod(mod)
        except OSError as exc:
            QMessageBox.critical(self, "Toggle failed", str(exc))
            return
        target_archive = selected_archive.with_name(selected_archive.name + ".disabled") if mod.enabled else selected_archive.with_name(selected_archive.name[:-9] if selected_archive.name.endswith(".disabled") else selected_archive.stem)
        self.refresh_state()
        self._select_mod_by_archive(target_archive)

    def _toggle_mod_by_archive(self, archive_path: Path) -> None:
        self._select_mod_by_archive(archive_path)
        self._toggle_selected_mod()

    def _check_mod_update_by_archive(self, archive_path: Path) -> None:
        mod = next((entry for entry in self.mods if entry.archive_path == archive_path), None)
        if mod is None:
            return
        message, _ = self._check_mod_update(mod)
        QMessageBox.information(self, "Update Check", message)

    def _check_mod_update(self, mod: ModInfo) -> tuple[str, str | None]:
        if not mod.manifest_url:
            return f"{mod.display_name}: no manifest_url for update checks", None
        try:
            latest_manifest = fetch_latest_manifest(mod.manifest_url)
        except Exception as exc:
            return f"{mod.display_name}: failed to check updates ({exc})", None
        latest_version = self._format_manifest_version(latest_manifest)
        if not latest_version:
            return f"{mod.display_name}: update source returned no version", None
        comparison = compare_versions(mod.version or "0.0.0", latest_version)
        if comparison < 0:
            download_url = self._resolve_update_download_url(mod, latest_manifest)
            download_suffix = "" if download_url else " (no download URL found)"
            return f"{mod.display_name}: update available ({mod.version or 'unknown'} -> {latest_version}){download_suffix}", download_url
        return f"{mod.display_name}: up to date ({mod.version or latest_version})", None

    def _resolve_update_download_url(self, mod: ModInfo, latest_manifest: dict[str, dict[str, Any]]) -> str | None:
        candidates: list[Any] = []
        links = latest_manifest.get("links", {})
        manifest_defs = latest_manifest.get("manifest_definitions", {})
        if isinstance(links, dict):
            candidates.extend([
                links.get("zip_url"),
                links.get("download_url"),
                links.get("release_zip"),
                links.get("mod_zip"),
                links.get("zip"),
                links.get("url"),
            ])
        if isinstance(manifest_defs, dict):
            candidates.extend([
                manifest_defs.get("download_url"),
                manifest_defs.get("zip_url"),
            ])
        if isinstance(mod.links, dict):
            candidates.extend([
                mod.links.get("zip_url"),
                mod.links.get("download_url"),
                mod.links.get("release_zip"),
                mod.links.get("mod_zip"),
                mod.links.get("zip"),
                mod.links.get("url"),
            ])
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip().startswith(("http://", "https://")):
                return candidate.strip()
        return None

    def _check_dependencies(self) -> None:
        if not self.mods:
            QMessageBox.information(self, "Dependency Check", "No mods found.")
            return
        installed_ids = {mod.mod_id.strip().casefold() for mod in self.mods if mod.mod_id.strip()}
        issues: list[str] = []
        for mod in self.mods:
            dependencies = self._extract_dependency_ids(mod)
            if not dependencies:
                continue
            missing = [dep for dep in dependencies if dep.casefold() not in installed_ids]
            if missing:
                issues.append(f"{mod.display_name}: missing {', '.join(missing)}")
        if issues:
            QMessageBox.warning(self, "Dependency Check", "\n".join(issues))
            return
        QMessageBox.information(self, "Dependency Check", "No missing dependencies detected.")

    def _extract_dependency_ids(self, mod: ModInfo) -> list[str]:
        return extract_dependency_ids_from_manifest(mod.manifest)

    def _update_all_mods(self) -> None:
        if self.mods_dir is None:
            QMessageBox.warning(self, "No mods folder", "Set or autodetect the Delta-V game directory first.")
            return
        if not self.mods:
            QMessageBox.information(self, "Update All", "No mods found.")
            return

        updated: list[str] = []
        skipped: list[str] = []

        for mod in self.mods:
            message, download_url = self._check_mod_update(mod)
            if "update available" not in message.casefold():
                skipped.append(message)
                continue
            if not download_url:
                skipped.append(message)
                continue
            try:
                install_mod_from_url(download_url, self.mods_dir)
                updated.append(mod.display_name)
            except Exception as exc:
                skipped.append(f"{mod.display_name}: update failed ({exc})")

        self.refresh_state()
        lines: list[str] = []
        if updated:
            lines.append(f"Updated: {', '.join(updated)}")
        if skipped:
            lines.append("")
            lines.append("Skipped:")
            lines.extend(skipped)
        if not lines:
            lines.append("No updates available.")
        QMessageBox.information(self, "Update All", "\n".join(lines))

    def _delete_mod_by_archive(self, archive_path: Path) -> None:
        mod = next((entry for entry in self.mods if entry.archive_path == archive_path), None)
        if mod is None:
            return
        delete_targets: list[ModInfo] = [mod]
        dependents = self._collect_dependent_mods(mod)
        if dependents:
            decision = self._show_dependency_impact_dialog("delete", dependents)
            if decision == "cancel":
                return
            if decision == "all":
                delete_targets.extend(dependents)
        else:
            answer = QMessageBox.question(
                self,
                "Delete Mod",
                f"Delete {mod.archive_path.name}?\n\nThis removes the archive file from the mods folder.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        errors: list[str] = []
        seen_paths: set[Path] = set()
        for target_mod in delete_targets:
            if target_mod.archive_path in seen_paths:
                continue
            seen_paths.add(target_mod.archive_path)
            try:
                target_mod.archive_path.unlink()
            except OSError as exc:
                errors.append(f"{target_mod.display_name}: {exc}")
        if errors:
            QMessageBox.critical(self, "Delete failed", "\n".join(errors))
            return
        self.refresh_state()

    def _show_missing_dependencies_dialog(self, dependencies: list[str]) -> str:
        message = "missing dependency(s):\n" + "\n".join(dependencies)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Missing Dependencies")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        install_all_button = dialog.addButton("install all", QMessageBox.ButtonRole.AcceptRole)
        ignore_button = dialog.addButton("ignore", QMessageBox.ButtonRole.ActionRole)
        cancle_button = dialog.addButton("cancle", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is install_all_button:
            return "install_all"
        if clicked is ignore_button:
            return "ignore"
        if clicked is cancle_button:
            return "cancle"
        return "cancle"

    def _install_dependencies_from_repository(self, dependencies: list[str]) -> tuple[list[str], list[str]]:
        if self.mods_dir is None:
            return [], ["mods folder is not configured"]
        if not self.repository_mods:
            try:
                self.repository_mods = fetch_repository_catalog()
            except Exception as exc:
                return [], [f"repository fetch failed ({exc})"]

        dependency_queue: list[str] = []
        seen: set[str] = set()
        for dependency in dependencies:
            normalized = dependency.strip()
            key = normalized.casefold()
            if not normalized or key in seen:
                continue
            seen.add(key)
            dependency_queue.append(normalized)

        repo_by_id = {entry.mod_id.casefold(): entry for entry in self.repository_mods if entry.mod_id}
        installed_ids = {mod.mod_id.strip().casefold() for mod in self.mods if mod.mod_id.strip()}
        installed: list[str] = []
        failed: list[str] = []

        for dependency in dependency_queue:
            dep_key = dependency.casefold()
            if dep_key in installed_ids:
                continue
            repo_mod = repo_by_id.get(dep_key)
            if repo_mod is None:
                failed.append(f"{dependency}: not found in repository")
                continue
            if not repo_mod.zip_url:
                failed.append(f"{dependency}: repository entry has no zip URL")
                continue
            try:
                install_mod_from_url(repo_mod.zip_url, self.mods_dir)
                installed_ids.add(dep_key)
                installed.append(dependency)
            except MissingDependenciesError as exc:
                chain = ", ".join(exc.dependencies)
                failed.append(f"{dependency}: missing dependencies ({chain})")
            except Exception as exc:
                failed.append(f"{dependency}: install failed ({exc})")

        return installed, failed

    def _install_with_dependency_prompt(
        self,
        installer: Callable[[bool], Any],
        failed_title: str,
    ) -> bool:
        try:
            installer(True)
            return True
        except MissingDependenciesError as exc:
            choice = self._show_missing_dependencies_dialog(exc.dependencies)
            if choice == "cancle":
                return False
            if choice == "ignore":
                try:
                    installer(False)
                    return True
                except Exception as ignore_exc:
                    QMessageBox.critical(self, failed_title, str(ignore_exc))
                    return False

            installed, failed = self._install_dependencies_from_repository(exc.dependencies)
            if failed:
                lines = ["Could not install all dependencies:", *failed]
                if installed:
                    lines.extend(["", "Installed:", *installed])
                QMessageBox.warning(self, "Dependency Install", "\n".join(lines))
                return False
            try:
                installer(True)
                return True
            except MissingDependenciesError as retry_exc:
                QMessageBox.warning(self, "Dependency Check", "missing dependency(s):\n" + "\n".join(retry_exc.dependencies))
                return False
            except Exception as retry_exc:
                QMessageBox.critical(self, failed_title, str(retry_exc))
                return False
        except Exception as exc:
            QMessageBox.critical(self, failed_title, str(exc))
            return False

    def _install_from_file(self) -> None:
        mods_dir = self.mods_dir
        if mods_dir is None:
            QMessageBox.warning(self, "No mods folder", "Set or autodetect the Delta-V game directory first.")
            return
        selected, _ = QFileDialog.getOpenFileName(self, "Choose mod archive", filter="Zip files (*.zip);;All files (*)")
        if not selected:
            return
        source = Path(selected)
        if not self._install_with_dependency_prompt(
            lambda enforce: install_mod_from_path(source, mods_dir, enforce_dependencies=enforce),
            "Install failed",
        ):
            return
        self.refresh_state()

    def _install_from_url(self) -> None:
        mods_dir = self.mods_dir
        if mods_dir is None:
            QMessageBox.warning(self, "No mods folder", "Set or autodetect the Delta-V game directory first.")
            return
        url, ok = QInputDialog.getText(self, "Install mod from URL", "Direct zip URL or GitHub repo/release URL")
        if not ok or not url.strip():
            return
        source_url = url.strip()
        if not self._install_with_dependency_prompt(
            lambda enforce: install_mod_from_url(source_url, mods_dir, enforce_dependencies=enforce),
            "Download failed",
        ):
            return
        self.refresh_state()

    def _install_selected_repository_mod(self) -> None:
        mods_dir = self.mods_dir
        if mods_dir is None:
            QMessageBox.warning(self, "No mods folder", "Set or autodetect the Delta-V game directory first.")
            return
        item = self.repository_list.currentItem()
        if item is None:
            return
        mod_id = item.data(Qt.ItemDataRole.UserRole)
        repo_mod = next((entry for entry in self.repository_mods if entry.mod_id == mod_id), None)
        if repo_mod is None or not repo_mod.zip_url:
            QMessageBox.warning(self, "No download available", "This repository entry does not provide a downloadable zip.")
            return
        if not self._install_with_dependency_prompt(
            lambda enforce: install_mod_from_url(repo_mod.zip_url, mods_dir, enforce_dependencies=enforce),
            "Repository install failed",
        ):
            return
        self.refresh_state()

    def _format_manifest_version(self, manifest: dict[str, dict[str, Any]]) -> str:
        version_info = manifest.get("version", {})
        parts = [version_info.get("version_major"), version_info.get("version_minor"), version_info.get("version_bugfix")]
        filtered = [str(part) for part in parts if part is not None]
        return ".".join(filtered)

    def _open_mods_folder(self) -> None:
        if self.mods_dir is None:
            return
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.mods_dir)

    def _current_mod(self) -> ModInfo | None:
        item = self.mod_list.currentItem()
        if item is None:
            return None
        archive_path = item.data(Qt.ItemDataRole.UserRole)
        return next((entry for entry in self.mods if entry.archive_path == archive_path), None)

    def _current_archive_path(self) -> Path | None:
        item = self.mod_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _select_mod_by_archive(self, archive_path: Path | None) -> None:
        if archive_path is None:
            return
        for row in range(self.mod_list.count()):
            item = self.mod_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == archive_path:
                self.mod_list.setCurrentRow(row)
                return

    def _clear_config_layout(self) -> None:
        while self.config_layout.count():
            child = self.config_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window._refresh_repository()
    window.show()
    return app.exec()
