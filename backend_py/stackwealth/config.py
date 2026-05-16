"""Centralized env config."""
import os


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v else default


PORT = int(env("PORT", "4000"))
FRONTEND_ORIGIN = env("FRONTEND_ORIGIN", "http://localhost:3000")
PLANNER_MODEL = env("PLANNER_MODEL", "claude-sonnet-4-6")
# Intake is a structured-JSON extraction task — Haiku is 3-5x faster and the
# job doesn't need Sonnet's reasoning. Keeps PDF / XLSX uploads under Fly's
# proxy idle-timeout window.
INTAKE_MODEL = env("INTAKE_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
OPENAI_API_KEY = env("OPENAI_API_KEY")

LANGFUSE_PUBLIC_KEY = env("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = env("LANGFUSE_SECRET_KEY")
LANGFUSE_BASE_URL = env("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")

DATABASE_URL = env("DATABASE_URL")
