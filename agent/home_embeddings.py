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
import threading
import time
from urllib.parse import urlsplit

MAX_DIMENSIONS = 3072
MAX_BATCH = 32
MAX_INPUT_CHARS = 16000
MAX_RESPONSE_BYTES = 2_000_000
BACKOFF_SECONDS = (15, 30, 60, 120, 300, 600)
_HEALTH: dict[str, dict] = {}
_HEALTH_LOCK = threading.Lock()


class EmbeddingUnavailable(OSError):
    """The endpoint failed recently; skip it until the backoff expires instead of waiting."""


@dataclass(frozen=True)
class EmbeddingConfig:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    profile_home: str = ''
    timeout: float = 5.0
    min_similarity: float = 0.55
    auto_index: bool = False

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
        # Automatic indexing uploads history after every turn: it needs its own explicit opt-in,
        # never a retroactive reading of an existing ``enabled: true``.
        auto_index = cfg.get('auto_index', False)
        if not isinstance(auto_index, bool):
            raise ValueError('Embedding auto_index must be true or false.')
        return EmbeddingConfig(base.rstrip('/'), model.strip(), key or '', str(home),
                               float(timeout), float(threshold), auto_index)


def normalized_vector(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_DIMENSIONS:
        raise ValueError('Invalid embedding dimensions.')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('Embedding must contain finite numbers.')
    norm = math.hypot(*value)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError('Embedding must have a finite, nonzero norm.')
    return tuple(v / norm for v in value)


def _health_key(config):
    # Transport health is per profile and credential; the vector-space identity is shared.
    credential = hashlib.sha256(config.api_key.encode()).hexdigest()
    return hashlib.sha256('\0'.join((config.profile_home, config.identity, credential)).encode()).hexdigest()


def embedding_health(config: EmbeddingConfig) -> dict:
    """Process-local endpoint health: last success, consecutive failures and retry time."""
    with _HEALTH_LOCK:
        return dict(_HEALTH.get(_health_key(config), {}))


def reset_embedding_health(config: EmbeddingConfig) -> None:
    """An explicit user request retries immediately instead of waiting out the backoff."""
    with _HEALTH_LOCK:
        _HEALTH.pop(_health_key(config), None)


def _reserve(config):
    """Admit a request, or refuse while backing off. After a failure, exactly one caller
    probes the endpoint; concurrent optional callers fall back to keyword recall."""
    with _HEALTH_LOCK:
        health = _HEALTH.get(_health_key(config))
        if health is None or not health['failures']:
            return
        if time.time() < health['retry_at'] or health.get('probing'):
            raise EmbeddingUnavailable('Embedding endpoint is backing off after a recent failure.')
        health['probing'] = True


def _record_health(config, error=None):
    now = time.time()
    with _HEALTH_LOCK:
        health = _HEALTH.setdefault(_health_key(config), {'failures': 0})
        health['probing'] = False
        if error is None:
            health.update(failures=0, retry_at=0.0, last_ok=now, last_error=None)
            return
        failures = health['failures'] + 1
        delay = BACKOFF_SECONDS[min(failures, len(BACKOFF_SECONDS)) - 1]
        health.update(failures=failures, retry_at=now + delay, last_error=type(error).__name__)


def _release_probe(config):
    with _HEALTH_LOCK:
        health = _HEALTH.get(_health_key(config))
        if health is not None:
            health['probing'] = False


def embed(config: EmbeddingConfig, texts: list[str]) -> list[tuple[float, ...]]:
    """One bounded request. A failing endpoint backs off (15 s doubling to 10 min) so a hung
    provider costs at most one timeout per window, not one per turn. Transport failures and
    slow rejections back off; a fast malformed or rejected response is retried next time."""
    _reserve(config)
    try:  # Immediately after reserving: every exit path below releases or records the probe.
        started = time.monotonic()
        with embedding_profile_scope(config.profile_home):
            vectors = _request_embeddings(config, texts)
    except _BudgetError:
        _release_probe(config)
        raise
    except (OSError, http.client.HTTPException) as exc:
        _record_health(config, exc)
        raise
    except ValueError as exc:
        if time.monotonic() - started >= config.timeout / 2:
            _record_health(config, exc)
        else:
            _release_probe(config)
        raise
    except BaseException:
        _release_probe(config)  # Never leave the recovery slot reserved (scope entry/exit included).
        raise
    _record_health(config)
    return vectors


class _BudgetError(ValueError):
    """A local input-budget rejection; says nothing about endpoint health."""


def _redact_inputs(config, texts):
    from agent.redact import redact_sensitive_text
    from agent.secret_scope import current_secret_scope

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
    return inputs


def embedding_input_sizes(config, texts):
    """Budget both original and redacted inputs without sending any provider request."""
    with embedding_profile_scope(config.profile_home):
        return [max(len(raw), len(redacted))
                for raw, redacted in zip(texts, _redact_inputs(config, texts))]


def _request_embeddings(config: EmbeddingConfig, texts: list[str]) -> list[tuple[float, ...]]:
    """One request, no retries/redirects/tools; bound response, time and vector shape."""
    if not 1 <= len(texts) <= MAX_BATCH or sum(map(len, texts)) > MAX_INPUT_CHARS:
        raise _BudgetError('Embedding input exceeds the bounded batch.')
    inputs = _redact_inputs(config, texts)
    # Redaction markers can be longer than the value they replace. The egress
    # budget applies to the actual request, including that expansion.
    if sum(map(len, inputs)) > MAX_INPUT_CHARS:
        raise _BudgetError('Redacted embedding input exceeds the bounded batch.')
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
