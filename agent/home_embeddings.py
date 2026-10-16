"""Explicit, profile-bound OpenAI-compatible embeddings for opt-in Home recall."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import http.client
import ipaddress
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

MAX_DIMENSIONS = 3072
MAX_BATCH = 32
MAX_INPUT_CHARS = 16000
MAX_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class EmbeddingConfig:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    profile_home: str = ''
    timeout: float = 5.0
    min_similarity: float = 0.55

    @property
    def identity(self):
        # Rotating a credential does not invalidate unchanged source vectors.
        return hashlib.sha256((self.base_url + '\0' + self.model).encode()).hexdigest()


@contextmanager
def embedding_profile_scope(home):
    """Bind config and redaction to the database owner, including deferred requests."""
    from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home_token = set_hermes_home_override(home)
    secret_token = None
    try:
        secret_token = set_secret_scope(build_profile_secret_scope(Path(home)), profile_home=str(home))
        yield
    finally:
        if secret_token is not None:
            reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)


def load_embedding_config(db) -> EmbeddingConfig | None:
    """Resolve ONLY this database's profile config and explicit credential reference."""
    from agent.secret_scope import get_secret
    from hermes_cli.config import load_config_readonly

    home = Path(db.db_path).resolve().parent
    with embedding_profile_scope(home):
        memory = load_config_readonly().get('memory', {})
        cfg = memory.get('home_recall', {}) if isinstance(memory, dict) else {}
        if not isinstance(cfg, dict) or cfg.get('enabled') is not True:
            return None
        base, model = cfg.get('base_url'), cfg.get('model')
        reference = cfg.get('api_key_env', 'HOME_EMBEDDING_API_KEY')
        if not isinstance(base, str) or not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError('Set memory.home_recall.base_url and model before indexing.')
        parsed = urlsplit(base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError('Embedding base_url must have no credentials, query or fragment.')
        local = parsed.hostname == 'localhost'
        try:
            local = local or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
            raise ValueError('Embedding endpoint requires HTTPS, except loopback HTTP.')
        if not isinstance(reference, str) or (reference and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', reference)):
            raise ValueError('api_key_env must name a profile secret, not contain a credential.')
        if cfg.get('api_key'):
            raise ValueError('Use api_key_env; literal embedding credentials are unsupported.')
        key = get_secret(reference) if reference else ''
        if not key and not local:
            raise ValueError('The configured embedding credential is unavailable in this profile.')
        timeout = cfg.get('timeout_seconds', 5)
        threshold = cfg.get('min_similarity', 0.55)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout)
                or not 0.1 <= timeout <= 10):
            raise ValueError('Embedding timeout_seconds must be between 0.1 and 10.')
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold) or not 0 <= threshold <= 1):
            raise ValueError('Embedding min_similarity must be between 0 and 1.')
        return EmbeddingConfig(base.rstrip('/'), model.strip(), key or '', str(home),
                               float(timeout), float(threshold))


def normalized_vector(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_DIMENSIONS:
        raise ValueError('Invalid embedding dimensions.')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('Embedding must contain finite numbers.')
    norm = math.hypot(*value)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError('Embedding must have a finite, nonzero norm.')
    return tuple(v / norm for v in value)


def embed(config: EmbeddingConfig, texts: list[str]) -> list[tuple[float, ...]]:
    with embedding_profile_scope(config.profile_home):
        return _request_embeddings(config, texts)


def _request_embeddings(config: EmbeddingConfig, texts: list[str]) -> list[tuple[float, ...]]:
    """One request, no retries/redirects/tools; bound response, time and vector shape."""
    from agent.redact import redact_sensitive_text
    from agent.secret_scope import current_secret_scope

    if not 1 <= len(texts) <= MAX_BATCH or sum(map(len, texts)) > MAX_INPUT_CHARS:
        raise ValueError('Embedding input exceeds the bounded batch.')
    # Prefix/assignment redaction cannot recognize arbitrary provider-issued values
    # mentioned in prose. Exact profile values are also removed before egress.
    secrets = {value for value in (current_secret_scope() or {}).values()
               if isinstance(value, str) and 8 <= len(value) <= 4096}
    if config.api_key:
        secrets.add(config.api_key)
    inputs = []
    for text in texts:
        for secret in sorted(secrets, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        inputs.append(redact_sensitive_text(text, force=True, redact_url_credentials=True))
    payload = json.dumps({'model': config.model, 'input': inputs, 'encoding_format': 'float'}).encode()
    url = urlsplit(config.base_url)
    connection_cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    connection = connection_cls(url.hostname, url.port, timeout=config.timeout)
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if config.api_key:
        headers['Authorization'] = 'Bearer ' + config.api_key
    deadline = time.monotonic() + config.timeout
    try:
        connection.request('POST', url.path.rstrip('/') + '/embeddings', payload, headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Embedding provider rejected the request.')
        body = bytearray()
        while len(body) <= MAX_RESPONSE_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Embedding deadline exceeded.')
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError('Embedding response exceeds the byte limit.')
        result = json.loads(body)
        data = result.get('data') if isinstance(result, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError('Embedding response has the wrong result count.')
        ordered = {}
        for item in data:
            if not isinstance(item, dict) or type(item.get('index')) is not int:
                raise ValueError('Embedding response requires unique result indexes.')
            index = item['index']
            if index not in range(len(texts)) or index in ordered:
                raise ValueError('Embedding result indexes are invalid.')
            ordered[index] = normalized_vector(item.get('embedding'))
        vectors = [ordered[i] for i in range(len(texts))]
        if len({len(vector) for vector in vectors}) != 1:
            raise ValueError('Embedding dimensions differ within the batch.')
        return vectors
    finally:
        connection.close()
