import os
import uuid
import sqlite3
import hashlib
import hmac
import time
import json
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, make_response, render_template_string
from flask_cors import CORS


# ============================================================
# VEYA V16
# Dynamic Multi-Provider AI Platform
# Razorpay subscriptions + dynamic model discovery
# ============================================================

APP_NAME = "Veya"
VERSION = "16.0"

PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DATABASE_PATH", "veya.db")

SECRET_KEY = (
    os.getenv("SECRET_KEY", "").strip()
    or os.urandom(32).hex()
)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

CORS(app)


# ============================================================
# PLANS
# ============================================================

PLANS = {
    "free": {
        "name": "Veya Free",
        "price_inr": 0,
        "monthly_provider_budget_usd": 0.10,
        "daily_messages": 20,
        "providers": ["google", "local"],
        "model_picker": False,
        "slots": 1,
        "features": [
            "20 messages/day",
            "Cost-efficient AI routing",
            "Persistent chat history",
            "Smart task routing",
            "Coding, writing, math and general help",
        ],
    },

    "core": {
        "name": "Veya Core",
        "price_inr": 399,
        "monthly_provider_budget_usd": 1.75,
        "daily_messages": 100,
        "providers": [
            "openai",
            "google",
            "anthropic",
        ],
        "model_picker": True,
        "slots": 1,
        "features": [
            "OpenAI flagship model",
            "Google flagship model",
            "Anthropic flagship model",
            "Automatic task routing",
            "Premium model selection",
            "100 messages/day",
        ],
    },

    "all_ai": {
        "name": "Veya All AI",
        "price_inr": 999,
        "monthly_provider_budget_usd": 5.00,
        "daily_messages": 300,
        "providers": [
            "openai",
            "google",
            "anthropic",
            "xai",
            "deepseek",
            "mistral",
            "nvidia",
            "microsoft",
            "meta",
            "groq",
        ],
        "model_picker": True,
        "slots": 5,
        "features": [
            "10 AI providers",
            "Up to 5 premium model slots/provider",
            "Reasoning agent",
            "Coding agent",
            "Research agent",
            "Creative agent",
            "Verification agent",
            "300 messages/day",
        ],
    },

    "ultra": {
        "name": "Veya Ultra",
        "price_inr": 2499,
        "monthly_provider_budget_usd": 12.00,
        "daily_messages": 1000,
        "providers": [
            "openai",
            "google",
            "anthropic",
            "xai",
            "deepseek",
            "mistral",
            "nvidia",
            "microsoft",
            "meta",
            "groq",
        ],
        "model_picker": True,
        "slots": 5,
        "features": [
            "All 10 configured providers",
            "Up to 5 top live models/provider",
            "Automatic best-model routing",
            "Advanced reasoning",
            "Advanced coding",
            "Research and analysis",
            "Creative intelligence",
            "Verification layer",
            "1000 messages/day",
        ],
    },
}


# ============================================================
# PROVIDERS
# ============================================================

PROVIDERS = [
    "openai",
    "anthropic",
    "google",
    "xai",
    "deepseek",
    "mistral",
    "nvidia",
    "microsoft",
    "meta",
    "groq",
]


API_KEYS = {
    provider: os.getenv(
        f"{provider.upper()}_API_KEY",
        "",
    ).strip()
    for provider in PROVIDERS
}


BASE_URLS = {
    "openai": os.getenv(
        "OPENAI_BASE_URL",
        "https://api.openai.com/v1",
    ).strip(),

    "anthropic": os.getenv(
        "ANTHROPIC_BASE_URL",
        "https://api.anthropic.com",
    ).strip(),

    "google": os.getenv(
        "GOOGLE_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    ).strip(),

    "xai": os.getenv(
        "XAI_BASE_URL",
        "https://api.x.ai/v1",
    ).strip(),

    "deepseek": os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ).strip(),

    "mistral": os.getenv(
        "MISTRAL_BASE_URL",
        "https://api.mistral.ai/v1",
    ).strip(),

    "nvidia": os.getenv(
        "NVIDIA_BASE_URL",
        "https://integrate.api.nvidia.com/v1",
    ).strip(),

    "microsoft": os.getenv(
        "MICROSOFT_BASE_URL",
        "",
    ).strip(),

    "meta": os.getenv(
        "META_BASE_URL",
        "",
    ).strip(),

    "groq": os.getenv(
        "GROQ_BASE_URL",
        "https://api.groq.com/openai/v1",
    ).strip(),
}


# ============================================================
# MODEL OVERRIDES
# ============================================================

def env_list(name):
    return [
        x.strip()
        for x in os.getenv(name, "").split(",")
        if x.strip()
    ]


MODEL_OVERRIDES = {
    provider: env_list(
        f"{provider.upper()}_MODELS"
    )
    for provider in PROVIDERS
}


# ============================================================
# MODEL CACHE
# ============================================================

MODEL_CACHE = {}
CACHE_SECONDS = int(
    os.getenv("MODEL_CACHE_SECONDS", "300")
)


def cache_get(provider):
    item = MODEL_CACHE.get(provider)

    if not item:
        return None

    timestamp, models = item

    if time.time() - timestamp >= CACHE_SECONDS:
        return None

    return models


def cache_set(provider, models):
    MODEL_CACHE[provider] = (
        time.time(),
        models,
    )


def cache_clear(provider=None):
    if provider:
        MODEL_CACHE.pop(provider, None)
    else:
        MODEL_CACHE.clear()


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# DATABASE
# ============================================================

def db():
    connection = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = db()

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'free',
            created_at TEXT NOT NULL,
            razorpay_customer_id TEXT,
            razorpay_subscription_id TEXT,
            subscription_status TEXT
        );

        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            agent_role TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            agent_role TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payment_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    connection.commit()
    connection.close()


# ============================================================
# USERS
# ============================================================

def get_user_id():
    user_id = request.cookies.get("veya_user")

    if not user_id:
        user_id = str(uuid.uuid4())

    connection = db()

    row = connection.execute(
        """
        SELECT id
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()

    if not row:
        connection.execute(
            """
            INSERT INTO users(
                id,
                plan,
                created_at
            )
            VALUES (?, 'free', ?)
            """,
            (
                user_id,
                utc_now(),
            ),
        )

        connection.commit()

    connection.close()

    return user_id


def get_plan(user_id):
    connection = db()

    row = connection.execute(
        """
        SELECT plan
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()

    connection.close()

    if not row or row["plan"] not in PLANS:
        return "free"

    return row["plan"]


def set_user_plan(
    user_id,
    plan,
    subscription_id=None,
    status=None,
):
    connection = db()

    connection.execute(
        """
        UPDATE users
        SET plan = ?,
            razorpay_subscription_id = COALESCE(?, razorpay_subscription_id),
            subscription_status = ?
        WHERE id = ?
        """,
        (
            plan,
            subscription_id,
            status,
            user_id,
        ),
    )

    connection.commit()
    connection.close()


# ============================================================
# PROVIDER CONFIG
# ============================================================

def provider_configured(provider):
    if provider == "local":
        return bool(
            os.getenv(
                "LOCAL_BASE_URL",
                "",
            ).strip()
        )

    if not API_KEYS.get(provider):
        return False

    if provider in ("microsoft", "meta"):
        return bool(BASE_URLS.get(provider))

    return True


def provider_headers(provider):
    key = API_KEYS.get(provider, "")

    if provider == "anthropic":
        return {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    if provider == "microsoft":
        return {
            "api-key": key,
            "Content-Type": "application/json",
        }

    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ============================================================
# HTTP
# ============================================================

def request_json(
    method,
    url,
    headers=None,
    params=None,
    payload=None,
    timeout=60,
):
    response = requests.request(
        method,
        url,
        headers=headers or {},
        params=params or {},
        json=payload,
        timeout=timeout,
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:1200]}"
        )

    if not response.text.strip():
        return {}

    return response.json()


# ============================================================
# MODEL FILTER
# ============================================================

NON_CHAT_TERMS = (
    "embedding",
    "embed",
    "rerank",
    "moderation",
    "whisper",
    "tts",
    "transcrib",
    "speech-only",
    "audio-only",
    "image-generation",
)


def looks_like_chat_model(model):
    name = model.lower()

    if any(term in name for term in NON_CHAT_TERMS):
        return False

    if "embedding" in name:
        return False

    return True


# ============================================================
# MODEL DISCOVERY
# ============================================================

def discover_openai_compatible_models(provider):
    cached = cache_get(provider)

    if cached is not None:
        return cached

    if not provider_configured(provider):
        return []

    base = BASE_URLS.get(provider, "").rstrip("/")

    if not base:
        return []

    data = request_json(
        "GET",
        base + "/models",
        headers=provider_headers(provider),
        timeout=30,
    )

    models = []

    for item in data.get("data", []):
        model_id = item.get("id")

        if (
            model_id
            and looks_like_chat_model(model_id)
        ):
            models.append(model_id)

    models = list(dict.fromkeys(models))

    cache_set(provider, models)

    return models


def discover_anthropic_models():
    provider = "anthropic"

    cached = cache_get(provider)

    if cached is not None:
        return cached

    if not provider_configured(provider):
        return []

    data = request_json(
        "GET",
        BASE_URLS[provider].rstrip("/")
        + "/v1/models",
        headers=provider_headers(provider),
        timeout=30,
    )

    models = [
        item.get("id")
        for item in data.get("data", [])
        if item.get("id")
    ]

    models = list(dict.fromkeys(models))

    cache_set(provider, models)

    return models


def discover_google_models():
    provider = "google"

    cached = cache_get(provider)

    if cached is not None:
        return cached

    if not provider_configured(provider):
        return []

    data = request_json(
        "GET",
        BASE_URLS[provider].rstrip("/")
        + "/models",
        params={
            "key": API_KEYS[provider]
        },
        timeout=30,
    )

    models = []

    for item in data.get("models", []):
        name = item.get("name", "")

        if name.startswith("models/"):
            name = name[7:]

        methods = item.get(
            "supportedGenerationMethods",
            [],
        )

        if not name:
            continue

        if (
            methods
            and "generateContent" not in methods
        ):
            continue

        if not looks_like_chat_model(name):
            continue

        models.append(name)

    models = list(dict.fromkeys(models))

    cache_set(provider, models)

    return models


def discover_models(provider):
    override = MODEL_OVERRIDES.get(
        provider,
        [],
    )

    try:
        if provider == "google":
            live = discover_google_models()

        elif provider == "anthropic":
            live = discover_anthropic_models()

        elif provider in (
            "openai",
            "xai",
            "deepseek",
            "mistral",
            "nvidia",
            "microsoft",
            "meta",
            "groq",
        ):
            live = discover_openai_compatible_models(
                provider
            )

        else:
            live = []

    except Exception:
        live = []

    if live:
        if override:
            valid = [
                x for x in override
                if x in live
            ]

            if valid:
                return valid

        return live

    if provider in (
        "microsoft",
        "meta",
        "nvidia",
    ):
        return override

    return []


# ============================================================
# MODEL RANKING
# ============================================================

def model_score(
    provider,
    model,
    task="general",
):
    name = model.lower()

    score = 0

    strong = (
        "flagship",
        "ultra",
        "opus",
        "pro",
        "reason",
        "thinking",
        "large",
        "max",
        "frontier",
        "advanced",
        "expert",
    )

    for word in strong:
        if word in name:
            score += 10

    if task == "coding":
        for word in (
            "code",
            "coder",
            "reason",
            "thinking",
            "pro",
        ):
            if word in name:
                score += 15

    elif task == "research":
        for word in (
            "research",
            "reason",
            "thinking",
            "pro",
            "large",
        ):
            if word in name:
                score += 15

    elif task == "math":
        for word in (
            "reason",
            "thinking",
            "pro",
            "large",
        ):
            if word in name:
                score += 15

    elif task == "writing":
        for word in (
            "opus",
            "sonnet",
            "creative",
            "large",
            "pro",
        ):
            if word in name:
                score += 15

    return score


def rank_models(
    provider,
    models,
    task="general",
):
    return sorted(
        models,
        key=lambda x: (
            model_score(
                provider,
                x,
                task,
            ),
            len(x),
        ),
        reverse=True,
    )


# ============================================================
# PREMIUM AGENT ROLES
# ============================================================

PREMIUM_ROLES = [
    (
        "reasoning",
        "Deep Reasoning",
    ),
    (
        "coding",
        "Advanced Coding",
    ),
    (
        "research",
        "Research & Analysis",
    ),
    (
        "creative",
        "Creative Intelligence",
    ),
    (
        "verifier",
        "Verification",
    ),
]


def provider_agents(
    provider,
    limit=5,
    task="general",
):
    models = rank_models(
        provider,
        discover_models(provider),
        task,
    )

    if not models:
        return []

    agents = []

    for index in range(limit):
        role_id, role_name = PREMIUM_ROLES[
            index % len(PREMIUM_ROLES)
        ]

        model = models[
            index % len(models)
        ]

        agents.append({
            "provider": provider,
            "slot": index + 1,
            "agent_id":
                f"{provider}-{role_id}-{index + 1}",
            "agent_name": role_name,
            "agent_role": role_id,
            "model": model,
            "real_model": True,
            "shared_model":
                index >= len(models),
        })

    return agents


def premium_catalog(
    plan,
    task="general",
):
    result = []

    if plan not in PLANS:
        return result

    for provider in PLANS[plan]["providers"]:
        if provider == "local":
            continue

        if not provider_configured(provider):
            continue

        result.extend(
            provider_agents(
                provider,
                PLANS[plan]["slots"],
                task,
            )
        )

    return result


# ============================================================
# FREE MODEL
# ============================================================

def free_model():
    if provider_configured("google"):
        models = discover_models("google")

        if models:
            preferred = [
                model
                for model in models
                if any(
                    key in model.lower()
                    for key in (
                        "flash-lite",
                        "flash",
                    )
                )
            ]

            return (
                "google",
                (
                    preferred or models
                )[0],
            )

    if provider_configured("local"):
        return (
            "local",
            os.getenv(
                "LOCAL_MODEL",
                "local-model",
            ),
        )

    return None, None


# ============================================================
# TASK ROUTER
# ============================================================

def route_task(text):
    value = text.lower()

    if any(
        word in value
        for word in (
            "python",
            "javascript",
            "typescript",
            "coding",
            "code",
            "debug",
            "docker",
            "api",
            "program",
            "github",
        )
    ):
        return "coding"

    if any(
        word in value
        for word in (
            "calculate",
            "equation",
            "math",
            "mathematics",
            "proof",
            "algebra",
        )
    ):
        return "math"

    if any(
        word in value
        for word in (
            "research",
            "latest",
            "current",
            "today",
            "compare",
            "analysis",
        )
    ):
        return "research"

    if any(
        word in value
        for word in (
            "write",
            "story",
            "article",
            "email",
            "essay",
            "rewrite",
        )
    ):
        return "writing"

    return "general"


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are Veya.

Veya is a multi-provider AI orchestration platform.

Never claim to be another company's model.

Never invent an unavailable model.

Veya virtual agents are orchestration roles around
real configured models. They are not separate foundation models.

Be accurate, transparent and useful.
"""


def role_instruction(role):
    instructions = {
        "reasoning": """
Solve difficult problems carefully.
Check assumptions and distinguish facts from inference.
""",

        "coding": """
Act as an advanced software engineer.
Check syntax, architecture, dependencies and edge cases.
""",

        "research": """
Act as a research and analysis specialist.
Do not invent facts or sources.
""",

        "creative": """
Act as a creative specialist while maintaining accuracy.
""",

        "verifier": """
Act as a verification layer.
Look for contradictions, unsupported claims and errors.
""",
    }

    return instructions.get(
        role,
        instructions["reasoning"],
    )


# ============================================================
# OPENAI
# ============================================================

def call_openai(model, messages):
    data = request_json(
        "POST",
        BASE_URLS["openai"].rstrip("/")
        + "/responses",
        headers=provider_headers("openai"),
        payload={
            "model": model,
            "input": messages,
        },
        timeout=180,
    )

    answer = data.get(
        "output_text",
        "",
    )

    if not answer:
        parts = []

        for item in data.get("output", []):
            for content in item.get(
                "content",
                [],
            ):
                if content.get("type") == "output_text":
                    parts.append(
                        content.get("text", "")
                    )

        answer = "\n".join(parts).strip()

    usage = data.get("usage", {})

    return (
        answer or "The model returned no text.",
        int(
            usage.get(
                "input_tokens",
                0,
            )
        ),
        int(
            usage.get(
                "output_tokens",
                0,
            )
        ),
    )


# ============================================================
# ANTHROPIC
# ============================================================

def call_anthropic(model, messages):
    system_parts = []
    clean_messages = []

    for message in messages:
        if message["role"] == "system":
            system_parts.append(
                message["content"]
            )
        else:
            clean_messages.append({
                "role": message["role"],
                "content": message["content"],
            })

    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": clean_messages,
    }

    if system_parts:
        payload["system"] = "\n".join(
            system_parts
        )

    data = request_json(
        "POST",
        BASE_URLS["anthropic"].rstrip("/")
        + "/v1/messages",
        headers=provider_headers("anthropic"),
        payload=payload,
        timeout=180,
    )

    parts = []

    for block in data.get("content", []):
        if block.get("type") == "text":
            parts.append(
                block.get("text", "")
            )

    usage = data.get("usage", {})

    return (
        "\n".join(parts).strip()
        or "The model returned no text.",
        int(
            usage.get(
                "input_tokens",
                0,
            )
        ),
        int(
            usage.get(
                "output_tokens",
                0,
            )
        ),
    )


# ============================================================
# GOOGLE
# ============================================================

def call_google(model, messages):
    contents = []
    system_parts = []

    for message in messages:
        if message["role"] == "system":
            system_parts.append(
                message["content"]
            )
            continue

        role = message["role"]

        if role == "assistant":
            role = "model"

        contents.append({
            "role": role,
            "parts": [
                {
                    "text":
                        message["content"]
                }
            ],
        })

    payload = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": 4096,
        },
    }

    if system_parts:
        payload["systemInstruction"] = {
            "parts": [
                {
                    "text":
                        "\n".join(system_parts)
                }
            ]
        }

    data = request_json(
        "POST",
        BASE_URLS["google"].rstrip("/")
        + "/models/"
        + model
        + ":generateContent",
        params={
            "key": API_KEYS["google"]
        },
        headers={
            "Content-Type":
                "application/json"
        },
        payload=payload,
        timeout=180,
    )

    parts = []

    for candidate in data.get(
        "candidates",
        [],
    ):
        for part in candidate.get(
            "content",
            {},
        ).get(
            "parts",
            [],
        ):
            if part.get("text"):
                parts.append(
                    part["text"]
                )

    usage = data.get(
        "usageMetadata",
        {},
    )

    return (
        "\n".join(parts).strip()
        or "The model returned no text.",
        int(
            usage.get(
                "promptTokenCount",
                0,
            )
        ),
        int(
            usage.get(
                "candidatesTokenCount",
                0,
            )
        ),
    )


# ============================================================
# OPENAI-COMPATIBLE PROVIDERS
# ============================================================

def call_compatible(
    provider,
    model,
    messages,
):
    base = BASE_URLS.get(
        provider,
        "",
    ).rstrip("/")

    if not base:
        raise RuntimeError(
            f"{provider} base URL is not configured."
        )

    data = request_json(
        "POST",
        base + "/chat/completions",
        headers=provider_headers(provider),
        payload={
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
        },
        timeout=180,
    )

    choices = data.get(
        "choices",
        [],
    )

    if not choices:
        raise RuntimeError(
            f"{provider} returned no choices."
        )

    content = choices[0].get(
        "message",
        {},
    ).get(
        "content",
        "",
    )

    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
        )

    usage = data.get(
        "usage",
        {},
    )

    return (
        content or "The model returned no text.",
        int(
            usage.get(
                "prompt_tokens",
                0,
            )
        ),
        int(
            usage.get(
                "completion_tokens",
                0,
            )
        ),
    )


# ============================================================
# LOCAL
# ============================================================

def call_local(model, messages):
    base = os.getenv(
        "LOCAL_BASE_URL",
        "",
    ).strip().rstrip("/")

    if not base:
        raise RuntimeError(
            "LOCAL_BASE_URL is not configured."
        )

    data = request_json(
        "POST",
        base + "/chat/completions",
        headers={
            "Content-Type":
                "application/json"
        },
        payload={
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
        },
        timeout=180,
    )

    choices = data.get(
        "choices",
        [],
    )

    if not choices:
        raise RuntimeError(
            "Local model returned no choices."
        )

    usage = data.get(
        "usage",
        {},
    )

    return (
        choices[0].get(
            "message",
            {},
        ).get(
            "content",
            "",
        )
        or "The model returned no text.",
        int(
            usage.get(
                "prompt_tokens",
                0,
            )
        ),
        int(
            usage.get(
                "completion_tokens",
                0,
            )
        ),
    )


# ============================================================
# UNIFIED CALL
# ============================================================

def call_provider(
    provider,
    model,
    messages,
):
    if provider == "openai":
        return call_openai(
            model,
            messages,
        )

    if provider == "anthropic":
        return call_anthropic(
            model,
            messages,
        )

    if provider == "google":
        return call_google(
            model,
            messages,
        )

    if provider == "local":
        return call_local(
            model,
            messages,
        )

    return call_compatible(
        provider,
        model,
        messages,
    )


# ============================================================
# CHAT STORAGE
# ============================================================

def create_chat(
    user_id,
    title="New chat",
):
    chat_id = str(uuid.uuid4())
    timestamp = utc_now()

    connection = db()

    connection.execute(
        """
        INSERT INTO chats(
            id,
            user_id,
            title,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            title,
            timestamp,
            timestamp,
        ),
    )

    connection.commit()
    connection.close()

    return chat_id


def ensure_chat(
    user_id,
    chat_id,
):
    connection = db()

    row = connection.execute(
        """
        SELECT id
        FROM chats
        WHERE id = ?
        AND user_id = ?
        """,
        (
            chat_id,
            user_id,
        ),
    ).fetchone()

    connection.close()

    if not row:
        raise RuntimeError(
            "Chat not found."
        )


def save_message(
    chat_id,
    role,
    content,
    provider=None,
    model=None,
    agent_role=None,
):
    timestamp = utc_now()

    connection = db()

    connection.execute(
        """
        INSERT INTO messages(
            chat_id,
            role,
            content,
            provider,
            model,
            agent_role,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            role,
            content,
            provider,
            model,
            agent_role,
            timestamp,
        ),
    )

    connection.execute(
        """
        UPDATE chats
        SET updated_at = ?
        WHERE id = ?
        """,
        (
            timestamp,
            chat_id,
        ),
    )

    connection.commit()
    connection.close()


def get_messages(
    chat_id,
    limit=30,
):
    connection = db()

    rows = connection.execute(
        """
        SELECT
            role,
            content,
            provider,
            model,
            agent_role,
            created_at
        FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            chat_id,
            limit,
        ),
    ).fetchall()

    connection.close()

    return [
        dict(row)
        for row in reversed(rows)
    ]


# ============================================================
# USAGE
# ============================================================

def daily_message_count(user_id):
    today = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")

    connection = db()

    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM messages m
        JOIN chats c
        ON c.id = m.chat_id
        WHERE c.user_id = ?
        AND m.role = 'user'
        AND substr(
            m.created_at,
            1,
            10
        ) = ?
        """,
        (
            user_id,
            today,
        ),
    ).fetchone()

    connection.close()

    return int(row[0] or 0)


def monthly_cost(user_id):
    month = datetime.now(
        timezone.utc
    ).strftime("%Y-%m")

    connection = db()

    row = connection.execute(
        """
        SELECT COALESCE(
            SUM(estimated_cost_usd),
            0
        )
        FROM usage
        WHERE user_id = ?
        AND substr(
            created_at,
            1,
            7
        ) = ?
        """,
        (
            user_id,
            month,
        ),
    ).fetchone()

    connection.close()

    return float(row[0] or 0)


def estimate_cost(
    input_tokens,
    output_tokens,
):
    input_price = float(
        os.getenv(
            "DEFAULT_INPUT_COST_USD_PER_M",
            "2",
        )
    )

    output_price = float(
        os.getenv(
            "DEFAULT_OUTPUT_COST_USD_PER_M",
            "8",
        )
    )

    return (
        input_tokens / 1_000_000
        * input_price
        +
        output_tokens / 1_000_000
        * output_price
    )


def record_usage(
    user_id,
    provider,
    model,
    agent_role,
    input_tokens,
    output_tokens,
):
    cost = estimate_cost(
        input_tokens,
        output_tokens,
    )

    connection = db()

    connection.execute(
        """
        INSERT INTO usage(
            user_id,
            provider,
            model,
            agent_role,
            input_tokens,
            output_tokens,
            estimated_cost_usd,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            provider,
            model,
            agent_role,
            input_tokens,
            output_tokens,
            cost,
            utc_now(),
        ),
    )

    connection.commit()
    connection.close()

    return cost


# ============================================================
# 5000 VIRTUAL AGENTS
# ============================================================

BASE_ROLES = [
    "reasoning",
    "coding",
    "research",
    "mathematics",
    "science",
    "writing",
    "editing",
    "planning",
    "analysis",
    "fact_checking",
    "criticism",
    "summarization",
    "translation",
    "teaching",
    "product_design",
    "business_analysis",
    "security_review",
    "data_analysis",
    "architecture",
    "strategy",
]


VIRTUAL_AGENTS = [
    {
        "id":
            f"veya-agent-{i + 1:04d}",
        "role":
            f"{BASE_ROLES[i % len(BASE_ROLES)]}-"
            f"{i // len(BASE_ROLES) + 1}",
        "index":
            i + 1,
    }
    for i in range(5000)
]


# ============================================================
# MODEL SELECTION
# ============================================================

def choose_model(
    plan,
    requested_provider=None,
    requested_model=None,
    task="general",
):
    available = premium_catalog(
        plan,
        task,
    )

    if not available:
        raise RuntimeError(
            "No live AI model is available "
            "for this plan."
        )

    if requested_provider and requested_model:
        for item in available:
            if (
                item["provider"]
                == requested_provider
                and
                item["model"]
                == requested_model
            ):
                return item

        raise RuntimeError(
            "Selected model is not currently "
            "available for this plan."
        )

    return max(
        available,
        key=lambda item:
            model_score(
                item["provider"],
                item["model"],
                task,
            ),
    )


# ============================================================
# API
# ============================================================

@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "app": APP_NAME,
        "version": VERSION,
        "time": utc_now(),
    })


@app.get("/api/me")
def me():
    user_id = get_user_id()
    plan = get_plan(user_id)

    response = jsonify({
        "user_id": user_id,
        "plan": plan,
        "plan_info": PLANS[plan],
        "daily_used":
            daily_message_count(user_id),
        "monthly_cost_usd":
            monthly_cost(user_id),
    })

    response.set_cookie(
        "veya_user",
        user_id,
        httponly=True,
        samesite="Lax",
    )

    return response


@app.get("/api/plans")
def plans():
    return jsonify(PLANS)


@app.get("/api/providers")
def providers():
    output = []

    for provider in PROVIDERS:
        configured = provider_configured(
            provider
        )

        models = []

        if configured:
            try:
                models = discover_models(
                    provider
                )
            except Exception:
                models = []

        output.append({
            "provider": provider,
            "configured": configured,
            "model_count": len(models),
            "models": models,
        })

    return jsonify(output)


@app.get("/api/models")
def models():
    user_id = get_user_id()
    plan = get_plan(user_id)

    task = request.args.get(
        "task",
        "general",
    )

    return jsonify({
        "plan": plan,
        "model_picker":
            PLANS[plan]["model_picker"],
        "providers":
            PLANS[plan]["providers"],
        "premium_slots_per_provider":
            PLANS[plan]["slots"],
        "models":
            premium_catalog(
                plan,
                task,
            ),
    })


@app.get("/api/agents")
def agents():
    return jsonify({
        "count": 5000,
        "agents": VIRTUAL_AGENTS[:100],
        "premium_agent_roles": [
            {
                "id": role_id,
                "name": role_name,
            }
            for role_id, role_name
            in PREMIUM_ROLES
        ],
        "note":
            "5000 virtual orchestration roles; "
            "not 5000 independent foundation models.",
    })


@app.get("/api/premium-agents")
def premium_agents():
    user_id = get_user_id()
    plan = get_plan(user_id)

    task = request.args.get(
        "task",
        "general",
    )

    return jsonify({
        "plan": plan,
        "agents":
            premium_catalog(
                plan,
                task,
            ),
    })


# ============================================================
# CHATS
# ============================================================

@app.get("/api/chats")
def chats():
    user_id = get_user_id()

    connection = db()

    rows = connection.execute(
        """
        SELECT
            id,
            title,
            created_at,
            updated_at
        FROM chats
        WHERE user_id = ?
        ORDER BY updated_at DESC
        """,
        (user_id,),
    ).fetchall()

    connection.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


@app.post("/api/chats/new")
def new_chat():
    return jsonify({
        "chat_id":
            create_chat(
                get_user_id()
            )
    })


@app.get("/api/chats/<chat_id>")
def chat_detail(chat_id):
    user_id = get_user_id()

    ensure_chat(
        user_id,
        chat_id,
    )

    return jsonify({
        "chat_id": chat_id,
        "messages":
            get_messages(chat_id),
    })


# ============================================================
# MAIN CHAT
# ============================================================

@app.post("/api/chat")
def chat():
    user_id = get_user_id()
    plan = get_plan(user_id)
    plan_data = PLANS[plan]

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    text = str(
        body.get(
            "message",
            "",
        )
    ).strip()

    if not text:
        return jsonify({
            "error":
                "Message is required."
        }), 400

    if len(text) > 30000:
        return jsonify({
            "error":
                "Message is too long."
        }), 400

    if (
        daily_message_count(user_id)
        >= plan_data["daily_messages"]
    ):
        return jsonify({
            "error":
                "Daily message limit reached."
        }), 429

    chat_id = body.get("chat_id")

    if not chat_id:
        chat_id = create_chat(
            user_id,
            text[:60],
        )

    ensure_chat(
        user_id,
        chat_id,
    )

    requested_provider = body.get(
        "provider"
    )

    requested_model = body.get(
        "model"
    )

    task = route_task(text)

    # --------------------------------------------------------
    # FREE
    # --------------------------------------------------------

    if plan == "free":
        provider, model = free_model()

        agent_role = "free-router"

        if not provider:
            return jsonify({
                "error":
                    "No free model is configured. "
                    "Configure GOOGLE_API_KEY "
                    "or LOCAL_BASE_URL."
            }), 503

    # --------------------------------------------------------
    # PAID
    # --------------------------------------------------------

    else:
        try:
            selected = choose_model(
                plan,
                requested_provider,
                requested_model,
                task,
            )

            provider = selected["provider"]
            model = selected["model"]
            agent_role = selected["agent_id"]

        except Exception as exc:
            return jsonify({
                "error": str(exc)
            }), 503

    # --------------------------------------------------------
    # COST CONTROL
    # --------------------------------------------------------

    budget = plan_data[
        "monthly_provider_budget_usd"
    ]

    if (
        budget > 0
        and monthly_cost(user_id) >= budget
    ):
        return jsonify({
            "error":
                "Monthly AI usage budget reached. "
                "This protects the service from unexpected "
                "provider costs."
        }), 402

    role_name = "reasoning"

    for role_id, _ in PREMIUM_ROLES:
        if role_id in str(agent_role):
            role_name = role_id
            break

    messages = [
        {
            "role": "system",
            "content":
                SYSTEM_PROMPT
                + "\n\n"
                + role_instruction(
                    role_name
                ),
        }
    ]

    history = get_messages(
        chat_id,
        20,
    )

    for item in history:
        if item["role"] in (
            "user",
            "assistant",
        ):
            messages.append({
                "role":
                    item["role"],
                "content":
                    item["content"],
            })

    messages.append({
        "role": "user",
        "content": text,
    })

    # --------------------------------------------------------
    # PROVIDER CALL + FALLBACK
    # --------------------------------------------------------

    try:
        (
            answer,
            input_tokens,
            output_tokens,
        ) = call_provider(
            provider,
            model,
            messages,
        )

    except Exception:
        cache_clear(provider)

        try:
            alternatives = [
                item
                for item in rank_models(
                    provider,
                    discover_models(
                        provider
                    ),
                    task,
                )
                if item != model
            ]

            if not alternatives:
                raise

            model = alternatives[0]

            (
                answer,
                input_tokens,
                output_tokens,
            ) = call_provider(
                provider,
                model,
                messages,
            )

        except Exception as second_error:
            return jsonify({
                "error":
                    f"{provider}/{model} failed: "
                    f"{second_error}",
                "provider":
                    provider,
                "model":
                    model,
            }), 502

    cost = record_usage(
        user_id,
        provider,
        model,
        agent_role,
        input_tokens,
        output_tokens,
    )

    save_message(
        chat_id,
        "user",
        text,
    )

    save_message(
        chat_id,
        "assistant",
        answer,
        provider,
        model,
        agent_role,
    )

    return jsonify({
        "chat_id": chat_id,
        "answer": answer,
        "provider": provider,
        "model": model,
        "agent": agent_role,
        "task": task,
        "usage": {
            "input_tokens":
                input_tokens,
            "output_tokens":
                output_tokens,
            "estimated_cost_usd":
                cost,
            "monthly_cost_usd":
                monthly_cost(user_id),
            "monthly_budget_usd":
                budget,
        },
    })


# ============================================================
# MODEL HEALTH
# ============================================================

@app.post("/api/test-model")
def test_model():
    user_id = get_user_id()
    plan = get_plan(user_id)

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    provider = body.get("provider")
    model = body.get("model")

    if not provider or not model:
        return jsonify({
            "ok": False,
            "error":
                "provider and model are required.",
        }), 400

    available = premium_catalog(plan)

    allowed = any(
        item["provider"] == provider
        and item["model"] == model
        for item in available
    )

    if not allowed:
        return jsonify({
            "ok": False,
            "error":
                "Model is not currently "
                "available for this plan.",
        }), 403

    try:
        (
            answer,
            input_tokens,
            output_tokens,
        ) = call_provider(
            provider,
            model,
            [
                {
                    "role":
                        "system",
                    "content":
                        "Health check. "
                        "Reply exactly OK.",
                },
                {
                    "role":
                        "user",
                    "content":
                        "Reply exactly OK.",
                },
            ],
        )

        return jsonify({
            "ok": True,
            "provider": provider,
            "model": model,
            "answer": answer,
            "input_tokens":
                input_tokens,
            "output_tokens":
                output_tokens,
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "provider": provider,
            "model": model,
            "error": str(exc),
        }), 502


# ============================================================
# RAZORPAY
# ============================================================

RAZORPAY_KEY_ID = os.getenv(
    "RAZORPAY_KEY_ID",
    "",
).strip()

RAZORPAY_KEY_SECRET = os.getenv(
    "RAZORPAY_KEY_SECRET",
    "",
).strip()

RAZORPAY_WEBHOOK_SECRET = os.getenv(
    "RAZORPAY_WEBHOOK_SECRET",
    "",
).strip()

RAZORPAY_PLAN_CORE = os.getenv(
    "RAZORPAY_PLAN_CORE",
    "",
).strip()

RAZORPAY_PLAN_ALL_AI = os.getenv(
    "RAZORPAY_PLAN_ALL_AI",
    "",
).strip()

RAZORPAY_PLAN_ULTRA = os.getenv(
    "RAZORPAY_PLAN_ULTRA",
    "",
).strip()


def razorpay_request(
    method,
    path,
    data=None,
):
    if not (
        RAZORPAY_KEY_ID
        and RAZORPAY_KEY_SECRET
    ):
        raise RuntimeError(
            "Razorpay is not configured."
        )

    response = requests.request(
        method,
        "https://api.razorpay.com/v1"
        + path,
        auth=(
            RAZORPAY_KEY_ID,
            RAZORPAY_KEY_SECRET,
        ),
        json=data or {},
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            f"Razorpay {response.status_code}: "
            f"{response.text[:1200]}"
        )

    return response.json()


def razorpay_plan_id(plan):
    mapping = {
        "core":
            RAZORPAY_PLAN_CORE,
        "all_ai":
            RAZORPAY_PLAN_ALL_AI,
        "ultra":
            RAZORPAY_PLAN_ULTRA,
    }

    return mapping.get(plan, "")


@app.post("/api/upgrade")
def upgrade():
    user_id = get_user_id()

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    plan = body.get("plan")

    if plan not in (
        "core",
        "all_ai",
        "ultra",
    ):
        return jsonify({
            "error":
                "Invalid paid plan."
        }), 400

    if not (
        RAZORPAY_KEY_ID
        and RAZORPAY_KEY_SECRET
    ):
        return jsonify({
            "configured": False,
            "message":
                "Razorpay is not configured yet.",
            "plan": plan,
        })

    plan_id = razorpay_plan_id(plan)

    if not plan_id:
        return jsonify({
            "configured": False,
            "message":
                f"Razorpay plan ID for {plan} "
                "is not configured.",
        }), 503

    subscription = razorpay_request(
        "POST",
        "/subscriptions",
        {
            "plan_id": plan_id,
            "total_count": 120,
            "quantity": 1,
            "customer_notify": 1,
            "notes": {
                "veya_user_id":
                    user_id,
                "veya_plan":
                    plan,
            },
        },
    )

    return jsonify({
        "configured": True,
        "subscription_id":
            subscription.get("id"),
        "short_url":
            subscription.get("short_url"),
        "plan": plan,
    })


# ============================================================
# RAZORPAY WEBHOOK
# ============================================================

@app.post("/api/razorpay/webhook")
def razorpay_webhook():
    if not RAZORPAY_WEBHOOK_SECRET:
        return jsonify({
            "error":
                "Webhook secret not configured."
        }), 503

    raw_body = request.get_data(
        cache=False
    )

    signature = request.headers.get(
        "X-Razorpay-Signature",
        "",
    )

    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        expected,
        signature,
    ):
        return jsonify({
            "error":
                "Invalid webhook signature."
        }), 400

    try:
        payload = json.loads(
            raw_body.decode("utf-8")
        )
    except Exception:
        return jsonify({
            "error":
                "Invalid JSON."
        }), 400

    event_id = (
        request.headers.get(
            "X-Razorpay-Event-Id"
        )
        or hashlib.sha256(
            raw_body
        ).hexdigest()
    )

    connection = db()

    already = connection.execute(
        """
        SELECT event_id
        FROM payment_events
        WHERE event_id = ?
        """,
        (event_id,),
    ).fetchone()

    if already:
        connection.close()

        return jsonify({
            "ok": True,
            "duplicate": True,
        })

    connection.execute(
        """
        INSERT INTO payment_events(
            event_id,
            event_type,
            payload,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            event_id,
            payload.get(
                "event",
                "unknown",
            ),
            json.dumps(
                payload
            ),
            utc_now(),
        ),
    )

    connection.commit()
    connection.close()

    event = payload.get(
        "event",
        "",
    )

    subscription_entity = (
        payload
        .get("payload", {})
        .get("subscription", {})
        .get("entity", {})
    )

    subscription_id = (
        subscription_entity.get("id")
    )

    notes = (
        subscription_entity.get(
            "notes",
            {}
        )
    )

    user_id = notes.get(
        "veya_user_id"
    )

    plan = notes.get(
        "veya_plan"
    )

    if not user_id and subscription_id:
        connection = db()

        row = connection.execute(
            """
            SELECT id
            FROM users
            WHERE razorpay_subscription_id = ?
            """,
            (subscription_id,),
        ).fetchone()

        connection.close()

        if row:
            user_id = row["id"]

    if user_id and plan in (
        "core",
        "all_ai",
        "ultra",
    ):
        if event in (
            "subscription.activated",
            "subscription.charged",
            "subscription.resumed",
        ):
            set_user_plan(
                user_id,
                plan,
                subscription_id,
                "active",
            )

        elif event in (
            "subscription.paused",
        ):
            set_user_plan(
                user_id,
                "free",
                subscription_id,
                "paused",
            )

        elif event in (
            "subscription.cancelled",
            "subscription.completed",
            "subscription.halted",
        ):
            set_user_plan(
                user_id,
                "free",
                subscription_id,
                event,
            )

    return jsonify({
        "ok": True,
    })


# ============================================================
# FRONTEND
# ============================================================

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Veya — AI Intelligence Platform</title>

<style>

*{
    box-sizing:border-box;
}

html,body{
    margin:0;
    width:100%;
    height:100%;
    font-family:
        Inter,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    background:#f7f9fc;
    color:#111827;
}

button,
textarea,
select{
    font:inherit;
}

button{
    cursor:pointer;
}

#app{
    height:100vh;
    display:flex;
    overflow:hidden;
}

/* SIDEBAR */

#sidebar{
    position:fixed;
    inset:0 auto 0 0;
    width:300px;
    background:
        linear-gradient(
            180deg,
            #ffffff,
            #f5f7fb
        );
    border-right:1px solid #e5e7eb;
    transform:translateX(-100%);
    transition:.25s ease;
    z-index:40;
    display:flex;
    flex-direction:column;
    box-shadow:0 20px 60px rgba(0,0,0,.08);
}

#sidebar.open{
    transform:translateX(0);
}

#overlay{
    position:fixed;
    inset:0;
    background:rgba(15,23,42,.35);
    backdrop-filter:blur(3px);
    display:none;
    z-index:30;
}

#overlay.show{
    display:block;
}

.sidebar-brand{
    padding:22px;
    font-size:22px;
    font-weight:850;
}

.sidebar-top{
    padding:0 16px 14px;
}

.new-chat{
    width:100%;
    border:1px solid #dbe3ef;
    background:#fff;
    border-radius:14px;
    padding:13px;
    font-weight:750;
    box-shadow:0 5px 18px rgba(0,0,0,.04);
}

.history{
    flex:1;
    overflow:auto;
    padding:10px;
}

.history-item{
    padding:12px;
    margin-bottom:4px;
    border-radius:11px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}

.history-item:hover{
    background:#eaf0f8;
}

.sidebar-bottom{
    padding:15px;
    border-top:1px solid #e5e7eb;
}

/* MAIN */

#main{
    width:100%;
    height:100vh;
    display:flex;
    flex-direction:column;
}

.topbar{
    height:70px;
    display:flex;
    align-items:center;
    gap:12px;
    padding:10px 18px;
    border-bottom:1px solid #e8ebf0;
    background:rgba(255,255,255,.92);
    backdrop-filter:blur(16px);
    z-index:10;
}

.icon{
    border:0;
    background:transparent;
    font-size:25px;
    width:44px;
    height:44px;
    border-radius:12px;
}

.icon:hover{
    background:#eef2f7;
}

.brand{
    font-size:21px;
    font-weight:850;
    letter-spacing:-.5px;
}

.brand span{
    font-size:11px;
    margin-left:6px;
    padding:4px 7px;
    border-radius:20px;
    background:#eef5ff;
    color:#2563eb;
}

.spacer{
    flex:1;
}

.upgrade{
    border:0;
    color:#fff;
    background:
        linear-gradient(
            135deg,
            #2563eb,
            #7c3aed
        );
    border-radius:24px;
    padding:11px 19px;
    font-weight:800;
    box-shadow:
        0 8px 25px
        rgba(79,70,229,.22);
}

.upgrade:hover{
    transform:translateY(-1px);
}

/* CHAT */

.chat{
    flex:1;
    overflow:auto;
    padding:35px 18px 165px;
}

.message{
    max-width:900px;
    margin:0 auto 24px;
    line-height:1.7;
}

.user{
    max-width:720px;
    margin-left:auto;
    padding:14px 17px;
    border-radius:20px;
    background:#eef2f7;
    white-space:pre-wrap;
}

.assistant{
    padding:4px 0;
    white-space:pre-wrap;
}

.tag{
    color:#64748b;
    font-size:11px;
    margin-bottom:7px;
    font-weight:700;
}

/* WELCOME */

.welcome{
    max-width:900px;
    margin:7vh auto 35px;
    text-align:center;
}

.welcome h1{
    font-size:
        clamp(36px,7vw,66px);
    line-height:1.02;
    letter-spacing:-3px;
    margin:0 0 16px;
}

.gradient-text{
    background:
        linear-gradient(
            90deg,
            #2563eb,
            #7c3aed,
            #db2777
        );
    -webkit-background-clip:text;
    color:transparent;
}

.welcome p{
    color:#64748b;
    font-size:17px;
}

.cards{
    display:grid;
    grid-template-columns:
        repeat(3,1fr);
    gap:12px;
    margin-top:28px;
}

.card{
    padding:17px;
    border:1px solid #e5e7eb;
    border-radius:18px;
    background:#fff;
    text-align:left;
    box-shadow:
        0 12px 35px
        rgba(15,23,42,.05);
}

.card b{
    display:block;
    margin-bottom:6px;
}

.card span{
    color:#64748b;
    font-size:13px;
}

/* COMPOSER */

.composer-wrap{
    position:fixed;
    left:0;
    right:0;
    bottom:0;
    padding:18px;
    background:
        linear-gradient(
            transparent,
            #f7f9fc 28%
        );
}

.composer{
    max-width:900px;
    margin:auto;
    border:1px solid #dbe2ec;
    border-radius:25px;
    padding:9px;
    background:#fff;
    box-shadow:
        0 18px 50px
        rgba(15,23,42,.10);
}

.row{
    display:flex;
    gap:8px;
    align-items:flex-end;
}

.plus{
    width:43px;
    height:43px;
    border:0;
    background:transparent;
    font-size:25px;
    color:#475569;
}

.send{
    width:43px;
    height:43px;
    border:0;
    border-radius:50%;
    background:#111827;
    color:white;
    font-size:18px;
}

textarea{
    flex:1;
    border:0;
    outline:0;
    resize:none;
    min-height:43px;
    max-height:160px;
    padding:11px 5px;
}

.picker{
    display:none;
    border-bottom:1px solid #edf0f4;
    padding:10px;
}

.picker.open{
    display:block;
}

select{
    width:100%;
    padding:10px;
    border:1px solid #dce3ec;
    border-radius:12px;
    background:#fff;
}

/* MODAL */

.modal{
    position:fixed;
    inset:0;
    background:rgba(15,23,42,.48);
    backdrop-filter:blur(7px);
    display:none;
    align-items:center;
    justify-content:center;
    padding:20px;
    z-index:100;
}

.modal.show{
    display:flex;
}

.modal-box{
    width:min(1100px,100%);
    background:#fff;
    border-radius:28px;
    padding:28px;
    max-height:92vh;
    overflow:auto;
    box-shadow:
        0 30px 100px
        rgba(0,0,0,.2);
}

.close{
    float:right;
    border:0;
    background:transparent;
    font-size:27px;
}

.modal-title{
    font-size:34px;
    letter-spacing:-1.5px;
    margin-bottom:6px;
}

.modal-subtitle{
    color:#64748b;
}

.plans{
    display:grid;
    grid-template-columns:
        repeat(3,1fr);
    gap:16px;
    margin-top:25px;
}

.plan{
    position:relative;
    border:1px solid #e2e8f0;
    border-radius:22px;
    padding:22px;
    background:#fff;
    overflow:hidden;
}

.plan.featured{
    border:2px solid #6366f1;
    box-shadow:
        0 20px 50px
        rgba(99,102,241,.15);
}

.badge{
    position:absolute;
    top:15px;
    right:15px;
    font-size:11px;
    padding:5px 8px;
    border-radius:20px;
    background:#ede9fe;
    color:#6d28d9;
    font-weight:800;
}

.price{
    font-size:34px;
    font-weight:900;
    margin:13px 0;
}

.plan ul{
    padding-left:19px;
    color:#475569;
    line-height:1.8;
}

.plan button{
    width:100%;
    border:0;
    border-radius:13px;
    padding:13px;
    background:#111827;
    color:white;
    font-weight:800;
}

.plan.featured button{
    background:
        linear-gradient(
            135deg,
            #2563eb,
            #7c3aed
        );
}

/* MOBILE */

@media(max-width:760px){

    .cards,
    .plans{
        grid-template-columns:1fr;
    }

    .welcome{
        margin-top:5vh;
    }

    .welcome h1{
        letter-spacing:-2px;
    }

    .modal-box{
        padding:20px;
    }
}

</style>
</head>

<body>

<div id="app">

<aside id="sidebar">

<div class="sidebar-brand">
    Veya
</div>

<div class="sidebar-top">

<button
class="new-chat"
onclick="newChat()">
    ＋ New chat
</button>

</div>

<div
id="history"
class="history">
</div>

<div class="sidebar-bottom">
    <b id="account">Free plan</b>
    <div
    style="font-size:12px;color:#64748b;margin-top:5px">
        AI orchestration workspace
    </div>
</div>

</aside>

<div
id="overlay"
onclick="toggleSidebar()">
</div>

<main id="main">

<header class="topbar">

<button
class="icon"
onclick="toggleSidebar()">
    ☰
</button>

<div class="brand">
    Veya
    <span>AI PLATFORM</span>
</div>

<div class="spacer"></div>

<button
class="upgrade"
onclick="openUpgrade()">
    Upgrade
</button>

</header>

<section
id="chat"
class="chat">

<div
id="welcome"
class="welcome">

<h1>
    One workspace.<br>
    <span class="gradient-text">
        Many AI minds.
    </span>
</h1>

<p>
    Veya intelligently routes your task
    to the best configured AI model.
</p>

<div class="cards">

<div class="card">
<b>⚡ Smart Routing</b>
<span>
Coding, research, math, writing
and general tasks automatically
choose an appropriate model.
</span>
</div>

<div class="card">
<b>🧠 Multi-Provider</b>
<span>
Connect multiple AI providers
through one Veya workspace.
</span>
</div>

<div class="card">
<b>✓ Verification</b>
<span>
Premium roles include reasoning,
research and verification workflows.
</span>
</div>

</div>

</div>

</section>

<div class="composer-wrap">

<div class="composer">

<div
id="picker"
class="picker">

<select id="modelSelect">
</select>

</div>

<div class="row">

<button
class="plus"
onclick="togglePicker()">
    ＋
</button>

<textarea
id="input"
placeholder="Message Veya..."
onkeydown="handleKey(event)">
</textarea>

<button
class="send"
onclick="sendMessage()">
    ↑
</button>

</div>

</div>

</div>

</main>
</div>


<div
id="upgradeModal"
class="modal">

<div class="modal-box">

<button
class="close"
onclick="closeUpgrade()">
    ×
</button>

<div class="modal-title">
    Upgrade Veya
</div>

<div class="modal-subtitle">
    Choose the level of AI access that fits you.
</div>

<div class="plans">

<div class="plan">

<h3>Veya Core</h3>

<div class="price">
    ₹399<span
    style="font-size:14px;color:#64748b">
    /month
    </span>
</div>

<p>
OpenAI + Google + Anthropic
</p>

<ul>
<li>1 flagship model/provider</li>
<li>Smart task routing</li>
<li>Premium model picker</li>
<li>100 messages/day</li>
<li>Persistent history</li>
</ul>

<button
onclick="upgrade('core')">
    Choose Core
</button>

</div>


<div class="plan featured">

<div class="badge">
    MOST POPULAR
</div>

<h3>Veya All AI</h3>

<div class="price">
    ₹999<span
    style="font-size:14px;color:#64748b">
    /month
    </span>
</div>

<p>
10-provider AI workspace
</p>

<ul>
<li>10 AI providers</li>
<li>Up to 5 model slots/provider</li>
<li>Reasoning agent</li>
<li>Coding agent</li>
<li>Research agent</li>
<li>Verification agent</li>
<li>300 messages/day</li>
</ul>

<button
onclick="upgrade('all_ai')">
    Choose All AI
</button>

</div>


<div class="plan">

<h3>Veya Ultra</h3>

<div class="price">
    ₹2,499<span
    style="font-size:14px;color:#64748b">
    /month
    </span>
</div>

<p>
Maximum Veya orchestration
</p>

<ul>
<li>All 10 providers</li>
<li>Up to 5 top live models/provider</li>
<li>Advanced routing</li>
<li>Deep reasoning</li>
<li>Advanced coding</li>
<li>Research & analysis</li>
<li>Verification workflow</li>
<li>1000 messages/day</li>
</ul>

<button
onclick="upgrade('ultra')">
    Choose Ultra
</button>

</div>

</div>

<p
style="font-size:12px;color:#64748b;margin-top:20px">
Model availability depends on your configured
provider accounts, API access, region, quotas
and provider-side model availability.
</p>

</div>
</div>


<script>

let currentChat = null;
let currentPlan = "free";
let models = [];


async function api(url, options = {}) {

    const response = await fetch(
        url,
        {
            credentials:"same-origin",
            ...options,
            headers:{
                "Content-Type":
                    "application/json",
                ...(options.headers || {})
            }
        }
    );

    const data = await response.json();

    if(!response.ok){
        throw new Error(
            data.error || "Request failed"
        );
    }

    return data;
}


function toggleSidebar(){

    const sidebar =
        document.getElementById("sidebar");

    const overlay =
        document.getElementById("overlay");

    sidebar.classList.toggle("open");

    overlay.classList.toggle(
        "show",
        sidebar.classList.contains("open")
    );
}


function openUpgrade(){

    document
        .getElementById("upgradeModal")
        .classList.add("show");
}


function closeUpgrade(){

    document
        .getElementById("upgradeModal")
        .classList.remove("show");
}


async function loadMe(){

    const data =
        await api("/api/me");

    currentPlan =
        data.plan;

    document
        .getElementById("account")
        .textContent =
        data.plan_info.name;

    await loadModels();
}


async function loadModels(){

    const data =
        await api("/api/models");

    models =
        data.models || [];

    const select =
        document.getElementById(
            "modelSelect"
        );

    select.innerHTML = "";

    if(!data.model_picker){
        return;
    }

    if(!models.length){

        const option =
            document.createElement(
                "option"
            );

        option.textContent =
            "No live premium models configured";

        select.appendChild(option);

        return;
    }

    for(const item of models){

        const option =
            document.createElement(
                "option"
            );

        option.value =
            JSON.stringify({
                provider:
                    item.provider,
                model:
                    item.model
            });

        option.textContent =
            item.provider.toUpperCase()
            + " — "
            + item.agent_name
            + " — "
            + item.model
            + (
                item.shared_model
                ? " (shared)"
                : ""
            );

        select.appendChild(option);
    }
}


function togglePicker(){

    if(currentPlan === "free"){
        openUpgrade();
        return;
    }

    document
        .getElementById("picker")
        .classList.toggle("open");
}


async function loadHistory(){

    const data =
        await api("/api/chats");

    const history =
        document.getElementById(
            "history"
        );

    history.innerHTML = "";

    for(const item of data){

        const div =
            document.createElement("div");

        div.className =
            "history-item";

        div.textContent =
            item.title;

        div.onclick =
            () => openChat(item.id);

        history.appendChild(div);
    }
}


async function newChat(){

    const data =
        await api(
            "/api/chats/new",
            {
                method:"POST"
            }
        );

    currentChat =
        data.chat_id;

    document
        .getElementById("chat")
        .innerHTML = "";

    await loadHistory();
}


async function openChat(id){

    currentChat = id;

    const data =
        await api(
            "/api/chats/" + id
        );

    const chat =
        document.getElementById("chat");

    chat.innerHTML = "";

    for(const message of data.messages){

        addMessage(
            message.role,
            message.content,
            message.provider,
            message.model,
            message.agent_role
        );
    }
}


function addMessage(
    role,
    content,
    provider,
    model,
    agent
){

    const welcome =
        document.getElementById("welcome");

    if(welcome){
        welcome.remove();
    }

    const chat =
        document.getElementById("chat");

    const wrapper =
        document.createElement("div");

    wrapper.className =
        "message "
        + (
            role === "user"
            ? "user"
            : "assistant"
        );

    if(
        role === "assistant"
        && provider
        && model
    ){

        const tag =
            document.createElement("div");

        tag.className = "tag";

        tag.textContent =
            provider.toUpperCase()
            + " · "
            + model
            + (
                agent
                ? " · " + agent
                : ""
            );

        wrapper.appendChild(tag);
    }

    const body =
        document.createElement("div");

    body.textContent = content;

    wrapper.appendChild(body);

    chat.appendChild(wrapper);

    chat.scrollTop =
        chat.scrollHeight;
}


function handleKey(event){

    if(
        event.key === "Enter"
        && !event.shiftKey
    ){

        event.preventDefault();

        sendMessage();
    }
}


async function sendMessage(){

    const input =
        document.getElementById("input");

    const text =
        input.value.trim();

    if(!text){
        return;
    }

    input.value = "";

    addMessage(
        "user",
        text
    );

    let selected = null;

    if(
        currentPlan !== "free"
        && models.length
    ){

        try{

            selected =
                JSON.parse(
                    document
                        .getElementById(
                            "modelSelect"
                        )
                        .value
                );

        }catch(error){

            selected = null;
        }
    }

    try{

        const data =
            await api(
                "/api/chat",
                {
                    method:"POST",
                    body:
                        JSON.stringify({
                            chat_id:
                                currentChat,

                            message:
                                text,

                            provider:
                                selected
                                ? selected.provider
                                : null,

                            model:
                                selected
                                ? selected.model
                                : null
                        })
                }
            );

        currentChat =
            data.chat_id;

        addMessage(
            "assistant",
            data.answer,
            data.provider,
            data.model,
            data.agent
        );

        await loadHistory();

    }catch(error){

        addMessage(
            "assistant",
            "Error: " + error.message
        );
    }
}


async function upgrade(plan){

    try{

        const data =
            await api(
                "/api/upgrade",
                {
                    method:"POST",
                    body:
                        JSON.stringify({
                            plan:plan
                        })
                }
            );

        if(
            data.configured
            && data.short_url
        ){

            window.location.href =
                data.short_url;

            return;
        }

        alert(
            data.message
            ||
            "Payment gateway is not configured."
        );

    }catch(error){

        alert(error.message);
    }
}


async function boot(){

    try{

        await loadMe();
        await loadHistory();

    }catch(error){

        addMessage(
            "assistant",
            "Startup error: "
            + error.message
        );
    }
}


boot();

</script>

</body>
</html>
"""


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    user_id = get_user_id()

    response = make_response(
        render_template_string(
            HTML
        )
    )

    response.set_cookie(
        "veya_user",
        user_id,
        httponly=True,
        samesite="Lax",
    )

    return response


# ============================================================
# STARTUP
# ============================================================

init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
    )