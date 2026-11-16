import os
import uuid
import sqlite3
import hashlib
import hmac
import time
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, make_response, render_template_string
from flask_cors import CORS


# ============================================================
# VEYA 15.1
# Dynamic Multi-Provider AI Platform
# ============================================================

APP_NAME = "Veya"
VERSION = "15.1"

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
        "name": "Free",
        "price_inr": 0,
        "monthly_provider_budget_usd": 0.0,
        "daily_messages": 20,
        "providers": [
            "google",
            "local",
        ],
        "model_picker": False,
        "slots": 1,
    },

    "core": {
        "name": "Veya Core",
        "price_inr": 199,
        "monthly_provider_budget_usd": 1.25,
        "daily_messages": 100,
        "providers": [
            "openai",
            "google",
            "anthropic",
        ],
        "model_picker": True,
        "slots": 3,
    },

    "all_ai": {
        "name": "Veya All AI",
        "price_inr": 599,
        "monthly_provider_budget_usd": 4.00,
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
    },

    "ultra": {
        "name": "Veya Ultra",
        "price_inr": 1499,
        "monthly_provider_budget_usd": 10.00,
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
    },
}


# ============================================================
# API KEYS
# ============================================================

API_KEYS = {
    provider: os.getenv(
        f"{provider.upper()}_API_KEY",
        "",
    ).strip()
    for provider in [
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
}


# ============================================================
# BASE URLS
# ============================================================

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
# OPTIONAL MODEL OVERRIDES
#
# Example:
#
# GOOGLE_MODELS=gemini-3.8-flash,gemini-3.6-flash
#
# Live discovery is preferred.
# ============================================================

def env_list(name):
    return [
        item.strip()
        for item in os.getenv(
            name,
            "",
        ).split(",")
        if item.strip()
    ]


MODEL_OVERRIDES = {
    provider: env_list(
        f"{provider.upper()}_MODELS"
    )
    for provider in API_KEYS
}


# ============================================================
# MODEL CACHE
# ============================================================

MODEL_CACHE = {}

CACHE_SECONDS = int(
    os.getenv(
        "MODEL_CACHE_SECONDS",
        "300",
    )
)


def cache_get(provider):
    item = MODEL_CACHE.get(
        provider
    )

    if not item:
        return None

    timestamp, models = item

    if (
        time.time() - timestamp
        >= CACHE_SECONDS
    ):
        return None

    return models


def cache_set(provider, models):
    MODEL_CACHE[provider] = (
        time.time(),
        models,
    )


def cache_clear(provider=None):
    if provider:
        MODEL_CACHE.pop(
            provider,
            None,
        )
    else:
        MODEL_CACHE.clear()


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


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
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT
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
        """
    )

    connection.commit()
    connection.close()


# ============================================================
# USER
# ============================================================

def get_user_id():
    user_id = request.cookies.get(
        "veya_user"
    )

    if not user_id:
        user_id = str(
            uuid.uuid4()
        )

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

    if not row:
        return "free"

    if row["plan"] not in PLANS:
        return "free"

    return row["plan"]


# ============================================================
# PROVIDER CONFIGURATION
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

    if provider in (
        "microsoft",
        "meta",
    ):
        return bool(
            BASE_URLS.get(provider)
        )

    return True


def provider_headers(provider):
    key = API_KEYS.get(
        provider,
        "",
    )

    if provider == "anthropic":
        return {
            "x-api-key": key,
            "anthropic-version":
                "2023-06-01",
            "Content-Type":
                "application/json",
        }

    if provider == "microsoft":
        return {
            "api-key": key,
            "Content-Type":
                "application/json",
        }

    return {
        "Authorization":
            f"Bearer {key}",
        "Content-Type":
            "application/json",
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
)


def looks_like_chat_model(model):
    name = model.lower()

    if any(
        term in name
        for term in NON_CHAT_TERMS
    ):
        return False

    if "image" in name:
        return False

    if "vision" in name:
        return False

    return True


# ============================================================
# OPENAI-COMPATIBLE MODEL DISCOVERY
# ============================================================

def discover_openai_compatible_models(
    provider
):
    cached = cache_get(
        provider
    )

    if cached is not None:
        return cached

    if not provider_configured(
        provider
    ):
        return []

    base = BASE_URLS.get(
        provider,
        "",
    ).rstrip("/")

    if not base:
        return []

    data = request_json(
        "GET",
        base + "/models",
        headers=provider_headers(
            provider
        ),
        timeout=30,
    )

    models = []

    for item in data.get(
        "data",
        [],
    ):
        model_id = item.get(
            "id"
        )

        if (
            model_id
            and looks_like_chat_model(
                model_id
            )
        ):
            models.append(
                model_id
            )

    models = list(
        dict.fromkeys(
            models
        )
    )

    cache_set(
        provider,
        models,
    )

    return models


# ============================================================
# ANTHROPIC
# ============================================================

def discover_anthropic_models():
    provider = "anthropic"

    cached = cache_get(
        provider
    )

    if cached is not None:
        return cached

    if not provider_configured(
        provider
    ):
        return []

    data = request_json(
        "GET",
        BASE_URLS[
            provider
        ].rstrip("/")
        + "/v1/models",
        headers=provider_headers(
            provider
        ),
        timeout=30,
    )

    models = [
        item.get("id")
        for item in data.get(
            "data",
            [],
        )
        if item.get("id")
    ]

    models = list(
        dict.fromkeys(
            models
        )
    )

    cache_set(
        provider,
        models,
    )

    return models


# ============================================================
# GOOGLE
#
# IMPORTANT:
# Do NOT hard-code Gemini 2.5.
#
# We discover the models available to the actual API key.
# Gemini 2.5/3.7 are excluded because the screenshot shows
# the new-user 2.5 access problem and 3.7 has been replaced.
# ============================================================

def discover_google_models():
    provider = "google"

    cached = cache_get(
        provider
    )

    if cached is not None:
        return cached

    if not provider_configured(
        provider
    ):
        return []

    data = request_json(
        "GET",
        BASE_URLS[
            provider
        ].rstrip("/")
        + "/models",
        params={
            "key":
                API_KEYS[
                    provider
                ]
        },
        timeout=30,
    )

    models = []

    for item in data.get(
        "models",
        [],
    ):
        name = item.get(
            "name",
            "",
        )

        if name.startswith(
            "models/"
        ):
            name = name[
                len("models/"):
            ]

        methods = item.get(
            "supportedGenerationMethods",
            [],
        )

        if not name:
            continue

        if (
            methods
            and
            "generateContent"
            not in methods
        ):
            continue

        if not looks_like_chat_model(
            name
        ):
            continue

        # Prevent the exact deprecated/new-user
        # problem visible in the screenshot.
        if name.startswith(
            "gemini-2.5"
        ):
            continue

        if name.startswith(
            "gemini-3.7"
        ):
            continue

        models.append(
            name
        )

    models = list(
        dict.fromkeys(
            models
        )
    )

    cache_set(
        provider,
        models,
    )

    return models


# ============================================================
# UNIVERSAL DISCOVERY
# ============================================================

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
            live = (
                discover_openai_compatible_models(
                    provider
                )
            )

        else:
            live = []

    except Exception:
        live = []

    # If the provider gave us a live list,
    # never invent a model.
    if live:

        if override:
            valid = [
                model
                for model in override
                if model in live
            ]

            if valid:
                return valid

        return live

    # Some hosted/deployment providers may need
    # explicit deployment/model names.
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

    frontier_words = (
        "ultra",
        "pro",
        "opus",
        "reason",
        "thinking",
        "large",
        "flagship",
        "frontier",
        "advanced",
        "max",
        "4.",
    )

    for word in frontier_words:
        if word in name:
            score += 10

    if task == "coding":

        for word in (
            "code",
            "coder",
            "dev",
            "reason",
            "thinking",
        ):
            if word in name:
                score += 12

    elif task == "research":

        for word in (
            "research",
            "reason",
            "thinking",
            "pro",
            "large",
        ):
            if word in name:
                score += 12

    elif task == "math":

        for word in (
            "reason",
            "thinking",
            "pro",
            "large",
        ):
            if word in name:
                score += 12

    elif task == "writing":

        for word in (
            "opus",
            "sonnet",
            "creative",
            "large",
            "pro",
        ):
            if word in name:
                score += 12

    return score


def rank_models(
    provider,
    models,
    task,
):
    return sorted(
        models,
        key=lambda model: (
            model_score(
                provider,
                model,
                task,
            ),
            len(model),
        ),
        reverse=True,
    )


# ============================================================
# PREMIUM AGENT ROLES
# ============================================================

PREMIUM_ROLES = [
    (
        "reasoning",
        "Deep Reasoning Agent",
    ),
    (
        "coding",
        "Advanced Coding Agent",
    ),
    (
        "research",
        "Research & Analysis Agent",
    ),
    (
        "creative",
        "Creative Intelligence Agent",
    ),
    (
        "verifier",
        "Verification Agent",
    ),
]


def provider_agents(
    provider,
    limit=5,
    task="general",
):
    models = rank_models(
        provider,
        discover_models(
            provider
        ),
        task,
    )[:limit]

    if not models:
        return []

    agents = []

    for index in range(
        limit
    ):
        role_id, role_name = (
            PREMIUM_ROLES[
                index % 5
            ]
        )

        model = models[
            index % len(models)
        ]

        agents.append({
            "provider":
                provider,

            "slot":
                index + 1,

            "agent_id":
                f"{provider}-{role_id}-{index + 1}",

            "agent_name":
                role_name,

            "agent_role":
                role_id,

            "model":
                model,

            "real_model":
                True,

            "shared_model":
                index >= len(models),
        })

    return agents


def premium_catalog(
    plan,
    task="general",
):
    output = []

    for provider in PLANS[
        plan
    ]["providers"]:

        if provider == "local":
            continue

        if not provider_configured(
            provider
        ):
            continue

        output.extend(
            provider_agents(
                provider,
                PLANS[
                    plan
                ]["slots"],
                task,
            )
        )

    return output


# ============================================================
# FREE MODEL
# ============================================================

def free_model():
    if provider_configured(
        "google"
    ):
        models = discover_models(
            "google"
        )

        if models:

            preferred = [
                model
                for model in models
                if any(
                    item in model.lower()
                    for item in (
                        "3.8-flash",
                        "3.6-flash",
                        "3.5-flash-lite",
                        "3.1-flash-lite",
                    )
                )
            ]

            return (
                "google",
                (
                    preferred
                    or models
                )[0],
            )

    if provider_configured(
        "local"
    ):
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

You are a multi-provider AI orchestration platform.

Never claim to be another company's model.

Never invent an unavailable model.

Virtual Veya agents are orchestration roles around
real configured models. They are not separate
foundation models.

Be accurate, useful and transparent.
"""


def role_instruction(role):
    instructions = {
        "reasoning": """
Solve difficult problems carefully.
Check assumptions and separate facts from inference.
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
Act as a high-quality creative specialist.
Preserve accuracy while producing useful output.
""",

        "verifier": """
Act as a verification layer.
Look for contradictions and unsupported claims.
""",
    }

    return instructions.get(
        role,
        instructions["reasoning"],
    )


# ============================================================
# OPENAI
# ============================================================

def call_openai(
    model,
    messages,
):
    data = request_json(
        "POST",
        BASE_URLS[
            "openai"
        ].rstrip("/")
        + "/responses",
        headers=provider_headers(
            "openai"
        ),
        payload={
            "model":
                model,

            "input":
                messages,
        },
        timeout=180,
    )

    answer = data.get(
        "output_text",
        "",
    )

    if not answer:
        parts = []

        for item in data.get(
            "output",
            [],
        ):
            for content in item.get(
                "content",
                [],
            ):
                if content.get(
                    "type"
                ) == "output_text":
                    parts.append(
                        content.get(
                            "text",
                            "",
                        )
                    )

        answer = "\n".join(
            parts
        ).strip()

    usage = data.get(
        "usage",
        {},
    )

    return (
        answer
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
# ANTHROPIC
# ============================================================

def call_anthropic(
    model,
    messages,
):
    system_parts = []

    clean_messages = []

    for message in messages:

        if message["role"] == "system":
            system_parts.append(
                message["content"]
            )
        else:
            clean_messages.append({
                "role":
                    message["role"],

                "content":
                    message["content"],
            })

    payload = {
        "model":
            model,

        "max_tokens":
            4096,

        "messages":
            clean_messages,
    }

    if system_parts:
        payload["system"] = (
            "\n".join(
                system_parts
            )
        )

    data = request_json(
        "POST",
        BASE_URLS[
            "anthropic"
        ].rstrip("/")
        + "/v1/messages",
        headers=provider_headers(
            "anthropic"
        ),
        payload=payload,
        timeout=180,
    )

    parts = []

    for block in data.get(
        "content",
        [],
    ):
        if block.get(
            "type"
        ) == "text":
            parts.append(
                block.get(
                    "text",
                    "",
                )
            )

    usage = data.get(
        "usage",
        {},
    )

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
# GOOGLE GEMINI
# ============================================================

def call_google(
    model,
    messages,
):
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
            "role":
                role,

            "parts": [
                {
                    "text":
                        message["content"]
                }
            ],
        })

    payload = {
        "contents":
            contents,

        "generationConfig": {
            "maxOutputTokens":
                4096,
        },
    }

    if system_parts:
        payload[
            "systemInstruction"
        ] = {
            "parts": [
                {
                    "text":
                        "\n".join(
                            system_parts
                        )
                }
            ]
        }

    data = request_json(
        "POST",
        BASE_URLS[
            "google"
        ].rstrip("/")
        + "/models/"
        + model
        + ":generateContent",
        params={
            "key":
                API_KEYS[
                    "google"
                ]
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
            if part.get(
                "text"
            ):
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
#
# xAI
# DeepSeek
# Mistral
# NVIDIA
# Microsoft
# Meta-compatible endpoint
# Groq
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
        base
        + "/chat/completions",
        headers=provider_headers(
            provider
        ),
        payload={
            "model":
                model,

            "messages":
                messages,

            "max_tokens":
                4096,
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

    if isinstance(
        content,
        list,
    ):
        content = "\n".join(
            item.get(
                "text",
                "",
            )
            for item in content
            if isinstance(
                item,
                dict,
            )
        )

    usage = data.get(
        "usage",
        {},
    )

    return (
        content
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
# LOCAL
# ============================================================

def call_local(
    model,
    messages,
):
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
        base
        + "/chat/completions",
        headers={
            "Content-Type":
                "application/json"
        },
        payload={
            "model":
                model,

            "messages":
                messages,

            "max_tokens":
                4096,
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
# UNIFIED PROVIDER CALL
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
# CHAT FUNCTIONS
# ============================================================

def create_chat(
    user_id,
    title="New chat",
):
    chat_id = str(
        uuid.uuid4()
    )

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
        for row in reversed(
            rows
        )
    ]


# ============================================================
# USAGE
# ============================================================

def daily_message_count(
    user_id,
):
    today = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d"
    )

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

    return int(
        row[0] or 0
    )


def monthly_cost(
    user_id,
):
    month = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m"
    )

    connection = db()

    row = connection.execute(
        """
        SELECT COALESCE(
            SUM(
                estimated_cost_usd
            ),
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

    return float(
        row[0] or 0
    )


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
        input_tokens
        / 1_000_000
        * input_price
        +
        output_tokens
        / 1_000_000
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
            f"veya-agent-{index + 1:04d}",

        "role":
            f"{BASE_ROLES[index % len(BASE_ROLES)]}-"
            f"{index // len(BASE_ROLES) + 1}",

        "index":
            index + 1,
    }

    for index in range(
        5000
    )
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

    if (
        requested_provider
        and requested_model
    ):
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
            "Selected model is not "
            "currently available."
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
# API ROUTES
# ============================================================

@app.get("/api/health")
def health():
    return jsonify({
        "ok":
            True,

        "app":
            APP_NAME,

        "version":
            VERSION,

        "time":
            utc_now(),
    })


@app.get("/api/me")
def me():
    user_id = get_user_id()

    plan = get_plan(
        user_id
    )

    response = jsonify({
        "user_id":
            user_id,

        "plan":
            plan,

        "plan_info":
            PLANS[plan],

        "daily_used":
            daily_message_count(
                user_id
            ),

        "monthly_cost_usd":
            monthly_cost(
                user_id
            ),
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
    return jsonify(
        PLANS
    )


@app.get("/api/providers")
def providers():
    output = []

    for provider in API_KEYS:

        configured = (
            provider_configured(
                provider
            )
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
            "provider":
                provider,

            "configured":
                configured,

            "model_count":
                len(models),

            "models":
                models,
        })

    return jsonify(
        output
    )


@app.get("/api/models")
def models():
    user_id = get_user_id()

    plan = get_plan(
        user_id
    )

    task = request.args.get(
        "task",
        "general",
    )

    return jsonify({
        "plan":
            plan,

        "model_picker":
            PLANS[plan][
                "model_picker"
            ],

        "providers":
            PLANS[plan][
                "providers"
            ],

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
        "count":
            5000,

        "agents":
            VIRTUAL_AGENTS[:100],

        "premium_agent_roles": [
            {
                "id":
                    role_id,

                "name":
                    role_name,
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

    plan = get_plan(
        user_id
    )

    task = request.args.get(
        "task",
        "general",
    )

    return jsonify({
        "plan":
            plan,

        "agents":
            premium_catalog(
                plan,
                task,
            ),
    })


# ============================================================
# CHAT ROUTES
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
def chat_detail(
    chat_id,
):
    user_id = get_user_id()

    ensure_chat(
        user_id,
        chat_id,
    )

    return jsonify({
        "chat_id":
            chat_id,

        "messages":
            get_messages(
                chat_id
            ),
    })


# ============================================================
# MAIN CHAT
# ============================================================

@app.post("/api/chat")
def chat():
    user_id = get_user_id()

    plan = get_plan(
        user_id
    )

    plan_data = PLANS[
        plan
    ]

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
        daily_message_count(
            user_id
        )
        >= plan_data[
            "daily_messages"
        ]
    ):
        return jsonify({
            "error":
                "Daily message limit reached."
        }), 429

    chat_id = body.get(
        "chat_id"
    )

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

    task = route_task(
        text
    )

    # --------------------------------------------------------
    # FREE
    # --------------------------------------------------------

    if plan == "free":

        provider, model = (
            free_model()
        )

        agent_role = (
            "free-router"
        )

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

            provider = selected[
                "provider"
            ]

            model = selected[
                "model"
            ]

            agent_role = selected[
                "agent_id"
            ]

        except Exception as exc:

            return jsonify({
                "error":
                    str(exc)
            }), 503

    # --------------------------------------------------------
    # MONTHLY SAFETY BUDGET
    # --------------------------------------------------------

    budget = plan_data[
        "monthly_provider_budget_usd"
    ]

    if (
        budget > 0
        and
        monthly_cost(
            user_id
        ) >= budget
    ):
        return jsonify({
            "error":
                "Monthly provider budget reached."
        }), 402

    # --------------------------------------------------------
    # AGENT ROLE
    # --------------------------------------------------------

    role_name = "reasoning"

    for role_id, _ in PREMIUM_ROLES:

        if role_id in str(
            agent_role
        ):
            role_name = role_id
            break

    messages = [
        {
            "role":
                "system",

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
        "role":
            "user",

        "content":
            text,
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

        cache_clear(
            provider
        )

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

    # --------------------------------------------------------
    # SAVE USAGE
    # --------------------------------------------------------

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
        "chat_id":
            chat_id,

        "answer":
            answer,

        "provider":
            provider,

        "model":
            model,

        "agent":
            agent_role,

        "task":
            task,

        "usage": {
            "input_tokens":
                input_tokens,

            "output_tokens":
                output_tokens,

            "estimated_cost_usd":
                cost,

            "monthly_cost_usd":
                monthly_cost(
                    user_id
                ),

            "monthly_budget_usd":
                budget,
        },
    })


# ============================================================
# MODEL HEALTH TEST
# ============================================================

@app.post("/api/test-model")
def test_model():
    user_id = get_user_id()

    plan = get_plan(
        user_id
    )

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    provider = body.get(
        "provider"
    )

    model = body.get(
        "model"
    )

    if not provider or not model:
        return jsonify({
            "ok":
                False,

            "error":
                "provider and model are required.",
        }), 400

    available = premium_catalog(
        plan
    )

    allowed = any(
        item["provider"] == provider
        and
        item["model"] == model
        for item in available
    )

    if not allowed:
        return jsonify({
            "ok":
                False,

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
            "ok":
                True,

            "provider":
                provider,

            "model":
                model,

            "answer":
                answer,

            "input_tokens":
                input_tokens,

            "output_tokens":
                output_tokens,
        })

    except Exception as exc:

        return jsonify({
            "ok":
                False,

            "provider":
                provider,

            "model":
                model,

            "error":
                str(exc),
        }), 502


# ============================================================
# STRIPE
# ============================================================

STRIPE_SECRET_KEY = os.getenv(
    "STRIPE_SECRET_KEY",
    "",
).strip()

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "http://localhost:10000",
).rstrip("/")


def stripe_request(
    method,
    path,
    data=None,
):
    if not STRIPE_SECRET_KEY:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is not configured."
        )

    response = requests.request(
        method,
        "https://api.stripe.com/v1"
        + path,
        auth=(
            STRIPE_SECRET_KEY,
            "",
        ),
        data=data or {},
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            f"Stripe {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


@app.post("/api/upgrade")
def upgrade():
    user_id = get_user_id()

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    plan = body.get(
        "plan"
    )

    if plan not in (
        "core",
        "all_ai",
        "ultra",
    ):
        return jsonify({
            "error":
                "Invalid paid plan."
        }), 400

    if not STRIPE_SECRET_KEY:
        return jsonify({
            "configured":
                False,

            "message":
                "Stripe is not configured yet.",

            "plan":
                plan,
        })

    info = PLANS[
        plan
    ]

    session = stripe_request(
        "POST",
        "/checkout/sessions",
        {
            "mode":
                "subscription",

            "success_url":
                PUBLIC_BASE_URL
                + "/?payment=success",

            "cancel_url":
                PUBLIC_BASE_URL
                + "/?payment=cancelled",

            "line_items[0][price_data][currency]":
                "inr",

            "line_items[0][price_data][unit_amount]":
                str(
                    info["price_inr"]
                    * 100
                ),

            "line_items[0][price_data][product_data][name]":
                info["name"],

            "line_items[0][price_data][recurring][interval]":
                "month",

            "line_items[0][quantity]":
                "1",

            "metadata[user_id]":
                user_id,

            "metadata[plan]":
                plan,
        },
    )

    return jsonify({
        "configured":
            True,

        "checkout_url":
            session.get("url"),
    })


# ============================================================
# FRONTEND
# ============================================================

HTML = """
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Veya</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family:
        system-ui,
        -apple-system,
        "Segoe UI",
        sans-serif;
    background: #fff;
    color: #171717;
}

button,
textarea,
select {
    font: inherit;
}

button {
    cursor: pointer;
}

#app {
    height: 100vh;
    display: flex;
    overflow: hidden;
}

#sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    width: 290px;
    background: #f7f7f8;
    border-right: 1px solid #e5e5e5;
    transform: translateX(-100%);
    transition: .2s;
    z-index: 30;
    display: flex;
    flex-direction: column;
}

#sidebar.open {
    transform: translateX(0);
}

#overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,.2);
    display: none;
    z-index: 20;
}

#overlay.show {
    display: block;
}

.sidebar-top {
    padding: 18px;
}

.new-chat {
    width: 100%;
    padding: 12px;
    border: 1px solid #ddd;
    border-radius: 12px;
    background: #fff;
}

.history {
    flex: 1;
    overflow: auto;
    padding: 10px;
}

.history-item {
    padding: 11px;
    border-radius: 9px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.history-item:hover {
    background: #ececef;
}

.sidebar-bottom {
    padding: 15px;
    border-top: 1px solid #ddd;
}

#main {
    width: 100%;
    height: 100vh;
    display: flex;
    flex-direction: column;
}

.topbar {
    height: 68px;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 18px;
    border-bottom: 1px solid #eee;
}

.icon {
    border: 0;
    background: transparent;
    font-size: 25px;
    width: 42px;
    height: 42px;
    border-radius: 10px;
}

.icon:hover {
    background: #f2f2f2;
}

.brand {
    font-size: 20px;
    font-weight: 700;
}

.spacer {
    flex: 1;
}

.upgrade {
    border: 0;
    background: #9bd0ff;
    border-radius: 22px;
    padding: 10px 19px;
    font-weight: 700;
}

.chat {
    flex: 1;
    overflow: auto;
    padding: 28px 18px 150px;
}

.message {
    max-width: 850px;
    margin: 0 auto 20px;
    line-height: 1.65;
}

.user {
    background: #f3f3f3;
    padding: 13px 16px;
    border-radius: 18px;
    max-width: 700px;
    margin-left: auto;
}

.assistant {
    padding: 4px 0;
}

.tag {
    color: #777;
    font-size: 12px;
    margin-bottom: 5px;
}

.composer-wrap {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 15px;
    background:
        linear-gradient(
            transparent,
            white 25%
        );
}

.composer {
    max-width: 850px;
    margin: auto;
    border: 1px solid #d8d8d8;
    border-radius: 24px;
    padding: 9px;
    background: #fff;
}

.row {
    display: flex;
    gap: 8px;
    align-items: flex-end;
}

.plus {
    width: 42px;
    height: 42px;
    border: 0;
    background: transparent;
    font-size: 27px;
}

.send {
    width: 42px;
    height: 42px;
    border: 0;
    border-radius: 50%;
    background: #111;
    color: white;
}

textarea {
    flex: 1;
    border: 0;
    outline: 0;
    resize: none;
    min-height: 42px;
    max-height: 150px;
    padding: 11px 5px;
}

.picker {
    display: none;
    border-bottom: 1px solid #eee;
    padding: 10px;
}

.picker.open {
    display: block;
}

select {
    width: 100%;
    padding: 10px;
    border: 1px solid #ddd;
    border-radius: 12px;
}

.modal {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,.45);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 20px;
    z-index: 100;
}

.modal.show {
    display: flex;
}

.modal-box {
    width: min(1000px,100%);
    background: #fff;
    border-radius: 22px;
    padding: 24px;
    max-height: 90vh;
    overflow: auto;
}

.close {
    float: right;
    border: 0;
    background: transparent;
    font-size: 25px;
}

.plans {
    display: grid;
    grid-template-columns: repeat(3,1fr);
    gap: 15px;
}

.plan {
    border: 1px solid #ddd;
    border-radius: 18px;
    padding: 20px;
}

.plan button {
    width: 100%;
    border: 0;
    background: #111;
    color: white;
    border-radius: 12px;
    padding: 12px;
}

.price {
    font-size: 30px;
    font-weight: 800;
}

@media(max-width:700px) {

    .plans {
        grid-template-columns: 1fr;
    }

}

</style>

</head>

<body>

<div id="app">

<aside id="sidebar">

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

<div id="account">
Free plan
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
</div>

<div class="spacer">
</div>

<button
    class="upgrade"
    onclick="openUpgrade()">

Upgrade

</button>

</header>

<section
    id="chat"
    class="chat">
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

+

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

<h2>
Upgrade Veya
</h2>

<div class="plans">

<div class="plan">

<h3>
Veya Core
</h3>

<div class="price">
₹199/mo
</div>

<p>
OpenAI + Google + Anthropic
</p>

<button
    onclick="upgrade('core')">

Choose Core

</button>

</div>


<div class="plan">

<h3>
Veya All AI
</h3>

<div class="price">
₹599/mo
</div>

<p>
All configured providers
</p>

<p>
Up to 5 premium slots/provider
</p>

<button
    onclick="upgrade('all_ai')">

Choose All AI

</button>

</div>


<div class="plan">

<h3>
Veya Ultra
</h3>

<div class="price">
₹1,499/mo
</div>

<p>
All configured providers
</p>

<p>
Up to 5 premium slots/provider
</p>

<button
    onclick="upgrade('ultra')">

Choose Ultra

</button>

</div>

</div>

</div>

</div>


<script>

let currentChat = null;

let currentPlan = "free";

let models = [];


async function api(
    url,
    options = {}
) {

    const response =
        await fetch(
            url,
            {
                credentials:
                    "same-origin",

                ...options,

                headers: {
                    "Content-Type":
                        "application/json",

                    ...(options.headers || {})
                }
            }
        );

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data.error ||
            "Request failed"
        );
    }

    return data;
}


function toggleSidebar() {

    const sidebar =
        document.getElementById(
            "sidebar"
        );

    const overlay =
        document.getElementById(
            "overlay"
        );

    sidebar.classList.toggle(
        "open"
    );

    overlay.classList.toggle(
        "show",
        sidebar.classList.contains(
            "open"
        )
    );
}


function openUpgrade() {

    document
        .getElementById(
            "upgradeModal"
        )
        .classList.add(
            "show"
        );
}


function closeUpgrade() {

    document
        .getElementById(
            "upgradeModal"
        )
        .classList.remove(
            "show"
        );
}


async function loadMe() {

    const data =
        await api(
            "/api/me"
        );

    currentPlan =
        data.plan;

    document
        .getElementById(
            "account"
        )
        .textContent =
        data.plan_info.name;

    await loadModels();
}


async function loadModels() {

    const data =
        await api(
            "/api/models"
        );

    models =
        data.models || [];

    const select =
        document.getElementById(
            "modelSelect"
        );

    select.innerHTML = "";

    if (!data.model_picker) {
        return;
    }

    if (!models.length) {

        const option =
            document.createElement(
                "option"
            );

        option.textContent =
            "No live premium models configured";

        select.appendChild(
            option
        );

        return;
    }

    for (
        const item
        of models
    ) {

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

        select.appendChild(
            option
        );
    }
}


function togglePicker() {

    if (
        currentPlan === "free"
    ) {

        openUpgrade();

        return;
    }

    document
        .getElementById(
            "picker"
        )
        .classList.toggle(
            "open"
        );
}


async function loadHistory() {

    const data =
        await api(
            "/api/chats"
        );

    const history =
        document.getElementById(
            "history"
        );

    history.innerHTML = "";

    for (
        const item
        of data
    ) {

        const div =
            document.createElement(
                "div"
            );

        div.className =
            "history-item";

        div.textContent =
            item.title;

        div.onclick =
            () => openChat(
                item.id
            );

        history.appendChild(
            div
        );
    }
}


async function newChat() {

    const data =
        await api(
            "/api/chats/new",
            {
                method:
                    "POST"
            }
        );

    currentChat =
        data.chat_id;

    document
        .getElementById(
            "chat"
        )
        .innerHTML = "";

    await loadHistory();
}


async function openChat(
    id
) {

    currentChat =
        id;

    const data =
        await api(
            "/api/chats/"
            + id
        );

    const chat =
        document.getElementById(
            "chat"
        );

    chat.innerHTML = "";

    for (
        const message
        of data.messages
    ) {

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
) {

    const chat =
        document.getElementById(
            "chat"
        );

    const wrapper =
        document.createElement(
            "div"
        );

    wrapper.className =
        "message "
        +
        (
            role === "user"
            ? "user"
            : "assistant"
        );

    if (
        role === "assistant"
        && provider
        && model
    ) {

        const tag =
            document.createElement(
                "div"
            );

        tag.className =
            "tag";

        tag.textContent =
            provider.toUpperCase()
            + " · "
            + model
            + (
                agent
                ? " · "
                + agent
                : ""
            );

        wrapper.appendChild(
            tag
        );
    }

    const body =
        document.createElement(
            "div"
        );

    body.textContent =
        content;

    wrapper.appendChild(
        body
    );

    chat.appendChild(
        wrapper
    );

    chat.scrollTop =
        chat.scrollHeight;
}


function handleKey(
    event
) {

    if (
        event.key === "Enter"
        && !event.shiftKey
    ) {

        event.preventDefault();

        sendMessage();
    }
}


async function sendMessage() {

    const input =
        document.getElementById(
            "input"
        );

    const text =
        input.value.trim();

    if (!text) {
        return;
    }

    input.value = "";

    addMessage(
        "user",
        text
    );

    let selected = null;

    if (
        currentPlan !== "free"
        && models.length
    ) {

        try {

            selected =
                JSON.parse(
                    document
                        .getElementById(
                            "modelSelect"
                        )
                        .value
                );

        } catch (error) {

            selected = null;
        }
    }

    try {

        const data =
            await api(
                "/api/chat",
                {
                    method:
                        "POST",

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

    } catch (error) {

        addMessage(
            "assistant",
            "Error: "
            + error.message
        );
    }
}


async function upgrade(
    plan
) {

    try {

        const data =
            await api(
                "/api/upgrade",
                {
                    method:
                        "POST",

                    body:
                        JSON.stringify({
                            plan:
                                plan
                        })
                }
            );

        if (
            data.configured
            && data.checkout_url
        ) {

            window.location.href =
                data.checkout_url;

            return;
        }

        alert(
            data.message
            ||
            "Stripe is not configured yet."
        );

    } catch (error) {

        alert(
            error.message
        );
    }
}


async function boot() {

    try {

        await loadMe();

        await loadHistory();

    } catch (error) {

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

    # IMPORTANT:
    # This is the syntax fix for your Render error.
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