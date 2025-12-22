from __future__ import annotations
"""
Phase 1 LLM spec generator: description_text -> spec (JSON dict).
"""

from typing import Dict, Any
from datetime import datetime, timezone
import json
from openai import OpenAI
from ....config import settings

PROMPT_TEMPLATE = """Return ONLY a JSON object (no markdown, no commentary) matching this structure:

{
  "fields": [
    {
      "key": "name_of_field",
      "type": "string|integer|number|boolean|enum|date|phone|email|file",
      "required": true|false,
      "label": "",
      "description": "summary about this field, including: explain, required or not, valid format",

      for string
      "minLength": ,
      "maxLength": ,

      "pattern": "regex if applicable",

      for number, integer
      "minimum": ,
      "maximum": ,

      for file
      "minCount": ,
      "maxCount": ,
      
      "enum": ["a","b"],
      "default": "b",
      "accept": ["pdf","jpg","png","jpeg"]   // only for type=file
    }
  ],
  "i18n": {
    "vi": { "collect_prompt": "optional short guidance for collecting fields in Vietnamese" }
  }
}

Rules:
- Use 'phone' for Vietnamese phone numbers; if no pattern is provided we will default to ^(?:\\+84|0)\\d{9,10}$.
- Use reasonable text lengths (name <= 200; long text <= 3000).
- Use enum only when the allowed values are clearly listed.
- If description does not tell "required" or "optional" -> make it required
- Do NOT include extra keys. Do NOT include comments. Return JSON ONLY.

Admin description:
\"\"\"{DESCRIPTION}\"\"\""""

def generate_spec_from_text(description_text: str) -> Dict[str, Any]:
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = PROMPT_TEMPLATE.replace("{DESCRIPTION}", description_text)
    resp = client.chat.completions.create(
        model=settings.openai_model_ticket_gen,
        messages=[
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
    )
    content = resp.choices[0].message.content or "{}"
    try:
        spec = json.loads(content)
    except Exception:
        # Fallback super-minimal spec to avoid total failure
        spec = {
            "fields": [
                {"key": "name", "type": "string", "required": True, "minLength": 1, "maxLength": 200},
                {"key": "phone", "type": "phone", "required": True}
            ]
        }
    meta = {
        "model": settings.openai_model_ticket_gen,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
    return {"spec": spec, "llm": meta, "raw": content}
