"""Naive RAG baseline (GraphRAG course, week 1)."""

# Use the operating system's certificate store for TLS. Behind a corporate
# proxy that re-signs HTTPS traffic, Python's bundled certifi CAs fail with
# CERTIFICATE_VERIFY_FAILED; the OS store already trusts the proxy's CA.
# Verification stays ON - this only changes which CAs are trusted.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover
    pass
