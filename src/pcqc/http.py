"""Secure HTTPS defaults that work with framework-installed macOS Python."""

from __future__ import annotations

import ssl
from urllib.request import Request, urlopen

import certifi


def trusted_urlopen(request: Request, *, timeout: float):
    context = ssl.create_default_context(cafile=certifi.where())
    return urlopen(request, timeout=timeout, context=context)
