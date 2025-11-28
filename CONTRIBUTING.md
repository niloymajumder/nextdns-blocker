# Contributing to NextDNS Blocker

Thank you for your interest in contributing! This guide will help you get started.

## How to Contribute

### Reporting Bugs

1. Check if the issue already exists in [Issues](https://github.com/aristeoibarra/nextdns-blocker/issues)
2. If not, create a new issue with:
   - Clear title describing the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Your environment (OS, Python version)

### Suggesting Features

1. Open an issue with the `enhancement` label
2. Describe the feature and its use case
3. Explain why it would be useful

### Code Contributions

#### Setup Development Environment

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/nextdns-blocker.git
cd nextdns-blocker

# Install dependencies
pip3 install -r requirements.txt
pip3 install -r requirements-dev.txt

# Run tests
pytest tests/ -v
```

#### Making Changes

1. **Fork** the repository
2. **Create a branch** for your feature:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** following the code style
4. **Add tests** for new functionality
5. **Run tests** to ensure everything passes:
   ```bash
   pytest tests/ -v
   ```
6. **Commit** with a clear message:
   ```bash
   git commit -m "feat: add your feature description"
   ```
7. **Push** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
8. **Open a Pull Request**

#### Commit Message Format

Use conventional commits:
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation changes
- `test:` adding or updating tests
- `refactor:` code refactoring

#### Code Style

- Follow PEP 8 guidelines
- Use type hints where possible
- Keep functions small and focused
- Add docstrings for public functions

### Documentation

Improvements to documentation are always welcome:
- Fix typos or unclear explanations
- Add examples
- Translate to other languages

## Project Structure

```
nextdns-blocker/
├── nextdns_blocker.py   # Main application
├── watchdog.py          # Cron protection
├── common.py            # Shared utilities (logging, file ops)
├── tests/               # Test suite (287 tests, 97% coverage)
│   ├── conftest.py      # Shared pytest fixtures
│   ├── test_client.py   # API client tests
│   ├── test_schedule.py # Schedule logic tests
│   ├── test_validation.py # Input validation tests
│   ├── test_config_loading.py # Config loading tests
│   ├── test_cli_commands.py # CLI command tests
│   ├── test_pause_protected.py # Pause/protected domain tests
│   └── test_watchdog.py # Watchdog tests
├── domains.json         # Domain configuration
├── domains.json.example # Example configuration
└── .env                 # Credentials (not in repo)
```

## Getting Help

- Open an issue for questions
- Check existing issues and discussions

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Focus on constructive feedback

Thank you for contributing!
