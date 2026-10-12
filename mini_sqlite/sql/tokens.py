from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    CREATE = auto()
    TABLE = auto()
    INSERT = auto()
    INTO = auto()
    VALUES = auto()
    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    DELETE = auto()
    PRIMARY = auto()
    KEY = auto()
    INTEGER = auto()
    TEXT = auto()
    NULL = auto()
    BEGIN = auto()
    TRANSACTION = auto()
    COMMIT = auto()
    END = auto()
    ROLLBACK = auto()
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    STAR = auto()
    EQ = auto()
    COMMA = auto()
    LPAREN = auto()
    RPAREN = auto()
    SEMICOLON = auto()
    EOF = auto()


KEYWORDS = {
    "CREATE": TokenType.CREATE,
    "TABLE": TokenType.TABLE,
    "INSERT": TokenType.INSERT,
    "INTO": TokenType.INTO,
    "VALUES": TokenType.VALUES,
    "SELECT": TokenType.SELECT,
    "FROM": TokenType.FROM,
    "WHERE": TokenType.WHERE,
    "DELETE": TokenType.DELETE,
    "PRIMARY": TokenType.PRIMARY,
    "KEY": TokenType.KEY,
    "INTEGER": TokenType.INTEGER,
    "TEXT": TokenType.TEXT,
    "NULL": TokenType.NULL,
    "BEGIN": TokenType.BEGIN,
    "TRANSACTION": TokenType.TRANSACTION,
    "COMMIT": TokenType.COMMIT,
    "END": TokenType.END,
    "ROLLBACK": TokenType.ROLLBACK,
}


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: object = None
    position: int = 0
