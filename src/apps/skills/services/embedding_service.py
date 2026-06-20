import json
from urllib import error, request

from django.conf import settings


class EmbeddingServiceError(ValueError):
    """Raised when text cannot be converted into a valid embedding vector."""

    pass


class OllamaEmbeddingBackend:
    """Embedding backend that calls Ollama's local HTTP API."""

    def __init__(self, model=None, base_url=None, timeout=None):
        self.model = model or settings.OLLAMA_EMBEDDING_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS

    def embed(self, text: str) -> list[float]:
        body = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/api/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = self._request_json(req)
        return self._extract_embedding(payload)

    def _request_json(self, req):
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise EmbeddingServiceError(
                f"Ollama embedding request failed: {exc}"
            ) from exc

    @staticmethod
    def _extract_embedding(payload):
        embedding = payload.get("embedding")
        if embedding is None and payload.get("embeddings"):
            embedding = payload["embeddings"][0]
        return embedding


class OpenAIEmbeddingBackend:
    """Embedding backend for OpenAI-compatible embedding APIs."""

    def __init__(self, model=None, api_key=None, timeout=None, dimensions=None):
        self.model = model or settings.OPENAI_EMBEDDING_MODEL
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", "")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS
        self.dimensions = dimensions or settings.SKILL_EMBEDDING_DIMENSIONS

    def embed(self, text: str) -> list[float]:
        if not self.api_key:
            raise EmbeddingServiceError("OPENAI_API_KEY is required for OpenAI.")

        payload = {
            "model": self.model,
            "input": text,
            "dimensions": self.dimensions,
        }
        req = request.Request(
            "https://api.openai.com/v1/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise EmbeddingServiceError(
                f"OpenAI embedding request failed: {exc}"
            ) from exc

        try:
            return response_payload["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingServiceError(
                "OpenAI embedding response did not contain an embedding."
            ) from exc


class EmbeddingService:
    """Convert text into fixed-size vectors for SkillSet semantic retrieval.

    A custom backend can be injected by tests or future local model adapters.
    Built-in provider names are ``ollama`` and ``openai``.
    """

    def __init__(self, provider=None, dimensions=None, backend=None):
        self.provider = (provider or settings.SKILL_EMBEDDING_PROVIDER).lower()
        self.dimensions = dimensions or settings.SKILL_EMBEDDING_DIMENSIONS
        self.backend = backend or self._build_backend()

    def embed(self, text: str) -> list[float]:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            raise EmbeddingServiceError("Cannot embed empty text.")

        embedding = self.backend.embed(cleaned)
        return self._validate_embedding(embedding)

    def _build_backend(self):
        if self.provider == "ollama":
            return OllamaEmbeddingBackend()
        if self.provider == "openai":
            return OpenAIEmbeddingBackend(dimensions=self.dimensions)
        raise EmbeddingServiceError(
            f"Unsupported embedding provider: {self.provider}. "
            "Inject a backend for custom local embedding models."
        )

    def _validate_embedding(self, embedding):
        if not isinstance(embedding, (list, tuple)):
            raise EmbeddingServiceError("Embedding response must be a list.")

        values = []
        for value in embedding:
            try:
                values.append(float(value))
            except (TypeError, ValueError) as exc:
                raise EmbeddingServiceError(
                    "Embedding response must contain only numbers."
                ) from exc

        if len(values) != self.dimensions:
            raise EmbeddingServiceError(
                f"Embedding dimensions must be {self.dimensions}; got {len(values)}."
            )
        return values
