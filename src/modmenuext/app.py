from __future__ import annotations

from functools import partial
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
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
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .godot_variant import TaggedValue, is_color_value
from .localization import resolve_translation_key
from .mods import (
    ModInfo,
    RepositoryMod,
    compare_versions,
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
from .steam import discover_delta_v_install, discover_delta_v_user_dir, discover_game_executable


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ModMenuExt")
        self.resize(1200, 760)

        self.game_dir: Path | None = None
        self.user_dir: Path | None = None
        self.mods_dir: Path | None = None
        self.config_path: Path | None = None
        self.mods: list[ModInfo] = []
        self.repository_mods: list[RepositoryMod] = []
        self.runtime_config: dict[str, dict[str, Any]] = {}
        self.current_locale = QLocale.system().name()
        self.shared_translations: dict[str, dict[str, Any]] = {}
        self.shared_master_locale = "en"

        self._build_ui()
        self._autodetect_paths()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.addWidget(self._build_paths_box())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_mods_panel())
        splitter.addWidget(self._build_details_panel())
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar(self))

        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_state)
        self.menuBar().addAction(refresh_action)

    def _build_paths_box(self) -> QGroupBox:
        box = QGroupBox("Paths")
        layout = QFormLayout(box)

        self.game_dir_edit = QLineEdit()
        self.game_dir_edit.setReadOnly(True)
        self.user_dir_edit = QLineEdit()
        self.user_dir_edit.setReadOnly(True)
        self.mods_dir_edit = QLineEdit()
        self.mods_dir_edit.setReadOnly(True)

        game_buttons = QHBoxLayout()
        detect_button = QPushButton("Autodetect")
        detect_button.clicked.connect(self._autodetect_paths)
        browse_game_button = QPushButton("Browse Game")
        browse_game_button.clicked.connect(self._browse_game_dir)
        browse_user_button = QPushButton("Browse User Data")
        browse_user_button.clicked.connect(self._browse_user_dir)
        game_buttons.addWidget(detect_button)
        game_buttons.addWidget(browse_game_button)
        game_buttons.addWidget(browse_user_button)

        layout.addRow("Game directory", self.game_dir_edit)
        layout.addRow("User data directory", self.user_dir_edit)
        layout.addRow("Mods directory", self.mods_dir_edit)
        layout.addRow("Actions", self._wrap_layout(game_buttons))
        return box

    def _build_mods_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.mod_list = QListWidget()
        self.mod_list.currentItemChanged.connect(self._on_mod_selected)
        layout.addWidget(self.mod_list)

        buttons = QHBoxLayout()
        self.toggle_button = QPushButton("Toggle")
        self.toggle_button.clicked.connect(self._toggle_selected_mod)
        self.check_updates_button = QPushButton("Check Updates")
        self.check_updates_button.clicked.connect(self._check_updates)
        install_url_button = QPushButton("Install From URL")
        install_url_button.clicked.connect(self._install_from_url)
        install_file_button = QPushButton("Install Zip")
        install_file_button.clicked.connect(self._install_from_file)
        open_mods_button = QPushButton("Open Mods Folder")
        open_mods_button.clicked.connect(self._open_mods_folder)
        launch_button = QPushButton("Launch Delta-V")
        launch_button.clicked.connect(self._launch_game)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_state)

        for button in (
            self.toggle_button,
            self.check_updates_button,
            install_url_button,
            install_file_button,
            open_mods_button,
            launch_button,
            refresh_button,
        ):
            buttons.addWidget(button)

        layout.addWidget(self._wrap_layout(buttons))
        return widget

    def _build_details_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.summary_box = QTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.setMinimumHeight(170)
        layout.addWidget(self.summary_box)

        self.details_tabs = QTabWidget()

        config_tab = QWidget()
        config_tab_layout = QVBoxLayout(config_tab)
        self.config_scroll = QScrollArea()
        self.config_scroll.setWidgetResizable(True)
        self.config_container = QWidget()
        self.config_layout = QVBoxLayout(self.config_container)
        self.config_layout.addWidget(QLabel("Select a mod to edit its configs."))
        self.config_layout.addStretch(1)
        self.config_scroll.setWidget(self.config_container)
        config_tab_layout.addWidget(self.config_scroll)
        self.details_tabs.addTab(config_tab, "Config")

        repository_tab = QWidget()
        repository_layout = QVBoxLayout(repository_tab)
        self.repository_list = QListWidget()
        self.repository_list.currentItemChanged.connect(self._on_repository_selected)
        self.repository_summary = QTextEdit()
        self.repository_summary.setReadOnly(True)
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

    def _autodetect_paths(self) -> None:
        self.game_dir = discover_delta_v_install()
        self.user_dir = discover_delta_v_user_dir()
        self._sync_paths()
        self.refresh_state()

    def _browse_game_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Delta-V install directory")
        if selected:
            self.game_dir = Path(selected)
            self._sync_paths()
            self.refresh_state()

    def _browse_user_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Delta-V user data directory")
        if selected:
            self.user_dir = Path(selected)
            self._sync_paths()
            self.refresh_state()

    def _sync_paths(self) -> None:
        self.mods_dir = self.game_dir / "mods" if self.game_dir else None
        self.config_path = self.user_dir / "cfg" / "Mod_Configurations.cfg" if self.user_dir else None
        self.game_dir_edit.setText(str(self.game_dir or ""))
        self.user_dir_edit.setText(str(self.user_dir or ""))
        self.mods_dir_edit.setText(str(self.mods_dir or ""))

    def refresh_state(self) -> None:
        selected_archive_path = self._current_archive_path()
        if self.config_path:
            self.runtime_config = load_runtime_config(self.config_path)
        else:
            self.runtime_config = {}
        self.mods = scan_mods(self.mods_dir) if self.mods_dir else []
        self._rebuild_shared_translations()
        self._populate_mod_list(selected_archive_path)
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
            prefix = "[ON]" if mod.enabled else "[OFF]"
            item = QListWidgetItem(f"{prefix} {mod.display_name}")
            item.setData(Qt.ItemDataRole.UserRole, mod.archive_path)
            self.mod_list.addItem(item)
            if selected_archive_path is not None and mod.archive_path == selected_archive_path:
                target_row = self.mod_list.count() - 1
        if self.mod_list.count() > 0:
            self.mod_list.setCurrentRow(target_row if target_row >= 0 else 0)
        else:
            self._show_mod_details(None)

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
            self.repository_summary.setPlainText("No repository mods found.")

    def _on_mod_selected(self, current: QListWidgetItem | None) -> None:
        if current is None:
            self._show_mod_details(None)
            return
        archive_path = current.data(Qt.ItemDataRole.UserRole)
        mod = next((entry for entry in self.mods if entry.archive_path == archive_path), None)
        self._show_mod_details(mod)

    def _show_mod_details(self, mod: ModInfo | None) -> None:
        self._clear_config_layout()
        if mod is None:
            self.summary_box.setPlainText("No mod selected.")
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
        self.summary_box.setPlainText("\n".join(summary_lines))
        self.toggle_button.setText("Disable" if mod.enabled else "Enable")

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
            self.repository_summary.setPlainText("No repository mod selected.")
            return
        mod_id = current.data(Qt.ItemDataRole.UserRole)
        repo_mod = next((entry for entry in self.repository_mods if entry.mod_id == mod_id), None)
        if repo_mod is None:
            self.repository_summary.setPlainText("No repository mod selected.")
            return
        summary = [
            f"Name: {repo_mod.name}",
            f"ID: {repo_mod.mod_id}",
            f"Author: {repo_mod.author or '-'}",
            f"Zip: {repo_mod.zip_name or '-'}",
            "",
            repo_mod.readme or "No repository README available.",
        ]
        self.repository_summary.setPlainText("\n".join(summary))

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

    def _translate_for_mod(self, mod: ModInfo, value: Any) -> str:
        translated = resolve_translation_key(value, mod.translations, self.current_locale, mod.master_locale)
        if translated != value:
            return translated
        return resolve_translation_key(value, self.shared_translations, self.current_locale, self.shared_master_locale)

    def _toggle_selected_mod(self) -> None:
        mod = self._current_mod()
        if mod is None:
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

    def _install_from_file(self) -> None:
        if self.mods_dir is None:
            QMessageBox.warning(self, "No mods folder", "Set or autodetect the Delta-V game directory first.")
            return
        selected, _ = QFileDialog.getOpenFileName(self, "Choose mod archive", filter="Zip files (*.zip);;All files (*)")
        if not selected:
            return
        install_mod_from_path(Path(selected), self.mods_dir)
        self.refresh_state()

    def _install_from_url(self) -> None:
        if self.mods_dir is None:
            QMessageBox.warning(self, "No mods folder", "Set or autodetect the Delta-V game directory first.")
            return
        url, ok = QInputDialog.getText(self, "Install mod from URL", "Direct zip URL or GitHub repo/release URL")
        if not ok or not url.strip():
            return
        try:
            install_mod_from_url(url.strip(), self.mods_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Download failed", str(exc))
            return
        self.refresh_state()

    def _install_selected_repository_mod(self) -> None:
        if self.mods_dir is None:
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
        try:
            install_mod_from_url(repo_mod.zip_url, self.mods_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Repository install failed", str(exc))
            return
        self.refresh_state()

    def _check_updates(self) -> None:
        installed_with_manifests = [mod for mod in self.mods if mod.manifest_url]
        if not installed_with_manifests:
            QMessageBox.information(self, "No manifest URLs", "No installed mods expose a manifest_url for update checks.")
            return

        lines: list[str] = []
        for mod in installed_with_manifests:
            try:
                latest_manifest = fetch_latest_manifest(mod.manifest_url)
            except Exception as exc:
                lines.append(f"{mod.display_name}: failed to check updates ({exc})")
                continue
            latest_version = self._format_manifest_version(latest_manifest)
            if not latest_version:
                lines.append(f"{mod.display_name}: update source returned no version")
                continue
            comparison = compare_versions(mod.version or "0.0.0", latest_version)
            if comparison < 0:
                lines.append(f"{mod.display_name}: update available ({mod.version or 'unknown'} -> {latest_version})")
            else:
                lines.append(f"{mod.display_name}: up to date ({mod.version or latest_version})")

        QMessageBox.information(self, "Update Check", "\n".join(lines))

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

    def _launch_game(self) -> None:
        if self.game_dir is None:
            QMessageBox.warning(self, "No game directory", "Set or autodetect the Delta-V game directory first.")
            return
        executable = discover_game_executable(self.game_dir)
        if executable is None:
            QMessageBox.warning(self, "No executable", "Could not find the Delta-V executable in the selected folder.")
            return
        subprocess.Popen([str(executable), "--enable-mods"], cwd=self.game_dir)
        self.statusBar().showMessage("Launched Delta-V with --enable-mods", 4000)

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
