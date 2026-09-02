from pathlib import Path
import sys


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    if text.count(start) != 1:
        raise SystemExit(f"{label}: expected one start marker, got {text.count(start)}")
    start_index = text.index(start)
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_index] + replacement + text[end_index:]


def block(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-m0-final-review-fixes.py <target-repository>")

    target = Path(sys.argv[1])
    path = target / "tools/parity/verify_m0.py"
    text = path.read_text(encoding="utf-8")

    text = replace_section(
        text,
        "    lines = [line for line in process.stdout.splitlines() if line.strip()]\n",
        "    if not isinstance(result, dict):\n",
        block([
            "    lines = [line for line in process.stdout.splitlines() if line.strip()]",
            "    if len(lines) != 1:",
            "        raise RuntimeError(",
            "            f\"Command must produce exactly one nonblank stdout line: {' '.join(command)}; \"",
            "            f\"got {len(lines)}\"",
            "        )",
            "    try:",
            "        result = json.loads(lines[0])",
            "    except json.JSONDecodeError as error:",
            "        raise RuntimeError(",
            "            f\"CLI stdout was not JSON for {' '.join(command)}: {lines[0]}\"",
            "        ) from error",
        ]),
        "stdout contract",
    )

    text = replace_section(
        text,
        "def _has_specialist_step(events: list[dict[str, object]]) -> bool:\n",
        "\n\ndef _assert_expected_behavior(\n",
        block([
            "def _specialist_steps(events: list[dict[str, object]]) -> list[str]:",
            "    steps: list[str] = []",
            "    for event in events:",
            "        data = event.get(\"data\")",
            "        if isinstance(data, dict):",
            "            step = str(data.get(\"step\", \"\"))",
            "            if step.startswith(\"specialist.\"):",
            "                steps.append(step)",
            "    return steps",
            "",
            "",
            "def _has_specialist_step(events: list[dict[str, object]]) -> bool:",
            "    return bool(_specialist_steps(events))",
        ]),
        "specialist helper",
    )

    text = replace_section(
        text,
        "        if not _has_specialist_step(events):\n",
        "        selected_events = [event for event in events if event.get(\"type\") == \"route.selected\"]\n",
        block([
            "        expected_specialist_step = f\"specialist.{expected_route}\"",
            "        specialist_steps = _specialist_steps(events)",
            "        if not specialist_steps:",
            "            raise AssertionError(f\"{label} did not emit a specialist step\")",
            "        if any(step != expected_specialist_step for step in specialist_steps):",
            "            raise AssertionError(",
            "                f\"{label} specialist steps must match {expected_specialist_step}: {specialist_steps}\"",
            "            )",
        ]),
        "specialist route binding",
    )

    npm_start = block([
        "        ts_result = _run([",
        "            \"npm\",",
        "            \"--prefix\",",
    ])
    npm_replacement = block([
        "        ts_result = _run([",
        "            \"npm\",",
        "            \"--silent\",",
        "            \"--prefix\",",
    ])
    if text.count(npm_start) != 1:
        raise SystemExit(f"silent npm: expected one target, got {text.count(npm_start)}")
    text = text.replace(npm_start, npm_replacement)

    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
