"""A shortcut-key editor for Nuke's menus

homepage: https://github.com/dbr/shortcuteditor-nuke
license: GPL v2

To use, in ~/.nuke/menu.py add this:

try:
    import shortcuteditor
    shortcuteditor.nuke_setup()
except Exception:
    import traceback
    traceback.print_exc()
# Note: It is recommended this goes near the end of menu.py
"""

__version__ = "1.3" 
# Updated by Cedric PALADJIAN (cedricpld) for Nuke 16+ compatibility

import nuke
import os
import sys
import json
import hashlib

try:
    # Prefer Qt.py when available
    from Qt import QtCore, QtGui, QtWidgets
    from Qt.QtCore import Qt
    QT_VERSION = 5 # Assumption for Qt.py, refined below if needed
except ImportError:
    try:
        # PySide6 for Nuke 16+
        from PySide6 import QtCore, QtGui, QtWidgets
        from PySide6.QtCore import Qt
        QT_VERSION = 6
    except ImportError:
        try:
            # PySide2 for Nuke 11-13
            from PySide2 import QtCore, QtGui, QtWidgets
            from PySide2.QtCore import Qt
            QT_VERSION = 5
        except ImportError:
            # Or PySide for Nuke 10
            from PySide import QtCore, QtGui, QtGui as QtWidgets
            from PySide.QtCore import Qt
            QT_VERSION = 4

if sys.version_info[0] >= 3:
    basestring = str

# Debug flag for logging missing/orphaned menu items
# Set to True to enable warnings for shortcuts that reference non-existent menu commands
# Can also be set via environment variable: SHORTCUTEDITOR_DEBUG=1
DEBUG_MISSING_ITEMS = os.environ.get('SHORTCUTEDITOR_DEBUG', '0').lower() in ('1', 'true', 'yes')

# Debug flag for printing conflict/orphaned statistics
# Set to True to enable one-line summary of conflicts and orphaned shortcuts
# Can also be set via environment variable: SHORTCUTEDITOR_DEBUG_STATS=1
DEBUG_STATS = os.environ.get('SHORTCUTEDITOR_DEBUG_STATS', '0').lower() in ('1', 'true', 'yes')

# Module-level guard to ensure debug stats print at most once per session
_debug_stats_printed_conflicts = False
_debug_stats_printed_orphaned = False

# Module-level cache for default shortcuts (captured before user prefs are applied)
_default_shortcuts_cache = None

# Pastel color palette for status indicators (suitable for dark UI with light text)
STATUS_COLORS = {
    'ADDED': '#7FD4B6',      # Soft teal/green
    'CLEARED': '#D4A5D4',    # Soft lavender/purple (more distinct from ADDED)
    'REPLACED': '#E8C97F',   # Soft amber/yellow
    'UNCHANGED': '#A0A0A0',  # Muted gray
    'CONFLICT': '#E87F7F',   # Soft red (for conflict badges)
    'CONFLICT_BG': '#3A2525', # Subtle red-tinted background (dark)
}

def _qt_int(val):
    """Helper to handle Qt6 Enums that don't cast to int directly"""
    if hasattr(val, "value"):
        return int(val.value)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0

# Pre-calculate masks for bitwise operations
SHIFT_MASK = _qt_int(Qt.ShiftModifier)
CTRL_MASK  = _qt_int(Qt.ControlModifier)
ALT_MASK   = _qt_int(Qt.AltModifier)
META_MASK  = _qt_int(Qt.MetaModifier)
MODIFIERS_MASK = SHIFT_MASK | CTRL_MASK | ALT_MASK | META_MASK

def _run_dialog(dialog):
    if hasattr(dialog, 'exec'):
        return dialog.exec()
    return dialog.exec_()


class KeySequenceWidget(QtWidgets.QWidget):
    """A widget to enter a keyboard shortcut.

    Loosely based on kkeysequencewidget.cpp from KDE :-)

    Modified from
    https://github.com/wbsoft/frescobaldi/blob/master/frescobaldi_app/widgets/keysequencewidget.py
    """

    keySequenceChanged = QtCore.Signal()

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)

        self.setMinimumWidth(140)

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.setLayout(layout)

        self.button = KeySequenceButton(self)
        self.clearButton = QtWidgets.QPushButton(self)
        self.clearButton.setIconSize(QtCore.QSize(16, 16))
        self.clearButton.setText("Clear")
        self.clearButton.setFixedWidth(50)

        layout.addWidget(self.button)
        layout.addWidget(self.clearButton)

        self.clearButton.clicked.connect(self.clear)

        self.button.setToolTip("Start recording a key sequence.")
        self.clearButton.setToolTip("Clear the key sequence.")

    def setShortcut(self, shortcut):
        """Sets the initial shortcut to display."""
        self.button.setKeySequence(shortcut)

    def shortcut(self):
        """Returns the currently set key sequence."""
        return self.button.keySequence()

    def clear(self):
        """Empties the displayed shortcut."""
        if self.button.isRecording():
            self.button.cancelRecording()
        if not self.button.keySequence().isEmpty():
            self.button.setKeySequence(QtGui.QKeySequence())
            self.keySequenceChanged.emit()

    def setModifierlessAllowed(self, allow):
        self.button._modifierlessAllowed = allow

    def isModifierlessAllowed(self):
        return self.button._modifierlessAllowed


class KeySequenceButton(QtWidgets.QPushButton):
    """
    Modified from
    https://github.com/wbsoft/frescobaldi/blob/master/frescobaldi_app/widgets/keysequencewidget.py
    """

    MAX_NUM_KEYSTROKES = 1

    def __init__(self, parent=None):
        QtWidgets.QPushButton.__init__(self, parent)
        # self.setIcon(icons.get("configure"))
        self._modifierlessAllowed = True  # True allows "b" as a shortcut, False requires shift/alt/ctrl/etc
        self._seq = QtGui.QKeySequence()
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._isrecording = False
        self._modifiers = 0
        self.clicked.connect(self.startRecording)
        self._timer.timeout.connect(self.doneRecording)
        self._recseq = QtGui.QKeySequence()

    def setKeySequence(self, seq):
        self._seq = seq
        self.updateDisplay()

    def keySequence(self):
        if self._isrecording:
            self.doneRecording()
        return self._seq

    def updateDisplay(self):
        if self._isrecording:
            try:
                s = self._recseq.toString(QtGui.QKeySequence.NativeText).replace('&', '&&')
                if self._modifiers:
                    if s: s += ","
                    s += QtGui.QKeySequence(_qt_int(self._modifiers)).toString(QtGui.QKeySequence.NativeText)
                elif self._recseq.isEmpty():
                    s = "Input"
                s += " ..."
            except Exception:
                s = "Input ..."
        else:
            s = self._seq.toString(QtGui.QKeySequence.NativeText).replace('&', '&&')
        self.setText(s)

    def isRecording(self):
        return self._isrecording

    def event(self, ev):
        if self._isrecording:
            # prevent Qt from special casing Tab and Backtab
            if ev.type() == QtCore.QEvent.KeyPress:
                self.keyPressEvent(ev)
                return True
        return QtWidgets.QPushButton.event(self, ev)

    def keyPressEvent(self, ev):
        if not self._isrecording:
            return QtWidgets.QPushButton.keyPressEvent(self, ev)
        if ev.isAutoRepeat():
            return
        
        current_modifiers = _qt_int(ev.modifiers())
        modifiers = current_modifiers & MODIFIERS_MASK

        ev.accept()

        all_modifiers = (_qt_int(Qt.Key_Shift), _qt_int(Qt.Key_Control), _qt_int(Qt.Key_AltGr),
                            _qt_int(Qt.Key_Alt), _qt_int(Qt.Key_Meta), _qt_int(Qt.Key_Menu))

        key = _qt_int(ev.key())
        
        # Handle unknown keys (sometimes happens with modifiers in Qt6)
        if key == -1 or key == 0:
            self._modifiers = modifiers
            self.controlTimer()
            self.updateDisplay()
            return

        # check if key is a modifier or a character key without modifier (and if that is allowed)
        if (
            # don't append the key if the key is -1 (garbage) or a modifier ...
            key not in all_modifiers
            # or if this is the first key and without modifier and modifierless keys are not allowed
            and (self._modifierlessAllowed
                 or self._recseq.count() > 0
                 or modifiers & ~SHIFT_MASK
                 or not ev.text()
                 or (modifiers & SHIFT_MASK
                     and key in (_qt_int(Qt.Key_Return), _qt_int(Qt.Key_Space), _qt_int(Qt.Key_Tab), _qt_int(Qt.Key_Backtab),
                                 _qt_int(Qt.Key_Backspace), _qt_int(Qt.Key_Delete), _qt_int(Qt.Key_Escape))))):

            # change Shift+Backtab into Shift+Tab
            if key == _qt_int(Qt.Key_Backtab) and modifiers & SHIFT_MASK:
                key = _qt_int(Qt.Key_Tab) | modifiers

            # remove the Shift modifier if it doen't make sense..
            elif (_qt_int(Qt.Key_Exclam) <= key <= _qt_int(Qt.Key_At)
                  # ... e.g ctrl+shift+! is impossible on, some,
                  # keyboards (because ! is shift+1)
                  or _qt_int(Qt.Key_Z) < key <= 0x0ff):
                key = key | (modifiers & ~SHIFT_MASK)

            else:
                key = key | modifiers

            # append max number of keystrokes
            if self._recseq.count() < self.MAX_NUM_KEYSTROKES:
                l = list(self._recseq)
                l.append(key)
                self._recseq = QtGui.QKeySequence(*l)

        self._modifiers = modifiers
        self.controlTimer()
        self.updateDisplay()

    def keyReleaseEvent(self, ev):
        if not self._isrecording:
            return QtWidgets.QPushButton.keyReleaseEvent(self, ev)
        
        current_modifiers = _qt_int(ev.modifiers())
        modifiers = current_modifiers & MODIFIERS_MASK
        ev.accept()

        self._modifiers = modifiers
        self.controlTimer()
        self.updateDisplay()

    def hideEvent(self, ev):
        if self._isrecording:
            self.cancelRecording()
        QtWidgets.QPushButton.hideEvent(self, ev)

    def controlTimer(self):
        if self._modifiers or self._recseq.isEmpty():
            self._timer.stop()
        else:
            self._timer.start(600)

    def startRecording(self):
        # self.setFocus(True)  # because of QTBUG 17810
        self.setDown(True)
        self.setStyleSheet("text-align: left;")
        self._isrecording = True
        self._recseq = QtGui.QKeySequence()
        app_mods = _qt_int(QtWidgets.QApplication.keyboardModifiers())
        self._modifiers = app_mods & MODIFIERS_MASK
        self.grabKeyboard()
        self.updateDisplay()

    def doneRecording(self):
        self._seq = self._recseq
        self.cancelRecording()
        self.clearFocus()
        self.parentWidget().keySequenceChanged.emit()

    def cancelRecording(self):
        if not self._isrecording:
            return
        self.setDown(False)
        self.setStyleSheet("")
        self._isrecording = False
        self.releaseKeyboard()
        self.updateDisplay()


def _find_menu_items(menu, _path=None, _top_menu_name=None):
    """Extracts items from a given Nuke menu

    Returns a list of strings, with the path to each item

    Ignores divider lines and hidden items (ones like "@;&CopyBranch" for shift+k)

    >>> found = _find_menu_items(nuke.menu("Nodes"))
    >>> found.sort()
    >>> found[:5]
    ['3D/Axis', '3D/Camera', '3D/CameraTracker', '3D/DepthGenerator', '3D/Geometry/Card']
    """

    if _top_menu_name is None:
        _top_menu_name = menu.name()
        # Ensure we have a valid context name (use stable unique ID if empty/None)
        if not _top_menu_name:
            # Use object id to create stable unique context identifier
            # This prevents false conflicts across different unnamed menus
            _top_menu_name = "_unnamed_menu_%x" % id(menu)

    found = []

    mi = menu.items()
    for i in mi:
        if isinstance(i, nuke.Menu):
            # Sub-menu, recurse
            mname = i.name().replace("&", "")
            subpath = "/".join(x for x in (_path, mname) if x is not None)
            sub_found = _find_menu_items(menu = i, _path = subpath, _top_menu_name = _top_menu_name)
            found.extend(sub_found)
        elif isinstance(i, nuke.MenuItem):
            if i.name() == "":
                # Skip dividers
                continue
            if i.name().startswith("@;"):
                # Skip hidden items
                continue

            subpath = "/".join(x for x in (_path, i.name()) if x is not None)
            found.append({'menuobj': i, 'menupath': subpath, 'top_menu_name': _top_menu_name})

    return found


def _widget_with_label(towrap, text):
    """Wraps the given widget in a layout, with a label to the left
    """
    w = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    label = QtWidgets.QLabel(text)
    layout.addWidget(label)
    layout.addWidget(towrap)
    w.setLayout(layout)
    return w


def _load_yaml(path):
    def _load_internal():
        if not os.path.isfile(path):
            print("Settings file %r does not exist" % (path))
            return
        # Explicit UTF-8 for Py3 compatibility
        try:
            f = open(path, 'r', encoding='utf-8')
        except TypeError:
            f = open(path, 'r')
        
        overrides = json.load(f)
        f.close()
        return overrides

    # Catch any errors, print traceback and continue
    try:
        return _load_internal()
    except Exception:
        print("Error loading %r" % path)
        import traceback
        traceback.print_exc()

        return None


def _normalize_shortcut(shortcut):
    """Normalize a shortcut string for comparison.
    
    Converts QKeySequence objects to strings, handles empty/None values,
    and normalizes whitespace and case for reliable comparison.
    """
    if shortcut is None:
        return ""
    if hasattr(shortcut, 'toString'):
        # QKeySequence object
        result = shortcut.toString()
    elif isinstance(shortcut, basestring):
        result = shortcut
    else:
        try:
            result = str(shortcut)
        except Exception:
            return ""
    
    # Normalize: strip whitespace, convert to empty string if falsy
    result = result.strip() if result else ""
    return result


def _capture_default_shortcuts():
    """Capture default shortcuts from all menu items before user prefs are applied.
    
    Returns a dict mapping command identifiers (menu_name/path) to their
    default shortcut strings. This snapshot can be used to determine if
    a shortcut has been changed by the user.
    
    Note: This should be called before user preferences are restored,
    otherwise it will capture shortcuts that already include user changes.
    """
    defaults = {}
    
    for menu_name in ("Nodes", "Nuke", "Viewer", "Node Graph"):
        try:
            m = nuke.menu(menu_name)
            if m:
                items = _find_menu_items(m)
                for item in items:
                    try:
                        raw_shortcut = item['menuobj'].action().shortcut()
                        shortcut_str = _normalize_shortcut(raw_shortcut)
                        cmd_key = "%s/%s" % (item['top_menu_name'], item['menupath'])
                        defaults[cmd_key] = shortcut_str
                    except Exception:
                        # Skip items that can't be accessed
                        continue
        except Exception:
            # Skip menus that don't exist or can't be accessed
            continue
    
    return defaults


def _save_yaml(obj, path):
    def _save_internal():
        ndir = os.path.dirname(path)
        if not os.path.isdir(ndir):
            try:
                os.makedirs(ndir)
            except OSError as e:
                if e.errno != 17:  # errno 17 is "already exists"
                    raise

        # Explicit UTF-8 for Py3 compatibility
        try:
            f = open(path, "w", encoding='utf-8')
        except TypeError:
            f = open(path, "w")

        # TODO: Limit number of saved items to some sane number
        json.dump(obj, fp=f, sort_keys=True, indent=1, separators=(',', ': '))
        f.write("\n")
        f.close()

    # Catch any errors, print traceback and continue
    try:
        _save_internal()
    except Exception:
        print("Error saving shortcuteditor settings")
        import traceback
        traceback.print_exc()


def _restore_overrides(overrides):
    """Restore keyboard shortcuts from saved overrides.
    
    Only applies shortcuts to menu items that exist in Nuke. If a shortcut
    references a non-existent menu command, it is skipped (to avoid Nuke warnings)
    but preserved in the overrides dictionary so it remains in the JSON file.
    
    Missing/orphaned shortcuts can be logged by enabling DEBUG_MISSING_ITEMS
    or setting the SHORTCUTEDITOR_DEBUG environment variable.
    """
    missing_items = set()  # Track missing items for deduplicated logging
    
    for item_key, shortcut_key in overrides.items():
        menu_name, _, path = item_key.partition("/")
        
        # Get the menu object
        try:
            m = nuke.menu(menu_name)
            if m is None:
                # Menu doesn't exist
                if DEBUG_MISSING_ITEMS:
                    missing_items.add((path, menu_name))
                continue
        except Exception:
            # Menu access failed
            if DEBUG_MISSING_ITEMS:
                missing_items.add((path, menu_name))
            continue
        
        # Find the menu item
        menu_item = m.findItem(path)
        if menu_item is None:
            # Menu item doesn't exist - skip applying shortcut but keep in overrides
            if DEBUG_MISSING_ITEMS:
                missing_items.add((path, menu_name))
        else:
            # Menu item exists - apply the shortcut
            try:
                menu_item.setShortcut(shortcut_key)
            except Exception:
                # If setShortcut fails, log it if debug is enabled
                if DEBUG_MISSING_ITEMS:
                    missing_items.add((path, menu_name))
    
    # Log missing items once (deduplicated) if debug is enabled
    if DEBUG_MISSING_ITEMS and missing_items:
        for path, menu_name in sorted(missing_items):
            nuke.warning("ShortcutEditor: Menu item %r (menu: %r) does not exist, skipping shortcut" % (path, menu_name))


def _overrides_as_code(overrides):
    menus = {}
    for item, key in overrides.items():
        menu_name, _, path = item.partition("/")

        menus.setdefault(menu_name, []).append((path, key))

    lines = []
    for menu, things in menus.items():
        lines.append("cur_menu = nuke.menu(%r)" % menu)
        for path, key in things:
            lines.append("m = cur_menu.findItem(%r)" % path)
            lines.append("if m is not None:")
            lines.append("    m.setShortcut(%r)" % key)
            lines.append("")
    return "\n".join(lines)


class Overrides(object):
    def __init__(self):
        self.settings_path = os.path.expanduser("~/.nuke/shortcuteditor_settings.json")
        self.ui_prefs = {}  # UI preferences like show_only_changed

    def save(self):
        """Save settings to disk.
        
        Ensures UI preferences are saved without modifying shortcut mappings.
        The 'overrides' dict is preserved exactly as-is.
        """
        settings = {
            'overrides': self.overrides.copy(),  # Explicit copy to ensure no mutation
            'version': 1,
        }
        # Add UI preferences if they exist (separate key, does not modify overrides)
        if self.ui_prefs:
            settings['ui'] = self.ui_prefs.copy()  # Explicit copy for safety
        _save_yaml(obj=settings, path=self.settings_path)

    def clear(self):
        self.overrides = {}
        self.save()

    def load_settings_file(self):
        """Load settings file without applying shortcuts.
        
        Returns the loaded settings dict, or None if file doesn't exist.
        Useful for reading user preferences without modifying Nuke state.
        """
        return _load_yaml(path=self.settings_path)

    def restore(self):
        """Load the settings from disc, and update Nuke
        
        Captures default shortcuts before applying user preferences,
        storing them in the module-level cache for use by the UI widget.
        """
        global _default_shortcuts_cache
        
        # Only capture defaults if cache is empty (first time, before user prefs applied)
        # If cache already exists, don't overwrite it (it contains true defaults)
        if _default_shortcuts_cache is None:
            # Capture defaults BEFORE applying user prefs
            _default_shortcuts_cache = _capture_default_shortcuts()
        
        settings = _load_yaml(path=self.settings_path)

        # Default
        self.overrides = {}
        self.ui_prefs = {}

        if settings is None:
            return

        elif int(settings['version']) == 1:
            self.overrides = settings['overrides']
            # Load UI preferences if they exist (backwards compatible)
            if 'ui' in settings and isinstance(settings['ui'], dict):
                self.ui_prefs = settings['ui']
            _restore_overrides(self.overrides)

        else:
            nuke.warning("Wrong version of shortcut editor config, nothing loaded (version was %s expected 1), path was %r" % (
                int(settings['version']),
                self.settings_path))
            return


class ShortcutEditorWidget(QtWidgets.QDialog):
    closed = QtCore.Signal()

    def __init__(self):
        QtWidgets.QDialog.__init__(self)

        # Load settings from disc, and into Nuke
        self.settings = Overrides()
        self.settings.restore()

        # Window setup
        self.setWindowTitle("Shortcut editor")
        self.setMinimumSize(600, 500)

        # Internal things
        self._search_timer = None
        self._cache_items = None
        # Track which commands are in user prefs (changed shortcuts)
        self._user_prefs_map = self.settings.overrides.copy()

        # Stack widgets atop each other
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Search group
        search_group = QtWidgets.QGroupBox("Filtering")
        search_layout = QtWidgets.QVBoxLayout()
        search_group.setLayout(search_layout)

        # Top row: search filters
        search_row = QtWidgets.QHBoxLayout()
        search_layout.addLayout(search_row)

        # By-key filter bar
        key_filter = KeySequenceWidget()
        key_filter.keySequenceChanged.connect(self.filter_entries)
        self.key_filter = key_filter

        search_row.addWidget(_widget_with_label(key_filter, "Search by key"))

        # text filter bar
        search_input = QtWidgets.QLineEdit()
        search_input.textChanged.connect(self.search)
        self.search_input = search_input
        search_row.addWidget(
            _widget_with_label(search_input, "Search by text"))

        # Bottom row: filter toggles
        filter_row = QtWidgets.QHBoxLayout()
        search_layout.addLayout(filter_row)
        
        # Show user-altered shortcuts toggle
        show_changed_checkbox = QtWidgets.QCheckBox("Show User-Altered Shortcuts")
        show_changed_checkbox.setToolTip(
            "Filter to show only shortcuts that differ from Nuke's defaults.\n"
            "Includes: shortcuts added, changed, or cleared by the user.")
        # Load saved state (defaults to False if not set)
        show_changed_state = self.settings.ui_prefs.get('show_only_changed', False)
        show_changed_checkbox.setChecked(show_changed_state)
        show_changed_checkbox.stateChanged.connect(self.on_show_changed_toggled)
        self.show_changed_checkbox = show_changed_checkbox
        filter_row.addWidget(show_changed_checkbox)
        
        # Show only conflicts toggle
        show_conflicts_checkbox = QtWidgets.QCheckBox("Show Only Conflicts")
        show_conflicts_checkbox.setToolTip(
            "Filter to show only shortcuts that have conflicts within the same context.\n"
            "Conflicts occur when multiple commands share the same shortcut in the same menu.")
        # Load saved state (defaults to False if not set)
        show_conflicts_state = self.settings.ui_prefs.get('show_only_conflicts', False)
        show_conflicts_checkbox.setChecked(show_conflicts_state)
        show_conflicts_checkbox.stateChanged.connect(self.on_show_conflicts_toggled)
        self.show_conflicts_checkbox = show_conflicts_checkbox
        filter_row.addWidget(show_conflicts_checkbox)

        layout.addWidget(search_group)

        # Main table
        table = QtWidgets.QTableWidget()
        table.setColumnCount(3)  # Shortcut, Status, Menu location

        table.setColumnWidth(0, 150)  # Shortcut
        # Status column: will be auto-sized after populating, start with reasonable default
        table.setColumnWidth(1, 80)  # Default width, will be adjusted to fit content
        table.horizontalHeader().setStretchLastSection(True)  # Menu location
        table.verticalHeader().setVisible(False)

        self.table = table
        layout.addWidget(table)

        # Buttons at bottom
        button_reset = QtWidgets.QPushButton("Reset...")
        button_reset.clicked.connect(self.reset)
        layout.addWidget(button_reset)
        self.button_reset = button_reset

        button_as_code = QtWidgets.QPushButton("Copy as menu.py snippet...")
        button_as_code.clicked.connect(self.show_as_code)
        layout.addWidget(button_as_code)
        self.button_as_code = button_as_code


        button_close = QtWidgets.QPushButton("Close")
        button_close.clicked.connect(self.close)
        layout.addWidget(button_close)
        self.button_close = button_close

        # Go
        self.populate()

    def search(self):
        """Handles changes to search box

        Gives a slight delay between filtering the list, so quickly
        typing doesn't update once for every letter
        """
        if self._search_timer is not None:
            # Timer already set, reset
            self._search_timer.stop()
            self._search_timer.start(200)
        else:
            self._search_timer = QtCore.QTimer()
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(self.filter_entries)
            self._search_timer.start(200)  # 200ms timeout

    def is_changed(self, menuitem):
        """Determine if a shortcut has been changed by the user.
        
        A shortcut is considered "changed" if it exists in the user preferences
        JSON file, indicating the user has explicitly interacted with it.
        
        Changed shortcuts include:
        - Shortcuts added where default was empty/none (user added a shortcut)
        - Default shortcuts changed to different key sequences (user modified it)
        - Default shortcuts removed/cleared (set to empty string in prefs)
        - Missing/orphaned shortcuts that exist in user prefs (user set it, but
          the command was later removed from Nuke)
        
        Note: This method compares against the user preferences JSON, not against
        Nuke's current defaults. Since user prefs are applied on startup before
        the widget opens, we use the JSON file as the source of truth for what
        the user has changed.
        
        Returns True if the shortcut has been changed, False otherwise.
        """
        cmd_key = "%s/%s" % (menuitem['top_menu_name'], menuitem['menupath'])
        # If command is in user prefs, it's been changed (user interacted with it)
        return cmd_key in self._user_prefs_map

    def get_change_status(self, menuitem):
        """Compute the change status for a menu item.
        
        Returns one of: 'ADDED', 'CLEARED', 'REPLACED', 'UNCHANGED'
        
        Status rules:
        - ADDED: user assigned a shortcut where default was empty/none
        - CLEARED: user removed a default shortcut (default had one, user now empty)
        - REPLACED: user shortcut differs from default (both non-empty and different)
        - UNCHANGED: same as default (no user override, or override matches default)
        """
        global _default_shortcuts_cache
        
        cmd_key = "%s/%s" % (menuitem['top_menu_name'], menuitem['menupath'])
        
        # Get default shortcut (normalized)
        default_shortcut = ""
        if _default_shortcuts_cache and cmd_key in _default_shortcuts_cache:
            default_shortcut = _normalize_shortcut(_default_shortcuts_cache[cmd_key])
        
        # Get user shortcut (normalized) - empty string if not in user prefs
        user_shortcut = ""
        if cmd_key in self._user_prefs_map:
            user_shortcut = _normalize_shortcut(self._user_prefs_map[cmd_key])
        
        # Determine status
        if cmd_key not in self._user_prefs_map:
            # No user override - unchanged
            return 'UNCHANGED'
        
        # User has an override entry
        if not default_shortcut and user_shortcut:
            # Default was empty, user added one
            return 'ADDED'
        elif default_shortcut and not user_shortcut:
            # Default had one, user cleared it
            return 'CLEARED'
        elif default_shortcut and user_shortcut:
            if default_shortcut == user_shortcut:
                # User override matches default (redundant override)
                return 'UNCHANGED'
            else:
                # User changed it to something different
                return 'REPLACED'
        else:
            # Both empty - unchanged
            return 'UNCHANGED'

    def get_effective_shortcut(self, menuitem):
        """Get the effective shortcut for a menu item.
        
        Returns the user shortcut if present, otherwise the default shortcut.
        Normalized for comparison.
        """
        global _default_shortcuts_cache
        
        cmd_key = "%s/%s" % (menuitem['top_menu_name'], menuitem['menupath'])
        
        # Check user prefs first
        if cmd_key in self._user_prefs_map:
            return _normalize_shortcut(self._user_prefs_map[cmd_key])
        
        # Fall back to default
        if _default_shortcuts_cache and cmd_key in _default_shortcuts_cache:
            return _normalize_shortcut(_default_shortcuts_cache[cmd_key])
        
        # Orphaned command - get from menuitem if available
        if menuitem.get('orphaned', False):
            return _normalize_shortcut(menuitem.get('shortcut_str', ''))
        
        return ""

    def detect_conflicts(self, menu_items):
        """Detect conflicts where multiple commands share the same effective shortcut.
        
        Conflicts are detected PER CONTEXT (menu). The same shortcut can be used
        in different contexts (e.g., "Node Graph" vs "Viewer") without conflict.
        A conflict only occurs when the same shortcut is used multiple times
        within the same context.
        
        Returns a dict mapping command keys to lists of conflicting command keys
        (within the same context). Only includes shortcuts that are non-empty.
        """
        # Build map: (context, effective_shortcut) -> list of command keys
        context_shortcut_to_commands = {}
        
        for menuitem in menu_items:
            cmd_key = "%s/%s" % (menuitem['top_menu_name'], menuitem['menupath'])
            # Get context, ensuring it's never None/empty (use stable unique ID if needed)
            context = menuitem.get('top_menu_name')
            if not context:
                # Fallback: create stable unique ID from cmd_key using SHA1
                context = "_unnamed_context_%s" % hashlib.sha1(cmd_key.encode("utf-8")).hexdigest()[:10]
            effective = self.get_effective_shortcut(menuitem)
            
            # Ignore empty shortcuts
            if effective:
                context_shortcut_key = (context, effective)
                if context_shortcut_key not in context_shortcut_to_commands:
                    context_shortcut_to_commands[context_shortcut_key] = []
                context_shortcut_to_commands[context_shortcut_key].append(cmd_key)
        
        # Build conflict map: command -> list of conflicting commands (same context only)
        conflicts = {}
        for (context, shortcut), cmd_keys in context_shortcut_to_commands.items():
            if len(cmd_keys) > 1:
                # This shortcut has conflicts within this context
                for cmd_key in cmd_keys:
                    # List all other commands sharing this shortcut in the same context
                    conflicts[cmd_key] = [c for c in cmd_keys if c != cmd_key]
        
        # Debug statistics logging (at most once per session)
        global _debug_stats_printed_conflicts
        if DEBUG_STATS and not _debug_stats_printed_conflicts:
            conflict_count = len(conflicts)
            print("ShortcutEditor: %d conflicts detected across all contexts" % conflict_count)
            _debug_stats_printed_conflicts = True
        
        return conflicts

    def on_show_changed_toggled(self, state):
        """Handle the "Show User-Altered Shortcuts" checkbox toggle.
        
        Saves the state to UI preferences and refreshes the filter.
        """
        is_checked = (state == Qt.Checked)
        self.settings.ui_prefs['show_only_changed'] = is_checked
        self.settings.save()
        # Refresh the filter to apply the new state
        self.filter_entries()

    def on_show_conflicts_toggled(self, state):
        """Handle the "Show Only Conflicts" checkbox toggle.
        
        Saves the state to UI preferences and refreshes the filter.
        """
        is_checked = (state == Qt.Checked)
        self.settings.ui_prefs['show_only_conflicts'] = is_checked
        self.settings.save()
        # Refresh the filter to apply the new state
        self.filter_entries()

    def filter_entries(self):
        """Iterate through the rows in the table and hide/show according to filters
        
        Filters by:
        - Text search (menu path)
        - Key sequence search
        - "Show User-Altered Shortcuts" toggle (if enabled)
        - "Show Only Conflicts" toggle (if enabled)
        
        Note: This function does NOT mutate the underlying data. It only controls
        row visibility. The master list from list_menu() remains unchanged.
        """
        # Get the master list (this is never mutated, only used for filtering)
        menu_items = self.list_menu()
        show_only_changed = self.show_changed_checkbox.isChecked()
        show_only_conflicts = self.show_conflicts_checkbox.isChecked()
        
        # Detect conflicts once if needed for filtering
        conflicts = None
        if show_only_conflicts:
            conflicts = self.detect_conflicts(menu_items)
        
        # Ensure we have enough rows in the table
        current_row_count = self.table.rowCount()
        if len(menu_items) > current_row_count:
            self.table.setRowCount(len(menu_items))

        for rownum, menuitem in enumerate(menu_items):
            # filter them, first by the input text
            search = self.search_input.text()
            found = search.lower() in menuitem['menupath'].lower().replace("&", "")

            # ..and also filter by the shortcut, if one is specified
            key_match = True
            filter_seq = self.key_filter.shortcut()
            if not filter_seq.isEmpty():
                # Handle orphaned commands (no menuobj)
                if menuitem.get('orphaned', False):
                    shortcut_str = menuitem.get('shortcut_str', '')
                    current_sc = QtGui.QKeySequence(shortcut_str)
                else:
                    current_sc = menuitem['menuobj'].action().shortcut()
                    if isinstance(current_sc, basestring):
                        current_sc = QtGui.QKeySequence(current_sc)
                
                key_match = current_sc == filter_seq

            # Filter by "show only changed" if enabled
            changed_match = True
            if show_only_changed:
                status = self.get_change_status(menuitem)
                # Show only ADDED, CLEARED, REPLACED (not UNCHANGED)
                changed_match = status != 'UNCHANGED'

            # Filter by "show only conflicts" if enabled
            conflict_match = True
            if show_only_conflicts:
                cmd_key = "%s/%s" % (menuitem['top_menu_name'], menuitem['menupath'])
                conflict_match = cmd_key in conflicts

            keep_result = all([found, key_match, changed_match, conflict_match])
            # Explicitly show/hide each row based on filter result
            self.table.setRowHidden(rownum, not keep_result)
        
        # Ensure any extra rows beyond menu_items are hidden
        for rownum in range(len(menu_items), self.table.rowCount()):
            self.table.setRowHidden(rownum, True)

    def list_menu(self):
        """Gets the list-of-dicts containing all menu items

        Includes both existing menu items and orphaned/missing commands
        that exist in user preferences. Caches for speed of filtering.
        """
        if self._cache_items is not None:
            return self._cache_items
        else:
            items = []
            existing_cmd_keys = set()
            
            # Get all existing menu items
            for menu in ("Nodes", "Nuke", "Viewer", "Node Graph"):
                m = nuke.menu(menu)
                if m:
                    menu_items = _find_menu_items(m)
                    items.extend(menu_items)
                    # Track which commands exist
                    for item in menu_items:
                        cmd_key = "%s/%s" % (item['top_menu_name'], item['menupath'])
                        existing_cmd_keys.add(cmd_key)
            
            # Add orphaned/missing commands from user prefs
            orphaned_count = 0
            for cmd_key, shortcut_str in self._user_prefs_map.items():
                if cmd_key not in existing_cmd_keys:
                    # This is an orphaned command - create a placeholder entry
                    menu_name, _, path = cmd_key.partition("/")
                    # Ensure menu_name is never empty (use stable unique ID)
                    if not menu_name:
                        # Use SHA1 of cmd_key to create stable unique identifier
                        menu_name = "_unnamed_orphan_%s" % hashlib.sha1(cmd_key.encode("utf-8")).hexdigest()[:10]
                    items.append({
                        'menuobj': None,  # No menu object for orphaned commands
                        'menupath': path,
                        'top_menu_name': menu_name,
                        'orphaned': True,  # Mark as orphaned
                        'shortcut_str': shortcut_str  # Store the shortcut from prefs
                    })
                    orphaned_count += 1
            
            # Debug statistics logging (at most once per session)
            global _debug_stats_printed_orphaned
            if DEBUG_STATS and not _debug_stats_printed_orphaned:
                print("ShortcutEditor: %d orphaned shortcuts in user prefs" % orphaned_count)
                _debug_stats_printed_orphaned = True
            
            self._cache_items = items
            return items

    def _create_status_badge(self, status):
        """Create a status label with text color only (no background).
        
        For UNCHANGED: returns empty label (blank cell).
        For ADDED/CLEARED/REPLACED: returns label with colored text only.
        """
        if status == 'UNCHANGED':
            # Return empty label for UNCHANGED
            return QtWidgets.QLabel("")
        
        label = QtWidgets.QLabel(status)
        color = STATUS_COLORS.get(status, STATUS_COLORS['UNCHANGED'])
        # Use text color only, no background, with padding for readability
        label.setStyleSheet(
            "color: %s; "
            "font-size: 10px; "
            "font-weight: bold; "
            "padding: 2px 4px; "
            "margin: 1px;" % color
        )
        label.setAlignment(Qt.AlignCenter)
        # Ensure label has proper size hint for column auto-sizing
        label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        return label

    def _create_conflict_tooltip(self, conflicting_commands):
        """Create a conflict tooltip text."""
        if not conflicting_commands:
            return ""
        
        tooltip = "Conflict: This shortcut is also assigned to:\n"
        tooltip += "\n".join("  • %s" % cmd for cmd in conflicting_commands[:5])
        if len(conflicting_commands) > 5:
            tooltip += "\n  ... and %d more" % (len(conflicting_commands) - 5)
        return tooltip

    def populate(self):
        # Get menu items (includes orphaned commands)
        menu_items = self.list_menu()
        
        # Detect conflicts
        conflicts = self.detect_conflicts(menu_items)

        # Setup table
        self.table.clear()
        self.table.setRowCount(len(menu_items))
        self.table.setHorizontalHeaderLabels(['Shortcut', 'Status', 'Menu location'])

        # Add items
        for rownum, menuitem in enumerate(menu_items):
            cmd_key = "%s/%s" % (menuitem['top_menu_name'], menuitem['menupath'])
            status = self.get_change_status(menuitem)
            conflicting_commands = conflicts.get(cmd_key, [])
            conflict_tooltip = self._create_conflict_tooltip(conflicting_commands)
            
            # Handle orphaned commands (no menuobj)
            if menuitem.get('orphaned', False):
                # Orphaned command - use shortcut from prefs
                shortcut_str = menuitem.get('shortcut_str', '')
                shortcut = QtGui.QKeySequence(shortcut_str)
                
                widget = KeySequenceWidget()
                widget.setShortcut(shortcut)
                # Disable editing for orphaned commands (they can't be applied)
                widget.setEnabled(False)
                base_tooltip = "This menu command no longer exists in Nuke"
                if conflict_tooltip:
                    widget.setToolTip("%s\n\n%s" % (base_tooltip, conflict_tooltip))
                else:
                    widget.setToolTip(base_tooltip)
                
                self.table.setCellWidget(rownum, 0, widget)  # Shortcut column
            else:
                # Normal menu item
                raw_shortcut = menuitem['menuobj'].action().shortcut()
                shortcut = QtGui.QKeySequence(raw_shortcut)

                widget = KeySequenceWidget()
                widget.setShortcut(shortcut)
                
                # Always set tooltip (empty string clears it if no conflicts)
                # This ensures tooltips update immediately when conflicts are resolved
                widget.setToolTip(conflict_tooltip if conflict_tooltip else "")

                self.table.setCellWidget(rownum, 0, widget)  # Shortcut column

                widget.keySequenceChanged.connect(lambda menu_item=menuitem, w=widget: self.setkey(menuitem=menu_item,
                                                                                                   shortcut_widget=w))
            
            # Status badge (column 1)
            status_badge = self._create_status_badge(status)
            self.table.setCellWidget(rownum, 1, status_badge)
            
            # Menu location (column 2)
            if menuitem.get('orphaned', False):
                label_text = "%s (menu: %s) [Missing]" % (menuitem['menupath'], menuitem['top_menu_name'])
            else:
                label_text = "%s (menu: %s)" % (menuitem['menupath'], menuitem['top_menu_name'])
            self.table.setCellWidget(rownum, 2, QtWidgets.QLabel(label_text))
            
            # Apply conflict highlighting (subtle red-tinted background)
            if conflicting_commands:
                for col in range(3):
                    item = self.table.item(rownum, col)
                    if item is None:
                        item = QtWidgets.QTableWidgetItem()
                        self.table.setItem(rownum, col, item)
                    item.setBackground(QtGui.QColor(STATUS_COLORS['CONFLICT_BG']))
        
        # Auto-resize Status column to fit content (ensure all status text is visible)
        # Process events to ensure widgets are rendered before measuring
        QtWidgets.QApplication.processEvents()
        self.table.resizeColumnToContents(1)
        # Add padding to prevent text cutoff and improve readability
        current_width = self.table.columnWidth(1)
        if current_width > 0:
            self.table.setColumnWidth(1, current_width + 12)  # Add 12px padding for margins
        
        # Reapply filters after populating (to respect filter toggle states)
        self.filter_entries()

    def setkey(self, menuitem, shortcut_widget):
        """Called when shortcut is edited

        Updates the Nuke menu, and puts the key in the Overrides setting-thing
        """

        # Check if shortcut is already assigned to something else:
        shortcut_str = shortcut_widget.shortcut().toString()
        menu_items = self.list_menu()
        for index, other_item in enumerate(menu_items):
            # Skip orphaned items when checking conflicts (they can't have active shortcuts)
            if other_item.get('orphaned', False):
                continue
                
            other_sc = other_item['menuobj'].action().shortcut()
            if hasattr(other_sc, 'toString'):
                other_sc = other_sc.toString()
            else:
                other_sc = QtGui.QKeySequence(other_sc).toString()

            if shortcut_str and other_sc == shortcut_str and other_item is not menuitem:
                answer = self._confirm_override(other_item, shortcut_str)
                if answer is None:
                    # Cancel editing - reset widget to original key then stop
                    if not menuitem.get('orphaned', False):
                        shortcut_widget.setShortcut(QtGui.QKeySequence(menuitem['menuobj'].action().shortcut()))
                    return
                elif answer is True:
                    # Un-assign the shortcut first
                    if not other_item.get('orphaned', False):
                        other_item['menuobj'].setShortcut('')
                    other_cmd_key = "%s/%s" % (other_item['top_menu_name'], other_item['menupath'])
                    self.settings.overrides[other_cmd_key] = ""
                    # Update user prefs map for "show only changed" filter
                    self._user_prefs_map[other_cmd_key] = ""
                    if self.table.cellWidget(index, 0):
                        self.table.cellWidget(index, 0).setShortcut(QtGui.QKeySequence(""))
                elif answer is False:
                    # Keep both shortcuts
                    pass

        # Only set shortcut if menu item exists (not orphaned)
        if not menuitem.get('orphaned', False):
            menuitem['menuobj'].setShortcut(shortcut_str)
        
        cmd_key = "%s/%s" % (menuitem['top_menu_name'], menuitem['menupath'])
        self.settings.overrides[cmd_key] = shortcut_str
        # Update user prefs map for "show only changed" filter
        self._user_prefs_map[cmd_key] = shortcut_str
        
        # Invalidate cache and refresh table to update status/conflict indicators
        self._cache_items = None
        self.populate()  # populate() will call filter_entries() at the end

    def _confirm_override(self, menu_item, shortcut):
        """Ask the user if they are sure they want to override the shortcut
        """
        mb = QtWidgets.QMessageBox(self)

        mb.setText("Shortcut '%s' is already assigned to %s (Menu: %s)." % (shortcut,
                                                                            menu_item['menupath'],
                                                                            menu_item['top_menu_name']))
        mb.setInformativeText("If two shortucts have same key and are in same context (e.g both Viewer shortcuts), they may not function as expected")
        mb.setIcon(QtWidgets.QMessageBox.Warning)

        mb.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel)
        mb.setDefaultButton(QtWidgets.QMessageBox.Yes)

        button_yes = mb.button(QtWidgets.QMessageBox.Yes)
        button_yes.setText('Clear existing shortcut')

        button_yes = mb.button(QtWidgets.QMessageBox.No)
        button_yes.setText('Keep both')

        ret = _run_dialog(mb)
        # TODO: More explicit return value than Optional[bool]?
        if ret == QtWidgets.QMessageBox.Yes:
            return True
        elif ret == QtWidgets.QMessageBox.No:
            return False
        elif ret == QtWidgets.QMessageBox.Cancel:
            return None

    def reset(self):
        """Reset some or all of the key overrides
        """

        mb = QtWidgets.QMessageBox(
            self,
        )

        mb.setText("Clear all key overrides?")
        mb.setInformativeText("Really remove all %s key overrides?" % len(self.settings.overrides))
        mb.setDetailedText(
            "Will reset the following to defaults:\n\n"
            + "\n".join("%s (key: %s)" % (p, k or "(blank)") for (p, k) in self.settings.overrides.items()))

        mb.setIcon(QtWidgets.QMessageBox.Warning)

        mb.setStandardButtons(QtWidgets.QMessageBox.Reset | QtWidgets.QMessageBox.Cancel)
        mb.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        ret = _run_dialog(mb)

        if ret == QtWidgets.QMessageBox.Reset:
            self.settings.clear()
            # Clear user prefs map since all overrides are cleared
            self._user_prefs_map = {}
            self.close()
            QtWidgets.QMessageBox.information(None, "Reset complete", "You must restart Nuke for this to take effect")
        elif ret == QtWidgets.QMessageBox.Cancel:
            pass
        else:
            raise RuntimeError("Unhandled button")

    def show_as_code(self):
        """Show overrides as a Python snippet
        """

        mb = QtWidgets.QMessageBox(
            self,
        )

        mb.setText("menu.py snippet exporter")

        mb.setInformativeText(
            "A Python snippet has been generated in the 'Show Details' window\n\n"
            "This can be placed in menu.py and it can be shared with people not using the Shortcut Editor UI.\n\n"
            "Important note: Using this snippet will act confusingly if used while Shortcut Editor UI is also installed."
        )
        mb.setDetailedText(
            "# ShortcutEditor generated snippet:\n" + 
            _overrides_as_code(self.settings.overrides)
            + "# End ShortcutEditor generated snippet"
        )
        mb.setIcon(QtWidgets.QMessageBox.Warning)

        mb.setStandardButtons(QtWidgets.QMessageBox.Close)
        mb.setDefaultButton(QtWidgets.QMessageBox.Close)
        ret = _run_dialog(mb)

    def closeEvent(self, evt):
        """Save when closing the UI
        """

        self.settings.save()
        self.closed.emit()
        QtWidgets.QWidget.closeEvent(self, evt)

    def undercursor(self):
        """Move window to under cursor, avoiding putting it off-screen
        """
        def clamp(val, mi, ma):
            return max(min(val, ma), mi)

        # Get cursor position, and screen dimensions on active screen
        cursor = QtGui.QCursor().pos()
        
        # Compatibility QDesktopWidget vs QGuiApplication for Nuke 16+
        screen_geo = None
        if hasattr(QtGui, 'QGuiApplication'):
             screen = QtGui.QGuiApplication.screenAt(cursor)
             if screen:
                 screen_geo = screen.geometry()
        
        if screen_geo is None:
            try:
                screen_geo = QtWidgets.QDesktopWidget().screenGeometry(cursor)
            except (AttributeError, NameError):
                screen_geo = QtCore.QRect(0,0, 1920, 1080)

        # Get window position so cursor is just over text input
        # Ensure width is calculated even if not shown yet
        width = self.width()
        if width < 100: width = 600
        height = self.height()
        if height < 100: height = 500

        xpos = cursor.x() - (width/2)
        ypos = cursor.y() - 13

        # Clamp window location to prevent it going offscreen
        xpos = clamp(xpos, screen_geo.left(), screen_geo.right() - width)
        ypos = clamp(ypos, screen_geo.top(), screen_geo.bottom() - (height-13))

        # Move window
        self.move(int(xpos), int(ypos))


def load_shortcuts():
    """Load the settings from disc

    Could be called from menu.py (see module docstring at start of
    file for an example)
    """
    s = Overrides()
    s.restore()


_sew_instance = None


def gui():
    """Launch the key-override editor GUI

    Could be called from menu.py (see module docstring at start of
    file for an example)
    """
    global _sew_instance

    if _sew_instance is not None:
        # Already an instance (make it really obvious - focused, in
        # front and under cursor, like other Nuke GUI windows)
        _sew_instance.show()
        _sew_instance.undercursor()
        _sew_instance.setFocus()
        _sew_instance.activateWindow()
        _sew_instance.raise_()
        return

    # Make a new instance, keeping it in a global variable to avoid
    # multiple instances being opened
    _sew_instance = ShortcutEditorWidget()

    def when_closed():
        global _sew_instance
        _sew_instance = None

    _sew_instance.closed.connect(when_closed)

    modal = False
    if modal:
        _run_dialog(_sew_instance)
    else:
        _sew_instance.show()



def nuke_setup():
    """Call this from menu.py to setup stuff
    """

    # Load saved shortcuts once Nuke has started up (i.e when it has
    # created the Root node - otherwise some menu items might be
    # created after this function runs)
    nuke.addOnCreate(lambda: load_shortcuts(), nodeClass="Root")

    # Menu item to open shortcut editor
    nuke.menu("Nuke").addCommand("Edit/Edit keyboard shortcuts", gui)


if __name__ == "__main__":
    nuke_setup()
