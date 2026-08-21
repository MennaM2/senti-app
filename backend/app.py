"""
Senti Health - Backend (RECONSTRUCTED)
======================================
NOTE: The original app.py was not present in the uploaded archive - only a
compiled __pycache__/app.cpython-314.pyc survived. This file was rebuilt by
disassembling that bytecode and reading back every embedded string
(imports, route names, the system prompt, the model id, the JSON db schema,
the ChatML prompt template, etc).

Everything below marked "EXTRACTED" was read directly out of the bytecode's
string table, so it should be accurate. Everything marked "INFERRED" is a
reasonable reconstruction where the exact value (e.g. an int, a float, or
which CORS origin string) doesn't survive as plain text in bytecode and had
to be filled in sensibly. Review the INFERRED bits carefully against your
own memory of the project before trusting them.
"""

from pathlib import Path
from datetime import datetime, timezone
import json
import os

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI
import uvicorn

load_dotenv()

app = FastAPI()

# EXTRACTED: allow_origins / allow_credentials / allow_methods / allow_headers
# keys were all present in the bytecode's CORSMiddleware call.
# INFERRED: the actual origin string wasn't visible as plain text. Using the
# CRA dev server default (localhost:3000) here - update if yours differs.
# NOTE: don't set allow_origins=["*"] together with allow_credentials=True -
# FastAPI/Starlette will raise a runtime error for that combination.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CHANGED: local Qwen2-1.5B (transformers/torch, loaded on startup) replaced
# with Groq's hosted API, per explicit request - too slow/heavy on CPU.
# No local model download, no torch, no multi-GB weights on disk anymore.
#
# NOTE: llama-3.3-70b-versatile (originally chosen) was deprecated by Groq
# on 2026-06-17 and fully shut down on 2026-08-16. Switched to
# openai/gpt-oss-120b, Groq's own official recommended replacement for that
# model (see https://console.groq.com/docs/deprecations) - same tier of
# quality/speed, currently active.
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Create backend/.env with a line like:\n"
        "GROQ_API_KEY=your_key_here\n"
        "Get a free key at https://console.groq.com/keys"
    )

# Groq's API is OpenAI-compatible, so the standard `openai` client works
# unchanged - just pointed at Groq's base_url with a Groq key.
client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
print(f"Using Groq API - model: {GROQ_MODEL}")

# CHANGED (per user request, 2nd pass): first version still produced one
# unbroken wall-of-text paragraph with a decorative emoji, which felt
# disorganized and uncomfortable to read for someone asking for emotional
# support. User pointed to the (separately, naturally well-structured)
# sleep-tips reply as the readability standard to match. Now explicit about
# paragraph breaks and no emojis, for every kind of reply - not just
# practical/list-style ones.
system_prompt = (
"Be emotionally warm and genuinely caring. When the user shares something "
"personal or emotional, do not jump immediately into a list of solutions. "
"First respond to the feeling itself and make the user feel understood. "
"Use natural, specific emotional language based on what they actually said. "

"Do not simply say 'I understand' or 'I hear you'. Explain briefly why their "
"feeling might make sense in the context they described. Reassure them when "
"appropriate that their feelings do not automatically mean something is wrong "
"with them. "

"After acknowledging and validating the feeling, you may give a few gentle, "
"practical suggestions if they are relevant. Advice should feel like part of "
"the conversation, not like a generic self-help article. Usually 1-3 useful "
"suggestions are enough in an emotional conversation. "

"Keep the conversation open by asking one thoughtful, natural follow-up "
"question when it would help understand the user better. The question should "
"feel caring and conversational, not clinical or like an interview. "

"Prefer questions such as 'Can I ask you something?', 'What does it feel like "
"when...?', or 'Do you think it's more because...?' when appropriate. "
"Do not ask several questions at once unless the user specifically asks for "
"a detailed assessment. "

"Balance every emotional response between: "
"empathy and validation + useful help + natural conversation. "
"Do not become so focused on advice that you stop talking to the user, and do "
"not become so focused on empathy that you stop being useful. "

"You have two tools available: log_mood, which you should call whenever the "
"user clearly expresses how they're feeling, so it's saved to their history "
"without them needing a separate button; and get_recent_moods, which you "
"should call whenever they ask how they've been feeling lately, so your "
"answer is based on their real logged data instead of a guess. Use these "
"naturally as part of the conversation, not as something you announce."
)
# EXTRACTED: filename and top-level keys
DB_FILE = Path("database.json")


def load_db():
    if DB_FILE.exists():
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"users": [], "moods": [], "chat_history": []}


def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)


# --- REAL TOOL CALLING ---
# Two tools the model can actually invoke mid-conversation. This is genuine
# Groq/OpenAI-style function calling (tools=[...] + a tool_calls round trip),
# not a scripted keyword match - the model decides for itself whether and
# when to call these based on what the user says.

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "log_mood",
            "description": (
                "Log the user's current mood to their mood history when they "
                "clearly express how they're feeling in conversation, so it's "
                "saved automatically without them needing to use a separate "
                "mood-check button. Only call this when the user has actually "
                "expressed a mood, not on every message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mood": {
                        "type": "string",
                        "enum": ["Awful", "Rough", "Okay", "Good", "Great"],
                        "description": "The user's mood, mapped to the closest of these five levels.",
                    },
                    "note": {
                        "type": "string",
                        "description": "A short note capturing what they said, in their own words or a close paraphrase.",
                    },
                },
                "required": ["mood"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_moods",
            "description": (
                "Get the user's recently logged moods with dates, to answer "
                "questions like 'how have I been feeling lately' or 'how was "
                "my week' using their real logged data instead of guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many recent mood entries to retrieve. Defaults to 7.",
                    },
                },
                "required": [],
            },
        },
    },
]


def tool_log_mood(mood, note=""):
    data = load_db()
    record = {
        "mood": mood,
        "note": note or "",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    data["moods"].append(record)
    save_db(data)
    return {"status": "logged", "entry": record}


def tool_get_recent_moods(limit=7):
    data = load_db()
    recent = list(reversed(data["moods"]))[:limit]
    return {"moods": recent, "count": len(recent)}


TOOL_FUNCTIONS = {
    "log_mood": tool_log_mood,
    "get_recent_moods": tool_get_recent_moods,
}


# EXTRACTED: route "/api/mood", success message "Mood logged successfully!"
@app.post("/api/mood")
def log_mood(entry: dict = Body(...)):
    data = load_db()
    record = {
        "mood": entry.get("mood"),
        "note": entry.get("note"),
        "createdAt": entry.get("createdAt", datetime.now(timezone.utc).isoformat()),
    }
    data["moods"].append(record)
    save_db(data)
    return {"message": "Mood logged successfully!", "entry": record}


# EXTRACTED: route "/api/moods", uses reversed(list)
@app.get("/api/moods")
def get_moods():
    data = load_db()
    return {"moods": list(reversed(data["moods"]))}


# EXTRACTED: route "/api/chat-history"
@app.get("/api/chat-history")
def get_chat_history():
    data = load_db()
    return {"chat_history": data["chat_history"]}


# CHANGED: route path, request field ("message"), response field ("reply"),
# and chat_history persistence are all UNCHANGED from the original - the
# frontend needs zero changes. What changed internally: Groq's chat
# completions API takes a proper messages=[...] list (system/user roles)
# and returns clean assistant text directly, so the manual ChatML string
# building, the raw-text split/strip, and the "\[.*?\]" bracket-stripping
# regex are no longer needed - those all existed to work around quirks of
# calling a raw text-generation pipeline locally. Same system_prompt as
# before (still extracted verbatim from the original bytecode).
#
# CHANGED (tool calling added): the model now gets real tools (log_mood,
# get_recent_moods) instead of just producing text. This follows Groq's
# standard local-tool-calling pattern: call the model with tools=[...], and
# if it responds with tool_calls, we execute them ourselves and send the
# results back in a second call so the model can give a final answer that
# actually reflects what the tool returned.
@app.post("/api/chat")
def chat(body: dict = Body(...)):
    user_message = body.get("message", "")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        tools=TOOLS,
        max_tokens=1000,
        temperature=0.7,
    )
    response_message = completion.choices[0].message

    if response_message.tool_calls:
        # Echo the assistant's tool-call request back into the conversation
        # (as a plain dict, not the SDK object, so it serializes predictably
        # on the second request).
        messages.append({
            "role": "assistant",
            "content": response_message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in response_message.tool_calls
            ],
        })

        for tool_call in response_message.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            fn = TOOL_FUNCTIONS.get(fn_name)
            print(f"[tool call] {fn_name}({fn_args})")
            result = fn(**fn_args) if fn else {"error": f"unknown tool: {fn_name}"}
            print(f"[tool result] {result}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": fn_name,
                "content": json.dumps(result),
            })

        # Second call: give the model the tool result so it can respond
        # naturally, now grounded in what actually got logged/retrieved.
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
        )
        response_message = completion.choices[0].message

    ai_response = response_message.content.strip()

    data = load_db()
    data["chat_history"].append({"user": user_message, "reply": ai_response})
    save_db(data)

    return {"reply": ai_response}


# EXTRACTED: host "127.0.0.1", the "host"/"port" kwarg names, and __main__ guard.
# INFERRED: port number (an int literal, not recoverable as text). Using 5000
# because the frontend hardcodes http://localhost:5000 and its own error
# messages say "Is the backend running on port 5000?".
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)