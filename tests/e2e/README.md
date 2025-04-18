# How to start e2e tests

## Run the auth server

```bash
poetry run python tests/e2e/auth_server.py
```

## Setup env

```bash
# JWT Secret
RUN_MODE=DEV
THESIS_AUTH_SERVER_URL=http://localhost:5000
JWT_SECRET=your-secret-key
```

## Start the backend server
 
```bash
LOG_LEVEL=debug make start-backend
```

## Start the tests

```bash
poetry run pytest tests/e2e/test_e2e.py
```