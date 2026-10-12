from __future__ import annotations

from mini_sqlite.catalog.schema import Column, ColumnType
from mini_sqlite.errors import ParseError
from mini_sqlite.sql.ast import (
    CreateTableStmt,
    DeleteStmt,
    EqualityPredicate,
    InsertStmt,
    SelectStmt,
    Statement,
)
from mini_sqlite.sql.tokenizer import Tokenizer
from mini_sqlite.sql.tokens import Token, TokenType


class Parser:
    def __init__(self, sql: str):
        self.tokens = Tokenizer(sql).tokenize()
        self.i = 0

    def parse(self) -> Statement:
        token_type = self.current.type
        if token_type == TokenType.CREATE:
            stmt = self._create_table()
        elif token_type == TokenType.INSERT:
            stmt = self._insert()
        elif token_type == TokenType.SELECT:
            stmt = self._select()
        elif token_type == TokenType.DELETE:
            stmt = self._delete()
        else:
            raise self._error(f"unsupported statement starting with {self.current.value!r}")
        self._match(TokenType.SEMICOLON)
        self._expect(TokenType.EOF)
        return stmt

    @property
    def current(self) -> Token:
        return self.tokens[self.i]

    def _advance(self) -> Token:
        token = self.current
        self.i += 1
        return token

    def _expect(self, token_type: TokenType) -> Token:
        if self.current.type != token_type:
            raise self._error(f"expected {token_type.name}, got {self.current.type.name}")
        return self._advance()

    def _match(self, token_type: TokenType) -> bool:
        if self.current.type == token_type:
            self._advance()
            return True
        return False

    def _error(self, message: str) -> ParseError:
        return ParseError(f"{message} at position {self.current.position}")

    def _ident(self) -> str:
        return str(self._expect(TokenType.IDENT).value)

    def _literal(self):
        if self.current.type in (TokenType.NUMBER, TokenType.STRING):
            return self._advance().value
        if self.current.type == TokenType.NULL:
            self._advance()
            return None
        raise self._error("expected literal")

    def _create_table(self) -> CreateTableStmt:
        self._expect(TokenType.CREATE)
        self._expect(TokenType.TABLE)
        name = self._ident()
        self._expect(TokenType.LPAREN)
        columns: list[Column] = []
        while True:
            col_name = self._ident()
            if self._match(TokenType.INTEGER):
                col_type = ColumnType.INTEGER
            elif self._match(TokenType.TEXT):
                col_type = ColumnType.TEXT
            else:
                raise self._error("expected INTEGER or TEXT")
            primary_key = False
            if self._match(TokenType.PRIMARY):
                self._expect(TokenType.KEY)
                primary_key = True
            columns.append(Column(col_name, col_type, primary_key))
            if not self._match(TokenType.COMMA):
                break
        self._expect(TokenType.RPAREN)
        return CreateTableStmt(name, columns)

    def _insert(self) -> InsertStmt:
        self._expect(TokenType.INSERT)
        self._expect(TokenType.INTO)
        table = self._ident()
        self._expect(TokenType.VALUES)
        self._expect(TokenType.LPAREN)
        values = [self._literal()]
        while self._match(TokenType.COMMA):
            values.append(self._literal())
        self._expect(TokenType.RPAREN)
        return InsertStmt(table, tuple(values))

    def _select(self) -> SelectStmt:
        self._expect(TokenType.SELECT)
        if self._match(TokenType.STAR):
            columns = ["*"]
        else:
            columns = [self._ident()]
            while self._match(TokenType.COMMA):
                columns.append(self._ident())
        self._expect(TokenType.FROM)
        table = self._ident()
        where = self._optional_where()
        return SelectStmt(table, columns, where)

    def _delete(self) -> DeleteStmt:
        self._expect(TokenType.DELETE)
        self._expect(TokenType.FROM)
        table = self._ident()
        where = self._optional_where()
        return DeleteStmt(table, where)

    def _optional_where(self) -> EqualityPredicate | None:
        if not self._match(TokenType.WHERE):
            return None
        column = self._ident()
        self._expect(TokenType.EQ)
        return EqualityPredicate(column, self._literal())
