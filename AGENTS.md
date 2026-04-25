# Agent Instructions

This document provides guidelines for AI agents and developers working on this repository.

## Development Workflow

### 1. Code Standards
- Adhere to PEP 8 and project-specific linting rules.
- Use type hints for all function signatures.

### 2. Validation (Mandatory)
Before finishing any task or submitting changes, you **must** run the following suite to ensure code quality and type safety:

```bash
# Run linting and type checking
uv run ruff check . && uv run ty check
```

### 3. Dependency Management
- Use `uv` for all package operations.
- Add production dependencies with `uv add <package>`.
- Add development dependencies with `uv add --dev <package>`.

### 4. Supabase Integration
- Credentials are currently hardcoded in `main.py` per project requirements. 
- Use the `supabase` client instance for database interactions.
