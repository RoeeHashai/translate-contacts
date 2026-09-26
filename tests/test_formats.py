import codecs

import pytest

from translate_contacts.formats import CsvFile, FormatError, VcfFile

GOOGLE_CSV = (
    "First Name,Middle Name,Last Name,Notes,Phone 1 - Value\n"
    "אבי,,כהן,,+972500000001\n"
    'Dana,,Levi,"line one\nline two",+972500000002\n'
    "שירה,,,,+972500000003"
)


def test_csv_round_trip_is_byte_identical():
    data = GOOGLE_CSV.encode()
    assert CsvFile.parse(data).to_bytes() == data


def test_csv_round_trip_keeps_bom_and_crlf():
    data = codecs.BOM_UTF8 + GOOGLE_CSV.replace("\n", "\r\n").encode() + b"\r\n"
    book = CsvFile.parse(data)
    assert book.get(0)["first"] == "אבי"
    assert book.to_bytes() == data


def test_csv_set_changes_only_name_cells():
    book = CsvFile.parse(GOOGLE_CSV.encode())
    assert len(book) == 3
    assert book.get(0) == {"first": "אבי", "middle": "", "last": "כהן"}
    book.set(0, {"first": "Avi", "middle": "", "last": "Cohen"})
    lines = book.to_bytes().decode().split("\n")
    assert lines[1] == "Avi,,Cohen,,+972500000001"
    assert lines[2:] == GOOGLE_CSV.split("\n")[2:]


def test_csv_alternative_column_names():
    book = CsvFile.parse("Given Name,Family Name,Phone\nיוסי,לוי,1\n".encode())
    assert book.get(0) == {"first": "יוסי", "middle": "", "last": "לוי"}
    book.set(0, {"first": "Yossi", "middle": "", "last": "Levi"})
    assert book.to_bytes().decode() == "Given Name,Family Name,Phone\nYossi,Levi,1\n"


def test_csv_without_name_columns_is_rejected():
    with pytest.raises(FormatError):
        CsvFile.parse(b"Phone,Email\n1,a@b.c\n")


VCARD_30 = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "N:כהן;אבי;;ד\"ר;\r\n"
    "FN:ד\"ר אבי כהן\r\n"
    "TEL;TYPE=CELL:+972500000001\r\n"
    "NOTE:a long note that is folded\r\n"
    "  onto a second line\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "N:;;;;\r\n"
    "FN:חברת אשראי\r\n"
    "END:VCARD\r\n"
)


def test_vcard_round_trip_is_byte_identical():
    data = VCARD_30.encode()
    assert VcfFile.parse(data).to_bytes() == data


def test_vcard_reads_n_and_falls_back_to_fn():
    book = VcfFile.parse(VCARD_30.encode())
    assert len(book) == 2
    assert book.get(0) == {"first": "אבי", "middle": "", "last": "כהן"}
    assert book.get(1) == {"first": "חברת אשראי", "middle": "", "last": ""}


def test_vcard_set_rewrites_only_name_lines():
    book = VcfFile.parse(VCARD_30.encode())
    book.set(0, {"first": "Avi", "middle": "", "last": "Cohen"})
    book.set(1, {"first": "Credit Company", "middle": "", "last": ""})
    out = book.to_bytes().decode()
    assert 'N:Cohen;Avi;;ד"ר;\r\n' in out
    assert 'FN:ד"ר Avi Cohen\r\n' in out
    assert "N:;;;;\r\nFN:Credit Company\r\n" in out
    assert "NOTE:a long note that is folded\r\n  onto a second line\r\n" in out


def test_vcard_21_quoted_printable():
    # "אבי" / "כהן" as Android exports them
    data = (
        "BEGIN:VCARD\n"
        "VERSION:2.1\n"
        "N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=D7=9B=D7=94=D7=9F;=D7=90=D7=91=\n"
        "=D7=99;;;\n"
        "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=D7=90=D7=91=D7=99 =D7=9B=D7=94=D7=9F\n"
        "TEL;CELL:+972500000001\n"
        "END:VCARD\n"
    ).encode()
    book = VcfFile.parse(data)
    assert book.to_bytes() == data
    assert book.get(0) == {"first": "אבי", "middle": "", "last": "כהן"}
    book.set(0, {"first": "Avi", "middle": "", "last": "Cohen"})
    assert book.to_bytes().decode() == (
        "BEGIN:VCARD\n"
        "VERSION:2.1\n"
        "N;CHARSET=UTF-8:Cohen;Avi;;;\n"
        "FN;CHARSET=UTF-8:Avi Cohen\n"
        "TEL;CELL:+972500000001\n"
        "END:VCARD\n"
    )


def test_vcard_escaping():
    data = "BEGIN:VCARD\nVERSION:3.0\nN:a\\;b;c\\,d;;;\nFN:x\nEND:VCARD\n".encode()
    book = VcfFile.parse(data)
    assert book.get(0) == {"first": "c,d", "middle": "", "last": "a;b"}
    book.set(0, {"first": "C, D", "middle": "", "last": "A;B"})
    assert "N:A\\;B;C\\, D;;;\nFN:C\\, D A\\;B\n" in book.to_bytes().decode()


def test_vcard_without_cards_is_rejected():
    with pytest.raises(FormatError):
        VcfFile.parse(b"hello\n")
