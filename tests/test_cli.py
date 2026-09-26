import pytest

from translate_contacts import cli
from translate_contacts.llm import LLMClient, TranslationError

CSV = (
    "First Name,Middle Name,Last Name,Phone 1 - Value\n"
    "Dana,,Levi,1\n"
    "אבי,,כהן,2\n"
    "שירה,,,3\n"
    "יוסי,,לוי,4\n"
    "חיים,,,5\n"
)
FAKE = {"אבי": "Avi", "כהן": "Cohen", "שירה": "Shira", "יוסי": "Yossi", "לוי": "Levi", "חיים": "Haim"}


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "LLM_REASONING_EFFORT"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".env").write_text("LLM_BASE_URL=https://example.test/v1\nLLM_MODEL=fake\nLLM_API_KEY=secret\n")
    (tmp_path / "contacts.csv").write_text(CSV, encoding="utf-8")
    return tmp_path


class CallLog(list):
    fake = None


@pytest.fixture
def calls(monkeypatch):
    log = CallLog()

    def fake_call(self, contacts):
        log.append([c["id"] for c in contacts])
        if getattr(fake_call, "fail_from", None) and len(log) >= fake_call.fail_from:
            raise TranslationError("simulated outage", retryable=False)
        return [{"id": c["id"], **{k: FAKE.get(c[k], c[k]) for k in ("first", "middle", "last")}} for c in contacts]

    monkeypatch.setattr(LLMClient, "call", fake_call)
    log.fake = fake_call
    return log


def run(*args):
    return cli.main(["contacts.csv", *args])


def test_full_run(workdir, calls):
    assert run("--chunk-size", "2") == 0
    assert calls == [[2, 3], [4, 5]]
    out = (workdir / "contacts_en.csv").read_text(encoding="utf-8")
    assert out == CSV.replace("אבי,,כהן", "Avi,,Cohen").replace("שירה", "Shira").replace(
        "יוסי,,לוי", "Yossi,,Levi"
    ).replace("חיים", "Haim")
    assert (workdir / "contacts.csv").read_text(encoding="utf-8") == CSV


def test_failure_then_resume(workdir, calls, capsys, monkeypatch):
    calls.fake.fail_from = 2
    monkeypatch.setattr("sys.argv", ["translate-contacts", "contacts.csv", "--chunk-size", "2"])
    assert run("--chunk-size", "2") == 1
    err = capsys.readouterr().err
    assert "Failed at contact: 4" in err
    assert "translate-contacts contacts.csv --chunk-size 2 --start-row 4" in err
    partial = (workdir / "contacts_en.csv").read_text(encoding="utf-8")
    assert "Avi,,Cohen" in partial and "יוסי" in partial

    calls.fake.fail_from = None
    calls.clear()
    assert run("--chunk-size", "2", "--start-row", "4") == 0
    assert calls == [[4, 5]]
    out = (workdir / "contacts_en.csv").read_text(encoding="utf-8")
    assert "Avi,,Cohen" in out and "Yossi,,Levi" in out and "Haim" in out


def test_limit(workdir, calls):
    assert run("--limit", "1") == 0
    assert calls == [[2]]


def test_dry_run_needs_no_llm_settings(workdir, calls, capsys):
    (workdir / ".env").unlink()
    assert run("--dry-run") == 0
    assert calls == []
    assert "4 contacts with Hebrew names" in capsys.readouterr().out
    assert not (workdir / "contacts_en.csv").exists()


def test_missing_llm_settings(workdir, calls):
    (workdir / ".env").unlink()
    with pytest.raises(SystemExit, match="LLM_BASE_URL"):
        run()


def test_vcf_input(workdir, calls):
    (workdir / "people.vcf").write_text(
        "BEGIN:VCARD\nVERSION:3.0\nN:כהן;אבי;;;\nFN:אבי כהן\nEND:VCARD\n", encoding="utf-8"
    )
    assert cli.main(["people.vcf"]) == 0
    assert (workdir / "people_en.vcf").read_text(encoding="utf-8") == (
        "BEGIN:VCARD\nVERSION:3.0\nN:Cohen;Avi;;;\nFN:Avi Cohen\nEND:VCARD\n"
    )
