from __future__ import annotations

from mini_sqlite.catalog.schema import Column, ColumnType
from mini_sqlite.errors import ParseError
from mini_sqlite.sql.ast import (
    AggregateExpr,
    AnalyzeStmt,
    AggregateFunction,
    Assignment,
    BeginStmt,
    CommitStmt,
    ComparisonPredicate,
    CompareOp,
    CreateIndexStmt,
    CreateTableStmt,
    DeleteStmt,
    InsertStmt,
    JoinClause,
    OrderBy,
    RollbackStmt,
    SelectStmt,
    Statement,
    TableRef,
    UpdateStmt,
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
            stmt = self._create()
        elif token_type == TokenType.INSERT:
            stmt = self._insert()
        elif token_type == TokenType.SELECT:
            stmt = self._select()
        elif token_type == TokenType.DELETE:
            stmt = self._delete()
        elif token_type == TokenType.UPDATE:
            stmt = self._update()
        elif token_type == TokenType.ANALYZE:
            stmt = self._analyze()
        elif token_type == TokenType.BEGIN:
            stmt = self._begin()
        elif token_type in (TokenType.COMMIT, TokenType.END):
            self._advance()
            self._match(TokenType.TRANSACTION)
            stmt = CommitStmt()
        elif token_type == TokenType.ROLLBACK:
            self._advance()
            self._match(TokenType.TRANSACTION)
            stmt = RollbackStmt()
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

    def _column_ref(self) -> str:
        first = self._ident()
        if self._match(TokenType.DOT):
            return f"{first}.{self._ident()}"
        return first

    def _literal(self):
        if self.current.type in (TokenType.NUMBER, TokenType.STRING):
            return self._advance().value
        if self.current.type == TokenType.NULL:
            self._advance()
            return None
        raise self._error("expected literal")

    def _analyze(self) -> AnalyzeStmt:
        self._expect(TokenType.ANALYZE)
        table = None
        if self.current.type == TokenType.IDENT:
            table = self._ident()
        return AnalyzeStmt(table)

    def _begin(self) -> BeginStmt:
        self._expect(TokenType.BEGIN)
        self._match(TokenType.TRANSACTION)
        return BeginStmt()

    def _create(self) -> Statement:
        self._expect(TokenType.CREATE)
        if self.current.type == TokenType.TABLE:
            return self._create_table_after_create()
        if self.current.type == TokenType.INDEX:
            return self._create_index_after_create()
        raise self._error("expected TABLE or INDEX after CREATE")

    def _create_index_after_create(self) -> CreateIndexStmt:
        self._expect(TokenType.INDEX)
        name = self._ident()
        self._expect(TokenType.ON)
        table = self._ident()
        self._expect(TokenType.LPAREN)
        column = self._ident()
        self._expect(TokenType.RPAREN)
        return CreateIndexStmt(name, table, column)

    def _create_table_after_create(self) -> CreateTableStmt:
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

    def _select_item(self) -> str | AggregateExpr:
        aggregate_tokens = {
            TokenType.COUNT: AggregateFunction.COUNT,
            TokenType.SUM: AggregateFunction.SUM,
            TokenType.MIN: AggregateFunction.MIN,
            TokenType.MAX: AggregateFunction.MAX,
        }
        function = aggregate_tokens.get(self.current.type)
        if function is not None:
            self._advance()
            self._expect(TokenType.LPAREN)
            if self._match(TokenType.STAR):
                if function != AggregateFunction.COUNT:
                    raise self._error(f"{function.value}(*) is not supported")
                column = None
            else:
                column = self._column_ref()
            self._expect(TokenType.RPAREN)
            return AggregateExpr(function, column)
        return self._column_ref()

    def _table_ref(self) -> TableRef:
        name = self._ident()
        alias = None
        if self._match(TokenType.AS):
            alias = self._ident()
        elif self.current.type == TokenType.IDENT:
            # SQL permits FROM users u as shorthand for FROM users AS u.
            alias = self._ident()
        return TableRef(name, alias)

    def _select(self) -> SelectStmt:
        self._expect(TokenType.SELECT)
        if self._match(TokenType.STAR):
            items: list[str | AggregateExpr] = ["*"]
        else:
            items = [self._select_item()]
            while self._match(TokenType.COMMA):
                items.append(self._select_item())
        self._expect(TokenType.FROM)
        left = self._table_ref()

        join = None
        if self._match(TokenType.INNER):
            self._expect(TokenType.JOIN)
            join = self._join_clause()
        elif self._match(TokenType.JOIN):
            join = self._join_clause(after_join_keyword=True)

        where = self._optional_where()
        order_by = self._optional_order_by()
        limit = self._optional_limit()
        return SelectStmt(
            left.name,
            items,
            where,
            order_by,
            limit,
            table_alias=left.alias,
            join=join,
        )

    def _join_clause(self, after_join_keyword: bool = False) -> JoinClause:
        # `after_join_keyword` exists only to make the two parse branches above
        # self-documenting; both arrive here with JOIN already consumed.
        _ = after_join_keyword
        right = self._table_ref()
        self._expect(TokenType.ON)
        left_column = self._column_ref()
        self._expect(TokenType.EQ)
        right_column = self._column_ref()
        return JoinClause(right, left_column, right_column)

    def _delete(self) -> DeleteStmt:
        self._expect(TokenType.DELETE)
        self._expect(TokenType.FROM)
        table = self._ident()
        where = self._optional_where()
        return DeleteStmt(table, where)

    def _update(self) -> UpdateStmt:
        self._expect(TokenType.UPDATE)
        table = self._ident()
        self._expect(TokenType.SET)
        assignments = [self._assignment()]
        while self._match(TokenType.COMMA):
            assignments.append(self._assignment())
        where = self._optional_where()
        return UpdateStmt(table, tuple(assignments), where)

    def _assignment(self) -> Assignment:
        column = self._ident()
        self._expect(TokenType.EQ)
        return Assignment(column, self._literal())

    def _optional_where(self) -> ComparisonPredicate | None:
        if not self._match(TokenType.WHERE):
            return None
        column = self._column_ref()
        operators = {
            TokenType.EQ: CompareOp.EQ,
            TokenType.NE: CompareOp.NE,
            TokenType.LT: CompareOp.LT,
            TokenType.LE: CompareOp.LE,
            TokenType.GT: CompareOp.GT,
            TokenType.GE: CompareOp.GE,
        }
        op = operators.get(self.current.type)
        if op is None:
            raise self._error("expected comparison operator")
        self._advance()
        return ComparisonPredicate(column, op, self._literal())

    def _optional_order_by(self) -> OrderBy | None:
        if not self._match(TokenType.ORDER):
            return None
        self._expect(TokenType.BY)
        column = self._column_ref()
        descending = False
        if self._match(TokenType.ASC):
            descending = False
        elif self._match(TokenType.DESC):
            descending = True
        return OrderBy(column, descending)

    def _optional_limit(self) -> int | None:
        if not self._match(TokenType.LIMIT):
            return None
        token = self._expect(TokenType.NUMBER)
        limit = int(token.value)
        if limit < 0:
            raise self._error("LIMIT must be non-negative")
        return limit
