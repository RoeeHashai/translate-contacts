from __future__ import annotations

import argparse
import os
import shlex
import sys
import time
from pathlib import Path

from . import __version__
from .formats import FIELDS, ContactFile, FormatError, load
from .languages import LANGUAGES
from .llm import LLMClient, TranslationError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="translate-contacts",
        description="Convert contact names written in another script (Hebrew, Arabic, Russian, ...) to how they "
        "would be saved in an English phone, using any OpenAI-compatible LLM API.",
    )
    parser.add_argument("input", type=Path, help="Contacts file: Google Contacts .csv or vCard .vcf")
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: <input>_en.<ext>)")
    parser.add_argument("--chunk-size", type=int, default=15, help="Contacts sent per request (default: 15)")
    parser.add_argument(
        "--start-row",
        type=int,
        help="Contact number to resume from (1 = first contact), as printed by a failed run. "
        "Continues from the existing output file. Omit to translate everything.",
    )
    parser.add_argument("--limit", type=int, help="Only translate the first N contacts that need it (preview)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show which contacts would be sent, without calling the API"
    )
    parser.add_argument(
        "--source-lang",
        choices=sorted(LANGUAGES),
        default="he",
        help="Language the names are written in (default: he)",
    )

    llm = parser.add_argument_group("LLM settings (flags override environment variables / .env)")
    llm.add_argument("--base-url", help="OpenAI-compatible API base URL, e.g. https://api.openai.com/v1 [LLM_BASE_URL]")
    llm.add_argument("--model", help="Model name [LLM_MODEL]")
    llm.add_argument(
        "--api-key-env",
        default="LLM_API_KEY",
        help="Name of the environment variable holding the API key (default: LLM_API_KEY)",
    )
    llm.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high", "xhigh"],
        help="Sent as reasoning_effort, for reasoning models that support it [LLM_REASONING_EFFORT]",
    )
    llm.add_argument(
        "--response-format",
        choices=["json_schema", "json_object", "none"],
        default="json_schema",
        help="How to request JSON output; use json_object or none if the provider rejects json_schema",
    )
    llm.add_argument("--env-file", type=Path, default=Path(".env"), help="Env file to load (default: ./.env)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args(argv)
    for name in ("chunk_size", "start_row", "limit"):
        value = getattr(args, name)
        if value is not None and value < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    return args


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def resume_command(start_row: int) -> str:
    kept, skip_next = [], False
    for arg in sys.argv[1:]:
        if skip_next:
            skip_next = False
        elif arg == "--start-row":
            skip_next = True
        elif not arg.startswith("--start-row="):
            kept.append(arg)
    return shlex.join(["translate-contacts", *kept, "--start-row", str(start_row)])


def build_client(args: argparse.Namespace) -> LLMClient:
    base_url = args.base_url or os.environ.get("LLM_BASE_URL")
    model = args.model or os.environ.get("LLM_MODEL")
    api_key = os.environ.get(args.api_key_env)
    missing = [
        label
        for label, value in (
            ("--base-url or LLM_BASE_URL", base_url),
            ("--model or LLM_MODEL", model),
            (args.api_key_env, api_key),
        )
        if not value
    ]
    if missing:
        raise SystemExit("Error: missing LLM settings: " + ", ".join(missing) + " (set them in .env or as flags)")
    return LLMClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        language=LANGUAGES[args.source_lang],
        reasoning_effort=args.reasoning_effort or os.environ.get("LLM_REASONING_EFFORT") or None,
        response_format=args.response_format,
    )


def open_contacts(args: argparse.Namespace, output: Path) -> ContactFile:
    book = load(args.input)
    if args.start_row and output.exists():
        previous = load(output)
        if len(previous) != len(book):
            raise FormatError(f"{output} has a different number of contacts than {args.input}; delete it and start over")
        print(f"Resuming from contact {args.start_row} using existing {output.name}")
        return previous
    return book


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    load_env_file(args.env_file)
    language = LANGUAGES[args.source_lang]
    output = args.output or args.input.with_name(f"{args.input.stem}_en{args.input.suffix}")

    if not args.input.is_file():
        print(f"Error: {args.input} not found", file=sys.stderr)
        return 2
    if output.resolve() == args.input.resolve():
        print("Error: output file must be different from the input file", file=sys.stderr)
        return 2

    try:
        book = open_contacts(args, output)
    except FormatError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    start_row = args.start_row or 1
    if start_row > len(book):
        print(f"Error: --start-row {start_row} is past the last contact ({len(book)})", file=sys.stderr)
        return 2

    pending = []
    for number in range(start_row, len(book) + 1):
        names = book.get(number - 1)
        if any(language.script.search(names[key]) for key in FIELDS):
            pending.append({"id": number, **names})
    if args.limit:
        pending = pending[: args.limit]

    chunks = [pending[i : i + args.chunk_size] for i in range(0, len(pending), args.chunk_size)]
    total = len(pending)

    if args.dry_run:
        print(f"{total} contacts with {language.name} names would be sent in {len(chunks)} requests:")
        for contact in pending:
            print(f"  #{contact['id']}: " + " | ".join(contact[key] for key in FIELDS))
        return 0

    client = build_client(args)
    book.save(output)
    if not pending:
        print(f"No {language.name} names to translate. Output written to {output}")
        return 0

    print(f"{total} contacts to translate in {len(chunks)} chunks of up to {args.chunk_size}")
    done = 0
    started = time.monotonic()
    for index, chunk in enumerate(chunks, 1):
        first_id = chunk[0]["id"]
        print(f"[{index}/{len(chunks)}] translating contacts {first_id}-{chunk[-1]['id']} ({len(chunk)} contacts)...")
        try:
            translations = client.translate(chunk)
        except (TranslationError, KeyboardInterrupt) as e:
            book.save(output)
            reason = "Interrupted" if isinstance(e, KeyboardInterrupt) else f"Failed: {e}"
            print(f"\n{reason}\nTranslated {done}/{total} before stopping.", file=sys.stderr)
            print(f"Failed at contact: {first_id}", file=sys.stderr)
            print(f"Resume with: {resume_command(first_id)}", file=sys.stderr)
            return 1

        for item in translations:
            book.set(item["id"] - 1, {key: item[key].strip() for key in FIELDS})
        book.save(output)

        done += len(chunk)
        elapsed = time.monotonic() - started
        eta = elapsed / done * (total - done)
        print(
            f"    done {done}/{total} ({done * 100 // total}%), {total - done} left, "
            f"elapsed {format_duration(elapsed)}, ~{format_duration(eta)} remaining"
        )

    print(f"Done. Translated {total} contacts in {format_duration(time.monotonic() - started)}.")
    print(f"Output written to {output}")
    return 0
