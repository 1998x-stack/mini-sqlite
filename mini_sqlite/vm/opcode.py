from enum import Enum, auto


class OpCode(Enum):
    CREATE_TABLE = auto()
    CREATE_INDEX = auto()
    ANALYZE = auto()
    OPEN_READ = auto()
    OPEN_WRITE = auto()
    OPEN_INDEX = auto()
    REWIND = auto()
    SEEK_PK = auto()
    SEEK_INDEX_EQ = auto()
    INDEX_TO_TABLE = auto()

    # v0.5 join-source instructions.
    SEEK_PK_FROM_COLUMN = auto()
    SEEK_INDEX_FROM_COLUMN = auto()
    FILTER_JOIN_EQ = auto()
    COLLECT_JOIN_ROW = auto()
    FILTER_ROWS = auto()

    # v0.1-v0.3 row-at-a-time instructions remain readable for historical code.
    FILTER_EQ = auto()
    PROJECT = auto()
    RESULT_ROW = auto()

    # v0.4 relational pipeline instructions.
    FILTER_COMPARE = auto()
    COLLECT_ROW = auto()
    SORT_ROWS = auto()
    PROJECT_ROWS = auto()
    AGGREGATE_ROWS = auto()
    LIMIT_ROWS = auto()
    EMIT_ROWS = auto()

    NEXT = auto()
    INDEX_NEXT = auto()
    INSERT_ROW = auto()
    UPDATE_CURRENT = auto()
    DELETE_CURRENT = auto()
    HALT = auto()
