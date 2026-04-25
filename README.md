# Secret Backend

A FastAPI backend integrated with Supabase and Scalar documentation.

## Setup

1. **Install uv**:
   Ensure you have `uv` installed on your system.

2. **Install Dependencies**:
   ```bash
   uv sync
   ```

3. **Run the Application**:
   ```bash
   uv run python main.py
   ```
   The API will be available at `http://localhost:8000`.

## Features
- **FastAPI**: Modern web framework for building APIs.
- **Scalar**: Interactive API documentation available at `/scalar`.
- **Supabase**: Backend-as-a-Service integration for database operations.
- **Linting & Types**: Powered by `ruff` and `ty`.
