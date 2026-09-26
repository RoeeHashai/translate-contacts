"""Talking to any OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .formats import FIELDS
from .languages import Language

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "first": {"type": "string"},
                    "middle": {"type": "string"},
                    "last": {"type": "string"},
                },
                "required": ["id", "first", "middle", "last"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["contacts"],
    "additionalProperties": False,
}

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class TranslationError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def build_prompt(language: Language) -> str:
    lang = language.name
    name_examples = f"\n   Examples: {language.name_examples}." if language.name_examples else ""
    label_examples = f"\n   Examples: {language.label_examples}." if language.label_examples else ""
    return f"""You convert contacts saved in {lang} into the way they would be saved in an English phone.

Question to answer for every contact: "How would you save this {lang} contact in an English phone?"

Rules:
1. Personal names and family names are NOT translated by meaning. Convert them by SOUND, using the most common English spelling that native {lang} speakers use for that name.{name_examples}
2. Words that are clearly NOT names but descriptions/labels (family relations, roles, jobs, institutions, places, departments, businesses, abbreviations) are translated by MEANING, the way a person would label the contact in English.{label_examples}
3. Keep any text that is already in English/Latin letters, digits and punctuation exactly as it is.
4. Keep every value in its own field (first / middle / last). If a field is an empty string in the input, return an empty string for it. If a field is non-empty, return a non-empty value.
5. The output must not contain any {lang} characters.

Output format:
Respond ONLY with a JSON object, no prose and no markdown, in exactly this shape:
{{"contacts": [{{"id": <same id as input>, "first": "...", "middle": "...", "last": "..."}}]}}
Return exactly one entry for every input contact, with the same "id" values, in the same order."""


@dataclass
class LLMClient:
    base_url: str
    model: str
    api_key: str
    language: Language
    reasoning_effort: str | None = None
    response_format: str = "json_schema"
    timeout: float = 300
    max_attempts: int = 3

    def request_body(self, contacts: list[dict]) -> dict:
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_prompt(self.language)},
                {"role": "user", "content": json.dumps({"contacts": contacts}, ensure_ascii=False)},
            ],
        }
        if self.response_format == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "contact_translations", "schema": RESPONSE_SCHEMA, "strict": True},
            }
        elif self.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def call(self, contacts: list[dict]) -> list[dict]:
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(self.request_body(contacts)).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as e:
            # Other 4xx errors (auth, billing, bad request) won't succeed on retry.
            retryable = e.code == 429 or e.code >= 500
            raise TranslationError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}", retryable) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise TranslationError(f"Network error: {e}") from e
        return parse_response(payload)

    def translate(self, contacts: list[dict]) -> list[dict]:
        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = self.call(contacts)
                validate(contacts, result, self.language)
                return result
            except TranslationError as e:
                last_error = e
                print(f"  attempt {attempt}/{self.max_attempts} failed: {e}", file=sys.stderr)
                if not e.retryable:
                    break
                if attempt < self.max_attempts:
                    time.sleep(2**attempt)
        raise last_error


def parse_response(payload: dict) -> list[dict]:
    try:
        content = payload["choices"][0]["message"]["content"]
        contacts = json.loads(_CODE_FENCE.sub("", content.strip()))["contacts"]
    except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError) as e:
        raise TranslationError(f"Could not parse model response: {str(payload)[:500]}") from e
    if not isinstance(contacts, list) or not all(isinstance(c, dict) for c in contacts):
        raise TranslationError(f"Unexpected response shape: {str(contacts)[:500]}")
    return contacts


def validate(sent: list[dict], received: list[dict], language: Language) -> None:
    sent_ids = sorted(c["id"] for c in sent)
    received_ids = sorted(c.get("id") for c in received if isinstance(c.get("id"), int))
    if sent_ids != received_ids or len(received) != len(sent):
        raise TranslationError(f"ID mismatch: sent {sent_ids}, got {[c.get('id') for c in received]}")

    by_id = {c["id"]: c for c in sent}
    for item in received:
        original = by_id[item["id"]]
        for key in FIELDS:
            value = item.get(key)
            if not isinstance(value, str):
                raise TranslationError(f"Contact {item['id']}: field '{key}' missing or not a string")
            value = value.strip()
            if bool(original[key].strip()) != bool(value):
                raise TranslationError(
                    f"Contact {item['id']}: field '{key}' emptiness changed ({original[key]!r} -> {value!r})"
                )
            if language.script.search(value):
                raise TranslationError(f"Contact {item['id']}: {language.name} left in '{key}': {value!r}")
