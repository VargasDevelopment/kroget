# Changelog

## v0.4.0 (2026-01-17)

### Feat

- add cli flag to load an existing proposal.json into the tui

### Fix

- **tui.py**: keep proposal ui state in sync with in-memory proposal

## v0.3.0 (2026-01-15)

### Feat

- **tui.py**: show list item preview in lists view

### Fix

- **storage**: isolate test data dir and prevent sent history pollution

## v0.2.3 (2026-01-14)

### Fix

- **tui.py**: auto-highlight active list in lists view
- prevent apply with empty proposals and show friendly errors

## v0.2.2 (2026-01-13)

### Fix

- **tui.py**: changed staples verbiage to items in tui
- remove unused openapi cli dev command and openapi specs

### Refactor

- **cli.py**: implemented lists-scoped items command; deprecated staples

## v0.2.1 (2026-01-13)

### Fix

- **tui.py**: use alternative now works with row highlight
- **tui.py**: instant load proposal, lazy load alternatives; rename pin for discovery
- always populate alternatives even with pinned UPC

## v0.2.0 (2026-01-11)

### Feat

- add --version flag to CLI

## v0.1.1 (2026-01-11)

### Fix

- **tui.py**: add staples respects modality default; tui modality button displays correct value

## v0.1.0 (2026-01-10)
