import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()
MODEL = os.environ.get("ANTHROPIC_MODEL")
WS = os.environ.get("ANTHROPIC_WORKSPACE_ID")
KEY = os.environ.get("ANTHROPIC_API_KEY", "")

print("ANTHROPIC_MODEL        =", repr(MODEL))
print("ANTHROPIC_WORKSPACE_ID =", repr(WS))
print("API key                =", f"{KEY[:10]}…({len(KEY)} caracteres)")

sin_header = anthropic.Anthropic(api_key=KEY, max_retries=0)
con_header = anthropic.Anthropic(api_key=KEY, max_retries=0,
                                 default_headers={"anthropic-workspace-id": WS or ""})
ping = [{"role": "user", "content": "ping"}]


def probar(nombre, fn):
    try:
        r = fn()
        print(f"[OK]    {nombre}")
        return True
    except anthropic.APIStatusError as e:
        print(f"[FALLA] {nombre} → HTTP {e.status_code}")
        with open("diag_api.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== {nombre} ===\n")
            f.write(json.dumps(e.body, ensure_ascii=False, indent=2) if e.body else e.response.text)
        return False


open("diag_api.log", "w").close()
probar("1. mínimo, sin header de workspace",
       lambda: sin_header.messages.create(model=MODEL, max_tokens=20, messages=ping))
probar("2. mínimo, con header de workspace",
       lambda: con_header.messages.create(model=MODEL, max_tokens=20, messages=ping))

from prompts import SYSTEM_PROMPT
from herramientas import TOOLS

probar("3. + SYSTEM_PROMPT",
       lambda: sin_header.messages.create(model=MODEL, max_tokens=20, messages=ping,
                                          system=SYSTEM_PROMPT))
for i, t in enumerate(TOOLS):
    probar(f"4.{i} + tool '{t['name']}'",
           lambda t=t: sin_header.messages.create(model=MODEL, max_tokens=20,
                                                  messages=ping, tools=[t]))

print("\nMensajes completos en diag_api.log:")
print(open("diag_api.log", encoding="utf-8").read())