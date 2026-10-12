from enum import Enum, auto


class OpCode(Enum):
    CREATE_TABLE = auto()
    CREATE_INDEX = auto()
    OPEN_READ = auto()
    OPEN_WRITE = auto()
    OPEN_INDEX = auto()
    REWIND = auto()
    SEEK_PK = auto()
    SEEK_INDEX_EQ = auto()
    INDEX_TO_TABLE = auto()
    FILTER_EQ = auto()
    PROJECT = auto()
    RESULT_ROW = auto()
    NEXT = auto()
    INDEX_NEXT = auto()
    INSERT_ROW = auto()
    DELETE_CURRENT = auto()
    HALT = auto()
