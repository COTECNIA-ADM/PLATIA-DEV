"""Cabeceras de seguridad OWASP en toda respuesta de la API (Capítulo 6)."""

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def apply_security_headers(response):
    h = response.headers
    # La API solo devuelve JSON: no necesita cargar nada
    h.setdefault("Content-Security-Policy", API_CSP)
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    # Los navegadores ignoran HSTS por HTTP; en producción con TLS fuerza HTTPS un año
    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if response.mimetype == "application/json":
        h["Cache-Control"] = "no-store"
    return response
