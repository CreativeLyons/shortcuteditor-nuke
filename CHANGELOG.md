# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4] - 2026-01-27

### Added
- Support for Nuke 16+ with PySide6 compatibility
- "Show User-Altered Shortcuts" filter toggle to display only shortcuts modified by the user
- "Show Only Conflicts" filter toggle to display only shortcuts with conflicts within the same context
- Conflict detection and visual highlighting for shortcuts assigned to multiple commands in the same menu
- Status badges indicating whether shortcuts are ADDED, CLEARED, REPLACED, or UNCHANGED
- Orphaned shortcut handling: shortcuts for non-existent menu items are silently skipped during startup
- Debug logging for missing menu items via `SHORTCUTEDITOR_DEBUG` environment variable
- Debug statistics for conflicts and orphaned shortcuts via `SHORTCUTEDITOR_DEBUG_STATS` environment variable
- Improved Qt version detection with fallback support for Qt.py, PySide6, PySide2, and PySide

### Changed
- Improved handling of Qt6 enum values that don't cast directly to int
- Enhanced screen geometry detection for window positioning with compatibility for both QDesktopWidget and QGuiApplication

## [1.3] - 2021-08-10

### Fixed
- Python 3 compatibility: updated print statements and exception handling syntax
- Support for Nuke 13

## [1.2] - 2020-08-12

### Added
- Support for Nuke 11 and 12 with PySide2
- Warning dialog when assigning a shortcut that conflicts with an existing shortcut, with options to clear the existing shortcut or keep both
- "Copy as menu.py snippet" button to export key overrides as Python code
- Support for "Node Graph" menu in addition to Nodes, Nuke, and Viewer menus

### Changed
- Improved search performance: filtering now updates the UI without repopulating the entire table

## [1.1] - 2014-08-23

### Fixed
- Error handling when a shortcut is assigned to a menu item that no longer exists: changed from `nuke.warn()` to `nuke.warning()`
- Shortcut loading timing: `nuke_setup()` now defers loading shortcuts until after the Root node is created, ensuring all menu items are available before shortcuts are applied

## [1.0] - 2013-11-09

### Added
- Initial release
- Keyboard shortcut editor GUI for Nuke menu items
- Search by menu item name or existing shortcut key
- Save and restore shortcut overrides to JSON file
- Support for Nodes, Nuke, and Viewer menus
