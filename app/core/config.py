from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_NAME: str = "Team Efficiency Measure"
    APP_ENV: str = "development"
    DEBUG: bool = True

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "team_efficiency"

    # Phase 6: Manager AI Assistant (Anthropic API). ANTHROPIC_API_KEY is intentionally optional
    # here — the app must still start and every other feature must still work without it; the
    # assistant endpoint itself reports a clear error if it's missing when actually used.
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-5"

    # Phase 10: Autonomous Daily Manager. Disabled by default so the app (and the test suite,
    # which shares this same Settings object) never starts a background scheduler thread
    # unexpectedly — enable explicitly for a real deployment. A manual trigger
    # (`POST /api/daily-manager/run`) always works regardless of this flag.
    DAILY_MANAGER_SCHEDULER_ENABLED: bool = False
    DAILY_MANAGER_RUN_HOUR: int = 8

    # Production-readiness pass: authentication (app.core.security). Left blank on purpose —
    # a hardcoded default secret checked into source control would itself be a vulnerability
    # (anyone who reads this file could forge tokens for any deployment that didn't override
    # it). If left blank, app.core.security generates a random secret ONCE per process at
    # import time and logs a loud warning; every previously-issued token becomes invalid on
    # restart in that mode, which is fine for local dev/tests but never acceptable for a real
    # deployment — always set a real JWT_SECRET_KEY in `.env` outside this sandbox.
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Optional one-time bootstrap admin, created at startup only if BOTH are set AND no admin
    # user exists yet (see app.database.init_db.bootstrap_admin). Leave unset in any shared
    # environment once a real admin account exists — this is a first-run convenience, not a
    # permanent credential; the bootstrap check runs on every startup but is a no-op once an
    # admin already exists.
    ADMIN_BOOTSTRAP_EMAIL: str = ""
    ADMIN_BOOTSTRAP_PASSWORD: str = ""

    # Demo mode: OFF by default. When true, POST /api/auth/demo-login issues a real, fully
    # valid JWT for a demo account with NO credentials required — every other auth/authz check
    # (RBAC, rate limiting, token expiry/revocation) stays completely unmodified and fully
    # active; this only removes the password step, and only via that one endpoint (which 404s,
    # as if it didn't exist, whenever this is false). NEVER enable this in a real deployment —
    # it lets anyone obtain a full admin session with no credentials at all. Intended only for
    # scripts/run_demo.py's disposable, SQLite-backed demo instance. See README "Demo Mode".
    DEMO_MODE: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
