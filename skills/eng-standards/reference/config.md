# Configuration Management

Every project MUST implement a centralized configuration system. Agents tend to scatter `process.env` calls throughout the codebase, use inconsistent defaults, and never validate that required config is present at startup.

## Single config module

All configuration MUST be loaded and validated in one place (e.g., `src/config.ts`, `config/settings.py`). This module:
1. Loads config from three layers in order, each overriding the previous:
   - **App defaults** (hardcoded in the config module)
   - **Config file** (e.g., `config.json`, `config.yaml`, `.env` file)
   - **Environment variables** (override any config file value)
2. Validates all values (required fields present, correct types, valid ranges)
3. Exports a typed/validated config object
4. Is the ONLY place that reads config sources — no direct `process.env` / `os.environ` access elsewhere

## Backing services as attached resources

All backing services (databases, caches, message queues, SMTP servers, external APIs, blob storage) MUST be treated as attached resources, swappable via configuration. Application code MUST make no distinction between local and third-party services — a local PostgreSQL and Amazon RDS are accessed the same way, differing only in config values. No hardcoded connection strings, hostnames, or service URLs anywhere in the codebase. This enables swapping a backing service without code changes — only config changes.

## Fail-fast validation

On startup, validate all configuration before doing anything else. If a required value is missing or invalid, the process MUST exit immediately with a clear error message listing every invalid/missing config key and what's expected. Not halfway through handling the first request.

## Sensitive vs non-sensitive config

- **Secrets** (API keys, database passwords, tokens, private keys) MUST only come from environment variables or secret managers. Never from config files checked into git.
- The config module MUST distinguish between sensitive and non-sensitive values.
- Sensitive values MUST never appear in log output — log that the value is "present" or "missing", not the value itself.

## Config documentation

The config module (or a dedicated section in the project README and any agentic documentation) MUST document every config key:

| Key | Type | Default | Required | Sensitive | Description |
|-----|------|---------|----------|-----------|-------------|
| `PORT` | number | 3000 | no | no | HTTP server port |
| `DATABASE_URL` | string | — | yes | yes | PostgreSQL connection string |

This table MUST be kept in sync with the config module — update both when adding/removing config keys.
