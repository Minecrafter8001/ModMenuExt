from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any


class ParseError(ValueError):
    pass


class IncompleteParse(ParseError):
    pass


@dataclass(frozen=True)
class TaggedValue:
    name: str
    args: tuple[Any, ...]


class VariantParser:
    def __init__(self, text: str):
        self.text = text
        self.length = len(text)
        self.position = 0

    def parse(self) -> Any:
        value = self._parse_value()
        self._skip_whitespace()
        if self.position != self.length:
            raise ParseError(f"unexpected trailing input at {self.position}")
        return value

    def _parse_value(self) -> Any:
        self._skip_whitespace()
        if self.position >= self.length:
            raise IncompleteParse("unexpected end of value")

        current = self.text[self.position]
        if current == '"':
            return self._parse_string()
        if current == "[":
            return self._parse_array()
        if current == "{":
            return self._parse_dict()
        if current in "-0123456789":
            return self._parse_number()
        if current.isalpha() or current == "_":
            return self._parse_identifier_or_call()
        raise ParseError(f"unsupported token {current!r} at {self.position}")

    def _parse_string(self) -> str:
        self.position += 1
        output: list[str] = []
        while self.position < self.length:
            current = self.text[self.position]
            if current == '"':
                self.position += 1
                return "".join(output)
            if current == "\\":
                self.position += 1
                if self.position >= self.length:
                    raise IncompleteParse("unfinished string escape")
                escaped = self.text[self.position]
                output.append({
                    '"': '"',
                    "\\": "\\",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }.get(escaped, escaped))
                self.position += 1
                continue
            output.append(current)
            self.position += 1
        raise IncompleteParse("unterminated string")

    def _parse_array(self) -> list[Any]:
        self.position += 1
        values: list[Any] = []
        while True:
            self._skip_whitespace()
            if self.position >= self.length:
                raise IncompleteParse("unterminated array")
            if self.text[self.position] == "]":
                self.position += 1
                return values
            values.append(self._parse_value())
            self._skip_whitespace()
            if self.position >= self.length:
                raise IncompleteParse("unterminated array")
            if self.text[self.position] == ",":
                self.position += 1
                continue
            if self.text[self.position] == "]":
                self.position += 1
                return values
            raise ParseError(f"expected ',' or ']' at {self.position}")

    def _parse_dict(self) -> dict[Any, Any]:
        self.position += 1
        values: dict[Any, Any] = {}
        while True:
            self._skip_whitespace()
            if self.position >= self.length:
                raise IncompleteParse("unterminated dictionary")
            if self.text[self.position] == "}":
                self.position += 1
                return values
            key = self._parse_value()
            self._skip_whitespace()
            if self.position >= self.length:
                raise IncompleteParse("unterminated dictionary")
            if self.text[self.position] != ":":
                raise ParseError(f"expected ':' at {self.position}")
            self.position += 1
            values[key] = self._parse_value()
            self._skip_whitespace()
            if self.position >= self.length:
                raise IncompleteParse("unterminated dictionary")
            if self.text[self.position] == ",":
                self.position += 1
                continue
            if self.text[self.position] == "}":
                self.position += 1
                return values
            raise ParseError(f"expected ',' or '}}' at {self.position}")

    def _parse_number(self) -> int | float:
        start = self.position
        while self.position < self.length and self.text[self.position] in "+-0123456789.eE":
            self.position += 1
        token = self.text[start:self.position]
        try:
            if any(marker in token for marker in ".eE"):
                return float(token)
            return int(token)
        except ValueError as exc:
            raise ParseError(f"invalid number {token!r}") from exc

    def _parse_identifier_or_call(self) -> Any:
        start = self.position
        while self.position < self.length and (self.text[self.position].isalnum() or self.text[self.position] in "_."):
            self.position += 1
        identifier = self.text[start:self.position]
        self._skip_whitespace()
        if identifier == "true":
            return True
        if identifier == "false":
            return False
        if identifier == "null":
            return None
        if self.position < self.length and self.text[self.position] == "(":
            return self._parse_call(identifier)
        return identifier

    def _parse_call(self, name: str) -> Any:
        self.position += 1
        args: list[Any] = []
        while True:
            self._skip_whitespace()
            if self.position >= self.length:
                raise IncompleteParse("unterminated function call")
            if self.text[self.position] == ")":
                self.position += 1
                break
            args.append(self._parse_value())
            self._skip_whitespace()
            if self.position >= self.length:
                raise IncompleteParse("unterminated function call")
            if self.text[self.position] == ",":
                self.position += 1
                continue
            if self.text[self.position] == ")":
                self.position += 1
                break
            raise ParseError(f"expected ',' or ')' at {self.position}")
        if name == "PoolStringArray":
            return list(args)
        return TaggedValue(name=name, args=tuple(args))

    def _skip_whitespace(self) -> None:
        while self.position < self.length and self.text[self.position].isspace():
            self.position += 1


def parse_variant(text: str) -> Any:
    return VariantParser(text).parse()


def serialize_variant(value: Any) -> str:
    if isinstance(value, TaggedValue):
        joined = ", ".join(serialize_variant(item) for item in value.args)
        return f"{value.name}( {joined} )"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("non-finite floats are not supported")
        if value.is_integer():
            return f"{value:.1f}"
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        joined = ", ".join(serialize_variant(item) for item in value)
        return f"[ {joined} ]"
    if isinstance(value, tuple):
        joined = ", ".join(serialize_variant(item) for item in value)
        return f"[ {joined} ]"
    if isinstance(value, dict):
        joined = ", ".join(
            f"{serialize_variant(str(key))}: {serialize_variant(item)}" for key, item in value.items()
        )
        return f"{{ {joined} }}"
    raise TypeError(f"unsupported variant type: {type(value)!r}")


def is_color_value(value: Any) -> bool:
    return isinstance(value, TaggedValue) and value.name == "Color" and len(value.args) in {3, 4}
