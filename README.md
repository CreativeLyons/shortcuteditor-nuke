# Nuke shortcut editor

`shortcuteditor` is a keyboard shortcut editor for
[Foundry's Nuke](https://www.foundry.com/products/nuke)

It allows you to quickly bind keyboard shortcuts to existing menu
items without writing Python code

[![tabtabtab](imgs/shortcuteditor_thumbnail.png)](imgs/shortcuteditor.png)

Watch the [first episode of Lars Wemmje's "Useful Nuke Tools"](https://vimeo.com/channels/nukepedia/135306112) for more details!


## Installation

Put `shortcuteditor.py` on PYTHONPATH or NUKE_PATH somewhere (probably
in `~/.nuke/`)

    mkdir -p ~/.nuke
    cd ~/.nuke
    curl -O https://raw.githubusercontent.com/dbr/shortcuteditor-nuke/v1.3/shortcuteditor.py


Then in `~/.nuke/menu.py` add the following:

    try:
        import shortcuteditor
        shortcuteditor.nuke_setup()
    except Exception:
        import traceback
        traceback.print_exc()


## Notes

The shortcuts overrides are saved in `~/.nuke/shortcuteditor_settings.json`

You can search for menu items either by name ("Search by text"), or by
existing shortcut ("Search by key"), or both (rarely necessary)

There are a few shortcuts you cannot (easily) override in the viewer
context, specifically things like the r/g/b and z/x/c shortcuts are
hardwired.

If you are changing an existing shortcut, be sure to clear the old usage of
the key. A popup appears to help with this if adding conflicting shortcuts.

### Missing/Orphaned Shortcuts

If your shortcuts JSON file contains entries for menu commands that no longer
exist in Nuke (e.g., after upgrading Nuke or removing plugins), those shortcuts
will be silently skipped during startup to avoid terminal warnings. The entries
remain in your JSON file and are preserved when saving.

To enable debug logging for missing menu items, set the environment variable:
```bash
export SHORTCUTEDITOR_DEBUG=1
```
This will print a single warning per missing menu item when Nuke starts.

### Show Only Changed Shortcuts

The shortcut editor includes a "Show only changed shortcuts" filter toggle in the
Filtering section. When enabled, the list displays only shortcuts that have been
modified by the user, making it easier to review your customizations.

A shortcut is considered "changed" if it exists in your preferences JSON file,
which includes:
- Shortcuts you've added (where the default was empty)
- Default shortcuts you've modified to different key sequences
- Default shortcuts you've cleared/removed
- Missing/orphaned shortcuts that you previously configured

The filter state (on/off) is saved in your preferences file and persists between
sessions. This filter works in combination with the text and key search filters.


## Future improvements

For a list of requested and planned features, see the project's issue tracker
on GitHub, https://github.com/dbr/shortcuteditor-nuke/issues

## Change log

* `v1.3` - 2021-08-10
  * Small fixes to support Nuke 13

* `v1.2` - 2020-08-12
  * Updated to support Nuke 11 and 12.
  * Warns when overriding an existing shortcut ([PR #12](https://github.com/dbr/shortcuteditor-nuke/pull/12) by [herronelou](https://github.com/herronelou))
  * Added button to export the key-overrides as a Python snippet.
  * Faster UI update for searching

* `v1.1` - 2014-08-23
 * Fixed error in error handling when a shortcut is added for a menu
   item which disappears.
 * `nuke_setup` method works as expected when installed earlier in
   NUKE_PATH. Previously it might run before some menu items were
   added, so the shortcut was never set.

* `v1.0` - 2013-10-09
 * Initial version
