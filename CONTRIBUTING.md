# Contributing to Kro-Get

Thanks for your interest in contributing! Kro-Get is a small, focused open-source project built for power users. The goal is to keep things reliable, predictable, and easy to reason about—both for humans and for automation.

This document outlines how to propose changes and what to expect when contributing.

---

## Ground Rules

- Be respectful and constructive.
- Prefer small, focused changes over large refactors.
- If you’re unsure about an approach, open an issue or draft PR first.

Kro-Get prioritizes **clarity and safety over cleverness**.

---

## Development Workflow

### Branching & Pull Requests

- The `main` branch is protected.
- **All changes must go through a pull request.**
- Direct pushes to `main` are disabled.
- At least **one approval is required** before merging (the maintainer may bypass this when appropriate).

Typical flow:
1. Fork the repo (or create a branch if you have access).
2. Create a feature or fix branch from `main`.
3. Make your changes.
4. Open a pull request targeting `main`.

---

## Commit Messages

This project uses **Commitizen** to standardize commit messages.

- Please create commits using:

```
cz commit
```

- Follow the interactive prompts when writing commit messages.
- This ensures commits are consistent and release-ready.

If you don’t have Commitizen installed, you can install it with:

```
pip install commitizen
```

---

## Code Style & Quality

- Python ≥ 3.12
- Follow existing patterns and structure.
- Prefer explicit, readable code over abstractions.
- Avoid introducing new dependencies unless clearly justified.

CI checks may be added over time, but contributors are expected to keep changes:
- reasonably formatted
- well-scoped
- easy to review

---

## Releases

Releases are tag-driven and follow the commit history produced by Commitizen.
Versions are derived from git tags via setuptools-scm.

### Release Process (Maintainer Only)

1. Ensure commits follow the Commitizen prompts.
2. Run `cz bump` to update `CHANGELOG.md` and create the tag.
3. Push with `git push --tags`, then `git push`.

Publishing to PyPI is handled from tags.

---

## What to Contribute

Good contribution ideas include:
- Bug fixes
- UX improvements (CLI or TUI)
- Documentation improvements
- Small quality-of-life enhancements
- Clear error messages

If you’re proposing a larger change, please open an issue first to discuss scope and tradeoffs.

---

## Security

- Do not include credentials, tokens, or secrets in commits or issues.
- If you believe you’ve found a security issue, please report it privately via GitHub security advisories rather than opening a public issue.

---

## Questions?

If something isn’t clear:
- Open an issue
- Ask in a draft PR
- Or start a discussion

Thanks again for contributing—every improvement helps keep Kro-Get calm, safe, and useful.
