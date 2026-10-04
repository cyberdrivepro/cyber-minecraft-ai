# Contributing to Cyber Minecraft AI Mod Builder

Thank you for your interest in contributing to **Cyber Minecraft AI Mod Builder**! 

## Code of Conduct
We are committed to providing a friendly, safe, and welcoming environment for all contributors.

## Local Development Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/cyberdrivepro/cyber-minecraft-ai.git
   cd cyber-minecraft-ai
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install development dependencies:
   ```bash
   pip install -r requirements.txt
   pip install pytest pytest-asyncio flake8
   ```

4. Run tests:
   ```bash
   pytest tests/ -v
   ```

## Development Guidelines

- **Deterministic Generation First**: Never rely entirely on unconstrained LLM code synthesis. Always use validated Pydantic schemas and deterministic templates in `builders/`.
- **Security**: Always sanitize identifiers using `core.security.sanitize_identifier()` and validate file paths using `core.security.validate_safe_path()`.
- **Formatting & Secrets**: Never commit real tokens or credentials. All secrets belong in `.env` (ignored by git) or Hugging Face Space Secrets.

## Submitting Pull Requests

1. Create a descriptive feature branch:
   ```bash
   git checkout -b feature/custom-particle-effects
   ```
2. Commit your changes with clear semantic messages (`feat: ...`, `fix: ...`).
3. Run the automated test suite and ensure all tests pass.
4. Push to your fork and submit a Pull Request against `main`.
