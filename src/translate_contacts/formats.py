"""Reading and writing contact files while leaving everything except the names untouched."""

from __future__ import annotations

import codecs
import csv
import io
import os
import quopri
import re
from dataclasses import dataclass, field
from pathlib import Path

FIELDS = ("first", "middle", "last")


class FormatError(Exception):
    pass


class ContactFile:
    """A contact file whose contacts are addressed by 0-based index."""

    def __len__(self) -> int:
        raise NotImplementedError

    def get(self, index: int) -> dict[str, str]:
        raise NotImplementedError

    def set(self, index: int, names: dict[str, str]) -> None:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        raise NotImplementedError

    def save(self, path: Path) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(self.to_bytes())
        os.replace(tmp, path)


def load(path: Path) -> ContactFile:
    if path.suffix.lower() in (".vcf", ".vcard"):
        return VcfFile.parse(path.read_bytes())
    return CsvFile.parse(path.read_bytes())


def _decode(data: bytes) -> tuple[str, bool]:
    bom = data.startswith(codecs.BOM_UTF8)
    try:
        return data.decode("utf-8-sig"), bom
    except UnicodeDecodeError as e:
        raise FormatError("file is not UTF-8 encoded") from e


def _encode(text: str, bom: bool) -> bytes:
    return (codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8")


# ---------------------------------------------------------------- CSV

CSV_COLUMNS = {
    "first": ("First Name", "Given Name"),
    "middle": ("Middle Name", "Additional Name"),
    "last": ("Last Name", "Family Name"),
}


@dataclass
class CsvFile(ContactFile):
    header: list[str]
    rows: list[list[str]]
    columns: dict[str, int]
    bom: bool = False
    newline: str = "\n"
    trailing_newline: bool = True

    @classmethod
    def parse(cls, data: bytes) -> CsvFile:
        text, bom = _decode(data)
        rows = list(csv.reader(io.StringIO(text, newline="")))
        if not rows:
            raise FormatError("CSV file is empty")
        header = rows[0]
        columns = {}
        for key, aliases in CSV_COLUMNS.items():
            for alias in aliases:
                if alias in header:
                    columns[key] = header.index(alias)
                    break
        if "first" not in columns and "last" not in columns:
            raise FormatError(
                "no name columns found; expected a Google Contacts CSV with 'First Name' / 'Last Name' columns"
            )
        return cls(
            header=header,
            rows=rows[1:],
            columns=columns,
            bom=bom,
            newline="\r\n" if "\r\n" in text else "\n",
            trailing_newline=text.endswith(("\n", "\r")),
        )

    def __len__(self) -> int:
        return len(self.rows)

    def get(self, index: int) -> dict[str, str]:
        row = self.rows[index]
        names = dict.fromkeys(FIELDS, "")
        for key, col in self.columns.items():
            if col < len(row):
                names[key] = row[col]
        return names

    def set(self, index: int, names: dict[str, str]) -> None:
        row = self.rows[index]
        for key, col in self.columns.items():
            if col >= len(row):
                row.extend([""] * (col + 1 - len(row)))
            row[col] = names[key]

    def to_bytes(self) -> bytes:
        buf = io.StringIO(newline="")
        csv.writer(buf, lineterminator=self.newline).writerows([self.header, *self.rows])
        text = buf.getvalue()
        if not self.trailing_newline:
            text = text.removesuffix(self.newline)
        return _encode(text, self.bom)


# ---------------------------------------------------------------- vCard

_PHYSICAL_LINE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+$")


@dataclass
class _Line:
    raw: str
    content: str
    ending: str


@dataclass
class _Property:
    group_and_name: str
    name: str
    params: list[str]
    value: str

    @classmethod
    def parse(cls, content: str) -> _Property:
        head, _, value = content.partition(":")
        parts = head.split(";")
        return cls(parts[0], parts[0].split(".")[-1].upper(), parts[1:], value)

    @property
    def quoted_printable(self) -> bool:
        return any("QUOTED-PRINTABLE" in p.upper() for p in self.params)

    def decoded_value(self) -> str:
        if not self.quoted_printable:
            return self.value
        charset = next((p.split("=", 1)[1] for p in self.params if p.upper().startswith("CHARSET=")), "utf-8")
        return quopri.decodestring(self.value.encode("utf-8")).decode(charset, "replace")

    def with_value(self, value: str) -> str:
        params = [p for p in self.params if "QUOTED-PRINTABLE" not in p.upper()]
        return ";".join([self.group_and_name, *params]) + ":" + value


@dataclass
class _Card:
    version: str = "3.0"
    n_line: int | None = None
    fn_line: int | None = None
    n: list[str] = field(default_factory=lambda: [""] * 5)
    fn: str = ""

    @property
    def fn_only(self) -> bool:
        return self.n_line is None or not any(self.n[:3])


def _split_lines(text: str) -> list[_Line]:
    physical = _PHYSICAL_LINE.findall(text)
    lines, i = [], 0
    while i < len(physical):
        raw = physical[i]
        content = raw.rstrip("\r\n")
        i += 1
        qp = "QUOTED-PRINTABLE" in content.partition(":")[0].upper()
        while i < len(physical):
            nxt = physical[i]
            nxt_content = nxt.rstrip("\r\n")
            if qp and content.endswith("="):
                content = content[:-1] + nxt_content
            elif nxt_content[:1] in (" ", "\t"):
                content += nxt_content[1:]
            else:
                break
            raw += nxt
            i += 1
        lines.append(_Line(raw, content, raw[len(raw.rstrip("\r\n")) :]))
    return lines


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def _escape(value: str, version: str) -> str:
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace("\n", "\\n")
    return value if version == "2.1" else value.replace(",", "\\,")


def _split_components(value: str) -> list[str]:
    parts, current, i = [], "", 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            current += value[i : i + 2]
            i += 2
            continue
        if value[i] == ";":
            parts.append(current)
            current = ""
        else:
            current += value[i]
        i += 1
    parts.append(current)
    return [_unescape(p) for p in parts]


@dataclass
class VcfFile(ContactFile):
    lines: list[_Line]
    cards: list[_Card]
    bom: bool = False
    replacements: dict[int, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, data: bytes) -> VcfFile:
        text, bom = _decode(data)
        lines = _split_lines(text)
        cards: list[_Card] = []
        card = None
        for index, line in enumerate(lines):
            prop = _Property.parse(line.content)
            if prop.name == "BEGIN" and prop.value.strip().upper() == "VCARD":
                card = _Card()
            elif card is None:
                continue
            elif prop.name == "END" and prop.value.strip().upper() == "VCARD":
                cards.append(card)
                card = None
            elif prop.name == "VERSION":
                card.version = prop.value.strip()
            elif prop.name == "N":
                card.n_line = index
                card.n = (_split_components(prop.decoded_value()) + [""] * 5)[:5]
            elif prop.name == "FN":
                card.fn_line = index
                card.fn = _unescape(prop.decoded_value())
        if not cards:
            raise FormatError("no BEGIN:VCARD ... END:VCARD entries found")
        return cls(lines, cards, bom)

    def __len__(self) -> int:
        return len(self.cards)

    def get(self, index: int) -> dict[str, str]:
        card = self.cards[index]
        if card.fn_only:
            return {"first": card.fn, "middle": "", "last": ""}
        return {"first": card.n[1], "middle": card.n[2], "last": card.n[0]}

    def set(self, index: int, names: dict[str, str]) -> None:
        card = self.cards[index]
        if card.fn_only:
            card.fn = names["first"]
        else:
            card.n[:3] = [names["last"], names["first"], names["middle"]]
            prefix, suffix = card.n[3], card.n[4]
            card.fn = " ".join(v for v in (prefix, names["first"], names["middle"], names["last"], suffix) if v)
            n_value = ";".join(_escape(v, card.version) for v in card.n)
            self._replace(card.n_line, n_value)
        if card.fn_line is not None:
            self._replace(card.fn_line, _escape(card.fn, card.version))

    def _replace(self, line_index: int, value: str) -> None:
        prop = _Property.parse(self.lines[line_index].content)
        self.replacements[line_index] = prop.with_value(value)

    def to_bytes(self) -> bytes:
        parts = [
            self.replacements[i] + line.ending if i in self.replacements else line.raw
            for i, line in enumerate(self.lines)
        ]
        return _encode("".join(parts), self.bom)
