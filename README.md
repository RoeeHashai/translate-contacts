# translate-contacts

Convert contact names written in Hebrew (or Arabic, Russian, Greek, ...) to how they'd be saved in an English phone, using an LLM.

This is not a translation of meaning. Names are converted by **sound**, the way people actually spell them in English, while descriptive words are translated by meaning:

| Before | After |
| --- | --- |
| אבי כהן | Avi Cohen |
| נועה ברק | Noa Barak |
| יעל שטרן | Yael Stern |
| אבא | Dad |
| דני עבודה | Dani Work |
| מוסך העיר | City Garage |

Only the first, middle and last names change. Phone numbers, emails, notes and everything else stay byte-for-byte identical, and your original file is never modified.

## Supported files

- **Google Contacts CSV** (export from [contacts.google.com](https://contacts.google.com) → Export → Google CSV). Outlook CSVs with `First Name` / `Last Name` columns also work.
- **vCard `.vcf`** (export from iPhone / macOS Contacts / Android). vCard 2.1, 3.0 and 4.0, including Android's quoted-printable encoding.

## Install

Requires Python 3.9+. No other dependencies.

```bash
pipx install git+https://github.com/RoeeHashai/translate-contacts
```

Or from a clone: `pip install .`

## Configure the LLM

Any OpenAI-compatible chat completions API works: OpenAI, xAI (Grok), Google Gemini, OpenRouter, a local Ollama, etc. Nothing is assumed; you choose the provider and model.

Create a `.env` file in the folder you run the tool from (see [`.env.example`](.env.example)):

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=<model name>
LLM_API_KEY=<your key>
```

Some base URLs:

| Provider | `LLM_BASE_URL` |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| xAI (Grok) | `https://api.x.ai/v1` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Ollama (local) | `http://localhost:11434/v1` |

Everything can also be passed as flags (`--base-url`, `--model`) or regular environment variables. Use `--api-key-env NAME` to read the key from a different variable.

**Tip:** reasoning models can be slow on this task. If yours supports it, set `LLM_REASONING_EFFORT=low` (or `--reasoning-effort low`).

## Usage

```bash
# See which contacts would be sent, without calling the API
translate-contacts contacts.csv --dry-run

# Try it on the first 20 contacts
translate-contacts contacts.csv --limit 20

# Translate everything, 15 contacts per request
translate-contacts contacts.csv --chunk-size 15
```

The result is written to `contacts_en.csv` (or `<name>_en.vcf`) next to the input; change it with `-o`. Then import that file back into Google Contacts or your phone.

Progress is printed after every request and the output is saved as it goes:

```
631 contacts to translate in 43 chunks of up to 15
[1/43] translating contacts 2-29 (15 contacts)...
    done 15/631 (2%), 616 left, elapsed 19s, ~13m20s remaining
```

### Resuming

If a request keeps failing (or you press Ctrl+C), the tool stops and tells you where:

```
Failed at contact: 312
Resume with: translate-contacts contacts.csv --chunk-size 15 --start-row 312
```

Running with `--start-row` continues from the existing output file.

### Other languages

Hebrew is the default. Use `--source-lang` for others: `ar` Arabic, `fa` Persian, `ru` Russian, `uk` Ukrainian, `bg` Bulgarian, `el` Greek, `hi` Hindi, `th` Thai, `zh` Chinese, `ja` Japanese, `ko` Korean.

```bash
translate-contacts contacts.vcf --source-lang ru
```

### All options

Run `translate-contacts --help`. Notable ones:

- `--response-format json_schema|json_object|none`: how JSON output is requested. The default (`json_schema`) is the most reliable; switch if your provider rejects it.
- `--env-file PATH`: load settings from a different file.

## How it works

Contacts whose names contain the source script are sent to the model in chunks, as JSON. The prompt asks: *"How would you save this contact in an English phone?"*, and the model must answer with JSON in a fixed schema. Every answer is checked before it's written: same contacts back, no source-script characters left, and no name fields added or dropped. Failed chunks are retried up to 3 times.

## Privacy

Contact names (only the name fields, not phone numbers or anything else) are sent to the LLM provider you configure. If that's a concern, use a local model via Ollama.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
