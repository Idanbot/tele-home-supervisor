# Contributing to tele-home-supervisor

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to this project.

## Development Setup

### Prerequisites

- Python 3.13.x
- [uv](https://github.com/astral-sh/uv) package manager
- Docker (for testing containerized functionality)
- Git

### Getting Started

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/tele-home-supervisor.git
   cd tele-home-supervisor
   ```

2. **Install dependencies**
   ```bash
   # Install uv if not already installed
   curl -LsSf https://astral.sh/uv/install.sh | sh
   
   # Install project dependencies
   uv sync
   ```

3. **Install pre-commit hooks**
   ```bash
   uv run pre-commit install
   ```

4. **Set up environment variables**
   ```bash
   export BOT_TOKEN=your_test_bot_token
   export ALLOWED_CHAT_IDS=your_chat_id
   ```

## Code Style

This project uses [Ruff](https://github.com/astral-sh/ruff) for linting and formatting.

### Running Code Quality Checks

```bash
# Lint code
uv run ruff check .

# Format code
uv run ruff format .

# Security scan
uv run bandit -r tele_home_supervisor

# Run all checks
uv run ruff check . && uv run ruff format . && uv run bandit -r tele_home_supervisor
```

### Code Style Guidelines

- **Type Hints**: Use type hints for all function signatures
- **Docstrings**: Add comprehensive docstrings for all public functions and classes
  - Use Google-style docstrings
  - Include Args, Returns, Raises, and Example sections where appropriate
- **Error Handling**: Use proper exception handling with informative logging
- **Async/Await**: Use async functions for I/O-bound operations
- **Naming**: Follow PEP 8 naming conventions
  - Functions and variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest tests/

# Run with verbose output
uv run pytest tests/ -v

# Run with coverage
uv run pytest tests/ --cov=tele_home_supervisor

# Run specific test file
uv run pytest tests/test_utils.py
```

### Writing Tests

- Place tests in the `tests/` directory
- Name test files as `test_*.py`
- Use descriptive test function names: `test_<function>_<scenario>`
- Use pytest fixtures for common setup
- Mock external dependencies (APIs, file system, network)

Example test:
```python
import pytest
from tele_home_supervisor.utils import fmt_bytes

def test_fmt_bytes_converts_correctly():
    assert fmt_bytes(1024) == "1.0 KiB"
    assert fmt_bytes(1536) == "1.5 KiB"
    assert fmt_bytes(1073741824) == "1.0 GiB"
```

## Making Changes

### Branch Naming

- Feature: `feature/description`
- Bug fix: `fix/description`
- Documentation: `docs/description`

### Commit Messages

Follow conventional commits:
- `feat: add new command for system monitoring`
- `fix: correct memory calculation in health check`
- `docs: update README with new examples`
- `refactor: simplify error handling in CLI`
- `test: add tests for DNS lookup functionality`

### Pull Request Process

1. Create a new branch from `main`
2. Make your changes following the code style guidelines
3. Add or update tests as needed
4. Ensure all tests pass and linters are happy
5. Update documentation if needed
6. Submit a pull request with:
   - Clear description of changes
   - Reference to any related issues
   - Screenshots for UI changes (if applicable)

## Project Structure

Understanding the codebase:

```
tele_home_supervisor/
├── main.py           # Application entry point
├── commands.py       # Command registry (single source of truth)
├── config.py         # Configuration from environment variables
├── state.py          # Runtime state management
├── handlers/         # Command handlers organized by category
│   ├── dispatch.py   # Rate-limiting wrapper
│   ├── common.py     # Shared utilities (auth, rate limit)
│   └── *.py          # Category-specific handlers
├── services.py       # Business logic layer
├── utils.py          # Low-level system utilities
├── cli.py            # Command execution helpers
├── torrent.py        # qBittorrent API client
└── ai_service.py     # Ollama integration
```

### Key Concepts

- **Separation of Concerns**: Handlers → Services → Utils
- **Async First**: All I/O operations are async
- **State Management**: Centralized in `BotState` class
- **Configuration**: Environment variables via `config.py`
- **Rate Limiting**: Applied to all handlers via decorator

## Adding New Features

### Adding a New Command

1. **Define the command** in `commands.py`:
   ```python
   CommandSpec(
       "mycommand",
       (),  # aliases
       "Category",
       "/mycommand <arg>",
       "description",
       handler="cmd_mycommand",
   )
   ```

2. **Create the handler** in appropriate `handlers/*.py` file:
   ```python
   async def cmd_mycommand(update: Update, context: ContextTypes.DEFAULT_TYPE):
       """Handle /mycommand command."""
       if not await guard(update, context):
           return
       
       # Your logic here
       await update.message.reply_text("Response")
   ```

3. **Register in dispatch.py**:
   ```python
   cmd_mycommand = rate_limit(category.cmd_mycommand)
   ```

4. **Add tests** in `tests/`:
   ```python
   def test_mycommand_success():
       # Test implementation
       pass
   ```

## Security Guidelines

- Never commit secrets or tokens
- Use environment variables for configuration
- Validate and sanitize all user inputs
- Use parameterized queries (if adding database support)
- Run security scans before submitting PRs
- Report security vulnerabilities privately

## Getting Help

- Check existing issues and discussions
- Read the documentation in README.md
- Review similar code in the project
- Ask questions in GitHub Discussions

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
