from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    CREATE = auto()
    TABLE = auto()
    INDEX = auto()
    ON = auto()
    INSERT = auto()
    INTO = auto()
    VALUES = auto()
    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    DELETE = auto()
    UPDATE = auto()
    SET = auto()
    ORDER = auto()
    BY = auto()
    ASC = auto()
    DESC = auto()
    LIMIT = auto()
    COUNT = auto()
    SUM = auto()
    MIN = auto()
    MAX = auto()
    JOIN = auto()
    INNER = auto()
    AS = auto()
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
    NE = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    DOT = auto()
    COMMA = auto()
    LPAREN = auto()
    RPAREN = auto()
    SEMICOLON = auto()
    EOF = auto()


KEYWORDS = {
    "CREATE": TokenType.CREATE,
    "TABLE": TokenType.TABLE,
    "INDEX": TokenType.INDEX,
    "ON": TokenType.ON,
    "INSERT": TokenType.INSERT,
    "INTO": TokenType.INTO,
    "VALUES": TokenType.VALUES,
    "SELECT": TokenType.SELECT,
    "FROM": TokenType.FROM,
    "WHERE": TokenType.WHERE,
    "DELETE": TokenType.DELETE,
    "UPDATE": TokenType.UPDATE,
    "SET": TokenType.SET,
    "ORDER": TokenType.ORDER,
    "BY": TokenType.BY,
    "ASC": TokenType.ASC,
    "DESC": TokenType.DESC,
    "LIMIT": TokenType.LIMIT,
    "COUNT": TokenType.COUNT,
    "SUM": TokenType.SUM,
    "MIN": TokenType.MIN,
    "MAX": TokenType.MAX,
    "JOIN": TokenType.JOIN,
    "INNER": TokenType.INNER,
    "AS": TokenType.AS,
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
