import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        # Local-development fallback only. Set SECRET_KEY in OpenShift.
        SECRET_KEY = "local-dev-only-change-me"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 15 * 1024 * 1024
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/tmp/jnpa-uploads")

    database_url = os.environ.get("DATABASE_URL", "sqlite:///expense_manager.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if database_url.startswith("postgresql://") and "sslmode" not in database_url:
        # PostgreSQL services may require SSL; configure DATABASE_URL as needed.
        pass
    SQLALCHEMY_DATABASE_URI = database_url
