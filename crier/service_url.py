"""Canonical HTTP base URL for direct relays and the Supabase gateway."""
from urllib.parse import urlsplit

SERVICE_PATHS = ('', '/', '/functions/v1/crier', '/functions/v1/crier/')


def service_url(value, *, allow_local=False):
    value = value.strip()
    parsed = urlsplit(value)
    local = allow_local and parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if ((parsed.scheme != 'https' and not local) or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or '?' in value or '#' in value or parsed.path not in SERVICE_PATHS
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
        raise ValueError('Use an HTTPS service address or its /functions/v1/crier gateway base.')
    return value.rstrip('/')
