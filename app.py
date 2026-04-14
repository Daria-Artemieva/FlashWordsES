"""
Vercel Flask entrypoint.

Vercel detects Flask by looking for a module-level variable named `app`
in one of the supported entrypoint files (e.g. app.py).
"""

from spanish_app.app import app  # noqa: F401

