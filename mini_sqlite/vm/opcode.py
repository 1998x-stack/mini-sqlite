from enum import Enum, auto


class OpCode(Enum):
    CREATE_TABLE = auto()
    OPEN_READ = auto()
    OPEN_WRITE = auto()
    REWIND = auto()
    SEEK_PK = auto()
    FILTER_EQ = auto()
    PROJECT = auto()
    RESULT_ROW = auto()
    NEXT = auto()
    INSERT_ROW = auto()
    DELETE_CURRENT = auto()
    HALT = auto()
