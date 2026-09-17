"""Python 3.10-compatible enums with value-like string formatting."""

from enum import Enum


class StringEnum(str, Enum):
    """Preserve value-like string formatting on every supported Python version."""

    __str__ = str.__str__
