# Contributing to ResGov

Thanks for your interest. Here's how to contribute:

## Setup

```bash
git clone https://github.com/michael-ebering/resgov.git
cd resgov
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Code Style

- Python 3.12+, type hints where meaningful
- Functions: `snake_case`, Classes: `PascalCase`
- Docstrings for public methods
- No external dependencies for core functionality

## Testing

```bash
pytest tests/ -v
```

All PRs must pass existing tests. New features require new tests.

## Pull Request Process

1. Fork and create a feature branch
2. Add tests for new functionality
3. Ensure `pytest tests/ -v` passes
4. Update README.md if adding features
5. Open PR with clear description of changes

## Code Review

PRs are reviewed for:
- Correctness and thread safety
- Test coverage
- API consistency
- Documentation

## License

By contributing, you agree your contributions will be licensed under MIT.
