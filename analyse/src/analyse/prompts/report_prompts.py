from __future__ import annotations

from typing import Any

from analyse.prompts.json_schema_prompts import (
    build_json_schema_instruction,
)
from analyse.prompts.system_prompts import get_system_prompt
from analyse.utils.safe_json import safe_json_dumps


def build_report_prompt(
    context: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> str:
    schema_instruction = build_json_schema_instruction(schema)

    return f"""{get_system_prompt()}

OUTPUT REQUIREMENTS:
{schema_instruction}

JSON CONTEXT:
{safe_json_dumps(context)}
""".strip()