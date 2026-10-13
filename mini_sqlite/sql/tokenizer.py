from __future__ import annotations

from mini_sqlite.errors import ParseError
from mini_sqlite.sql.tokens import KEYWORDS, Token, TokenType


class Tokenizer:
    def __init__(self, sql: str):
        self.sql = sql
        self.i = 0

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.i < len(self.sql):
            ch = self.sql[self.i]
            if ch.isspace():
                self.i += 1
                continue
            if ch == "-" and self._peek(1) == "-":
                self._skip_line_comment()
                continue
            if ch.isalpha() or ch == "_":
                tokens.append(self._identifier())
                continue
            if ch.isdigit() or (ch == "-" and self._peek(1).isdigit()):
                tokens.append(self._number())
                continue
            if ch in ("'", '"'):
                tokens.append(self._string(ch))
                continue

            # Comparison operators are checked before one-character tokens.
            two = ch + self._peek(1)
            multi = {
                "!=": TokenType.NE,
                "<>": TokenType.NE,
                "<=": TokenType.LE,
                ">=": TokenType.GE,
            }.get(two)
            if multi is not None:
                tokens.append(Token(multi, two, self.i))
                self.i += 2
                continue

            single = {
                "*": TokenType.STAR,
                "=": TokenType.EQ,
                "<": TokenType.LT,
                ">": TokenType.GT,
                ".": TokenType.DOT,
                ",": TokenType.COMMA,
                "(": TokenType.LPAREN,
                ")": TokenType.RPAREN,
                ";": TokenType.SEMICOLON,
            }.get(ch)
            if single is not None:
                tokens.append(Token(single, ch, self.i))
                self.i += 1
                continue
            raise ParseError(f"unexpected character {ch!r} at position {self.i}")
        tokens.append(Token(TokenType.EOF, None, len(self.sql)))
        return tokens

    def _peek(self, n: int) -> str:
        j = self.i + n
        return self.sql[j] if j < len(self.sql) else ""

    def _skip_line_comment(self) -> None:
        while self.i < len(self.sql) and self.sql[self.i] != "\n":
            self.i += 1

    def _identifier(self) -> Token:
        start = self.i
        self.i += 1
        while self.i < len(self.sql) and (
            self.sql[self.i].isalnum() or self.sql[self.i] == "_"
        ):
            self.i += 1
        text = self.sql[start:self.i]
        token_type = KEYWORDS.get(text.upper(), TokenType.IDENT)
        return Token(token_type, text if token_type == TokenType.IDENT else text.upper(), start)

    def _number(self) -> Token:
        start = self.i
        if self.sql[self.i] == "-":
            self.i += 1
        while self.i < len(self.sql) and self.sql[self.i].isdigit():
            self.i += 1
        return Token(TokenType.NUMBER, int(self.sql[start:self.i]), start)

    def _string(self, quote: str) -> Token:
        start = self.i
        self.i += 1
        chars: list[str] = []
        while self.i < len(self.sql):
            ch = self.sql[self.i]
            if ch == quote:
                if self._peek(1) == quote:  # SQL-style doubled quote escape
                    chars.append(quote)
                    self.i += 2
                    continue
                self.i += 1
                return Token(TokenType.STRING, "".join(chars), start)
            chars.append(ch)
            self.i += 1
        raise ParseError(f"unterminated string starting at {start}")
