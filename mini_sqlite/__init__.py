"""mini-sqlite public API."""
from .database import Database
from .errors import MiniSQLiteError

__all__ = ["Database", "MiniSQLiteError"]
__version__ = "0.8.0"
