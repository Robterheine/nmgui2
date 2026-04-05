# Contributing to NMGUI2

Thank you for your interest in improving NMGUI2.

## How to contribute

### Reporting bugs

Open an [issue](https://github.com/robterheine/nmgui2/issues) and include:
- Your operating system and Python version (`python3 --version`)
- PyQt6 version (`pip show PyQt6`)
- What you expected to happen and what happened instead
- The full error message from the terminal if there is one
- A minimal example that reproduces the problem if possible

### Requesting features

Open an issue with the label `enhancement`. Describe your use case — what are you trying to do and why would it be useful to others?

### Submitting code

1. Fork the repository on GitHub
2. Create a branch for your change: `git checkout -b my-feature`
3. Make your changes in `nmgui2.py`
4. Test on your platform
5. Open a pull request with a clear description of what changed and why

### Code style

- Single-file architecture (`nmgui2.py`) — keep it that way for simplicity
- Follow the existing patterns for Qt widgets, signals and slots
- Add a comment above any non-obvious logic
- Test with both dark and light themes if changing UI code

## Architecture overview

```
nmgui2.py          Main application — all UI, logic, and rendering
parser.py          NONMEM output parser — do not modify unless fixing a parse bug
```

Configuration lives in `~/.nmgui/` and is never committed.

## Areas most in need of help

- **Parsing** — NONMEM output varies widely between versions; edge cases in `parser.py` are common
- **Windows testing** — primary development is on macOS; Windows-specific issues welcome
- **Linux testing** — same as above
- **New plot types** — additional diagnostic plots for model evaluation
- **Documentation** — tutorials, worked examples, screenshots
