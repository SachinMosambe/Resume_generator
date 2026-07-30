"""Canonical tech-name glossary for resume text/skill normalization.

Prevents space-repair from turning FastAPI → Fast API, EC2 → EC 2, etc.
"""
from __future__ import annotations

import re

# Broken spaced form (case-insensitive) → canonical display form.
TECH_SPACED_TO_CANONICAL: dict[str, str] = {
    "fast api": "FastAPI",
    "lang graph": "LangGraph",
    "lang chain": "LangChain",
    "lang smith": "LangSmith",
    "postgre sql": "PostgreSQL",
    "my sql": "MySQL",
    "mongo db": "MongoDB",
    "num py": "NumPy",
    "py torch": "PyTorch",
    "sci kit learn": "Scikit-learn",
    "scikit learn": "Scikit-learn",
    "node js": "Node.js",
    "next js": "Next.js",
    "react js": "React",
    "vue js": "Vue",
    "open ai": "OpenAI",
    "open router": "OpenRouter",
    "web sockets": "WebSockets",
    "web socket": "WebSocket",
    "ec 2": "EC2",
    "s 3": "S3",
    "ci cd": "CI/CD",
    "c i / c d": "CI/CD",
    "rest api": "REST API",
    "graph ql": "GraphQL",
    "type script": "TypeScript",
    "java script": "JavaScript",
    "power bi": "Power BI",
    "git hub": "GitHub",
    "git lab": "GitLab",
    "cloud watch": "CloudWatch",
    "dynamo db": "DynamoDB",
    "elastic search": "Elasticsearch",
    "big query": "BigQuery",
    "xg boost": "XGBoost",
    "ml flow": "MLflow",
    "hugging face": "Hugging Face",
    "model context protocol": "Model Context Protocol",
    "retrieval augmented generation": "Retrieval-Augmented Generation",
}

# Compact lowercase → canonical (also used by skill normalizer).
TECH_COMPACT_TO_CANONICAL: dict[str, str] = {
    "fastapi": "FastAPI",
    "langgraph": "LangGraph",
    "langchain": "LangChain",
    "langsmith": "LangSmith",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "numpy": "NumPy",
    "pytorch": "PyTorch",
    "scikit-learn": "Scikit-learn",
    "sklearn": "Scikit-learn",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "websockets": "WebSockets",
    "websocket": "WebSocket",
    "ec2": "EC2",
    "s3": "S3",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "graphql": "GraphQL",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "powerbi": "Power BI",
    "github": "GitHub",
    "gitlab": "GitLab",
    "cloudwatch": "CloudWatch",
    "dynamodb": "DynamoDB",
    "elasticsearch": "Elasticsearch",
    "bigquery": "BigQuery",
    "xgboost": "XGBoost",
    "mlflow": "MLflow",
    "huggingface": "Hugging Face",
    "aws": "AWS",
    "gcp": "GCP",
    "sql": "SQL",
    "html": "HTML",
    "css": "CSS",
    "api": "API",
    "rest api": "REST API",
    "spring boot": "Spring Boot",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "redis": "Redis",
    "celery": "Celery",
    "faiss": "FAISS",
    "qdrant": "Qdrant",
    "pandas": "Pandas",
    "react": "React",
    "angular": "Angular",
    "vue": "Vue",
    "django": "Django",
    "flask": "Flask",
    "python": "Python",
    "java": "Java",
    "git": "Git",
    "jenkins": "Jenkins",
    "terraform": "Terraform",
    "kafka": "Kafka",
    "spark": "Spark",
    # Keep as Bedrock — restore_tech_names adds a single AWS prefix idempotently.
    "bedrock": "Bedrock",
    "mcp": "MCP",
    "rag": "RAG",
    "llm": "LLM",
    "llms": "LLMs",
    "nlp": "NLP",
}

# Tokens that must never be camelCase/digit-split (protect during space repair).
PROTECTED_TECH_TOKENS: tuple[str, ...] = tuple(
    sorted(
        {
            "FastAPI",
            "LangGraph",
            "LangChain",
            "LangSmith",
            "PostgreSQL",
            "MySQL",
            "MongoDB",
            "NumPy",
            "PyTorch",
            "OpenAI",
            "OpenRouter",
            "WebSockets",
            "WebSocket",
            "TypeScript",
            "JavaScript",
            "GraphQL",
            "GitHub",
            "GitLab",
            "CloudWatch",
            "DynamoDB",
            "Elasticsearch",
            "BigQuery",
            "XGBoost",
            "MLflow",
            "Node.js",
            "Next.js",
            "EC2",
            "S3",
            "FAISS",
            "Qdrant",
            "Scikit-learn",
            "HuggingFace",
            "Bedrock",
            "LLM",
            "LLMs",
            "RAG",
            "MCP",
            "NLP",
        },
        key=len,
        reverse=True,
    )
)


def restore_tech_names(text: str) -> str:
    """Fix spaced/broken tech names in free text (skills, bullets, summary)."""
    if not text:
        return text
    out = str(text)
    # Longest spaced patterns first.
    for broken, canon in sorted(TECH_SPACED_TO_CANONICAL.items(), key=lambda x: len(x[0]), reverse=True):
        out = re.sub(rf"(?i)\b{re.escape(broken)}\b", canon, out)
    # Compact forms that may appear after bad splits were partially fixed.
    for compact, canon in TECH_COMPACT_TO_CANONICAL.items():
        out = re.sub(rf"(?i)\b{re.escape(compact)}\b", canon, out)
    # One AWS prefix for Bedrock; never AWS AWS AWS Bedrock.
    out = re.sub(r"(?i)(?<!\bAWS\s)\bBedrock\b", "AWS Bedrock", out)
    out = re.sub(r"(?i)\b(?:AWS\s+){2,}(Bedrock)\b", r"AWS \1", out)
    out = re.sub(r"(?i)\b(?:AWS\s+){2,}", "AWS ", out)
    # AWS(EC 2, S 3 → AWS(EC2, S3
    out = re.sub(r"(?i)\bEC\s*2\b", "EC2", out)
    out = re.sub(r"(?i)\bS\s*3\b", "S3", out)
    out = re.sub(r"(?i)\bCI\s*/\s*CD\b", "CI/CD", out)
    out = re.sub(r"(?i)\bCI\s+CD\b", "CI/CD", out)
    return out


def normalize_skill_token(skill: str) -> str:
    """Normalize a single skill/tool token to canonical casing."""
    raw = re.sub(r"\s+", " ", str(skill or "").strip(" .,:;|/"))
    if not raw:
        return ""
    fixed = restore_tech_names(raw)
    key = fixed.casefold()
    if key in TECH_COMPACT_TO_CANONICAL:
        return TECH_COMPACT_TO_CANONICAL[key]
    if key in TECH_SPACED_TO_CANONICAL:
        return TECH_SPACED_TO_CANONICAL[key]
    return fixed


def protect_tech_and_emails(text: str) -> tuple[str, dict[str, str]]:
    """
    Replace emails and known tech tokens with placeholders before aggressive space repair.
    Returns (protected_text, restore_map).
    """
    mapping: dict[str, str] = {}
    out = text or ""
    counter = 0

    def _stash(value: str) -> str:
        nonlocal counter
        key = f"⟦KEEP{counter}⟧"
        counter += 1
        mapping[key] = value
        return key

    # Emails first.
    out = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        lambda m: _stash(m.group(0)),
        out,
    )
    # URLs.
    out = re.sub(
        r"https?://[^\s<>\"']+",
        lambda m: _stash(m.group(0)),
        out,
        flags=re.IGNORECASE,
    )
    # Known tech tokens (longest first).
    for token in PROTECTED_TECH_TOKENS:
        out = re.sub(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", lambda m, t=token: _stash(t), out)

    return out, mapping


def unprotect_placeholders(text: str, mapping: dict[str, str]) -> str:
    out = text or ""
    for key, value in mapping.items():
        out = out.replace(key, value)
    return out
