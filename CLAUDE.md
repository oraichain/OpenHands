# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Build and Setup
```bash
# Initial setup - installs all dependencies and configures pre-commit hooks
make build

# Configure OpenHands (LLM settings, workspace directory)
make setup-config

# Start PostgreSQL database (required before running)
[ ! -f .env ] && cp .env.example .env
docker-compose up -d postgres
```

### Running the Application
```bash
# Run both frontend and backend (recommended)
make run

# Run backend only
make start-backend

# Run frontend only
make start-frontend

# Run in Docker
make docker-run

# Development in Docker container
make docker-dev
```

### Testing
```bash
# Run all frontend tests
make test

# Run Python unit tests
poetry run pytest ./tests/unit/test_*.py

# Run specific test file
poetry run pytest tests/unit/test_file_name.py -xvs

# Run integration tests
poetry run pytest ./tests/integration/

# Run evaluation benchmarks
cd evaluation && poetry run python -m pytest benchmarks/
```

### Linting and Code Quality
```bash
# Run all linters
make lint

# Backend linting (Python)
make lint-backend
poetry run ruff check --fix openhands/ evaluation/
poetry run mypy openhands/ --config-file dev_config/python/mypy.ini

# Frontend linting (TypeScript/React)
make lint-frontend
cd frontend && npm run lint

# Pre-commit hooks (runs automatically on commit)
poetry run pre-commit run --all-files
```

### Development Utilities
```bash
# Clean caches
make clean

# Format Python code
poetry run ruff format openhands/ evaluation/

# Add Python dependency
poetry add <package-name>

# Add dev dependency
poetry add --group dev <package-name>

# Update dependencies
poetry update

# Frontend dependency management
cd frontend && npm install <package-name>
```

## High-Level Architecture

### Core Components

**OpenHands** is an AI-powered software development agent platform with these major components:

1. **Backend Server** (`/openhands/server/`)
   - FastAPI-based REST API and WebSocket server
   - Handles agent lifecycle, conversation management, and file operations
   - Uses PostgreSQL for persistence and Redis for caching
   - Real-time communication via Socket.IO

2. **Frontend** (`/frontend/`)
   - React + TypeScript SPA with Redux state management
   - Provides IDE-like interface with terminal, file browser, and code editor
   - WebSocket client for real-time agent interactions

3. **Agent System** (`/openhands/agenthub/`)
   - Multiple agent implementations (CodeActAgent, BrowsingAgent, etc.)
   - Each agent has different capabilities and approaches to problem-solving
   - Agents interact with runtime environments to execute actions

4. **Runtime Environment** (`/openhands/runtime/`)
   - Sandboxed execution environments (Docker, E2B, Modal, Local)
   - Provides secure isolation for code execution
   - Supports browser automation, file operations, and command execution

5. **Controller** (`/openhands/controller/`)
   - Orchestrates agent-runtime interactions
   - Manages conversation state and action execution
   - Handles agent delegation and error recovery

6. **Evaluation Framework** (`/evaluation/`)
   - Comprehensive benchmarking system
   - Supports SWE-bench, HumanEvalFix, and other coding benchmarks
   - Used for measuring agent performance

### Key Concepts

- **Actions**: Commands agents can execute (RunIPythonAction, FileWriteAction, BrowseInteractiveAction, etc.)
- **Observations**: Results from action execution returned to agents
- **Events**: All actions and observations are events in the event stream
- **Microagents**: Specialized prompt templates for specific tasks (in `/microagents/`)
- **MCP (Model Context Protocol)**: Tool integration system for extending agent capabilities

### Configuration

- Main config: `config.toml` (created from `config.template.toml`)
- Environment variables: `.env` (created from `.env.example`)
- LLM configurations support via litellm (OpenAI, Anthropic, Google, local models, etc.)

### Important Development Notes

- Python 3.12 required (use Poetry for dependency management)
- Node.js 22+ required for frontend
- Docker required for runtime sandboxing
- Development mode: Set `RUN_MODE=DEV` to bypass auth checks
- Pre-commit hooks enforce code quality standards
- WebSocket connection handles real-time agent-user communication
- File operations are restricted to configured workspace directory

### Testing Strategy

- Unit tests: Test individual components in isolation
- Integration tests: Test agent capabilities end-to-end
- Evaluation benchmarks: Measure performance on standard coding tasks
- All new features should include appropriate test coverage