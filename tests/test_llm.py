import json

import pytest

from translate_contacts.languages import LANGUAGES
from translate_contacts.llm import LLMClient, TranslationError, build_prompt, parse_response, validate

HEBREW = LANGUAGES["he"]
SENT = [{"id": 1, "first": "אבי", "middle": "", "last": "כהן"}]


def reply(content):
    return {"choices": [{"message": {"content": content}}]}


def test_parse_response_plain_and_fenced():
    body = '{"contacts": [{"id": 1, "first": "Avi", "middle": "", "last": "Cohen"}]}'
    assert parse_response(reply(body))[0]["first"] == "Avi"
    assert parse_response(reply(f"```json\n{body}\n```"))[0]["last"] == "Cohen"


def test_parse_response_rejects_garbage():
    with pytest.raises(TranslationError):
        parse_response(reply("sure! here you go"))
    with pytest.raises(TranslationError):
        parse_response({"error": "nope"})


def test_validate_accepts_good_answer():
    validate(SENT, [{"id": 1, "first": "Avi", "middle": "", "last": "Cohen"}], HEBREW)


@pytest.mark.parametrize(
    "received",
    [
        [],
        [{"id": 2, "first": "Avi", "middle": "", "last": "Cohen"}],
        [{"id": 1, "first": "Avi", "middle": "", "last": ""}],
        [{"id": 1, "first": "Avi", "middle": "X", "last": "Cohen"}],
        [{"id": 1, "first": "Avi", "middle": "", "last": "כהן"}],
        [{"id": 1, "first": "Avi", "last": "Cohen"}],
    ],
)
def test_validate_rejects_bad_answers(received):
    with pytest.raises(TranslationError):
        validate(SENT, received, HEBREW)


def test_prompt_mentions_language_and_json():
    prompt = build_prompt(LANGUAGES["ru"])
    assert "Russian" in prompt and "English phone" in prompt and '"contacts"' in prompt


def test_request_body_options():
    client = LLMClient("https://example.test/v1", "some-model", "key", HEBREW)
    body = client.request_body(SENT)
    assert body["model"] == "some-model"
    assert body["response_format"]["type"] == "json_schema"
    assert "reasoning_effort" not in body
    assert json.loads(body["messages"][1]["content"]) == {"contacts": SENT}

    client = LLMClient("u", "m", "k", HEBREW, reasoning_effort="low", response_format="none")
    body = client.request_body(SENT)
    assert body["reasoning_effort"] == "low"
    assert "response_format" not in body
