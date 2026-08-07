# Expose Base for Alembic to import. The project declares Base in app.models (evaluation.py),
# so delegate to app.models to ensure a single Base is used for autogeneration.
from app.models import Base

__all__ = ["Base"]
