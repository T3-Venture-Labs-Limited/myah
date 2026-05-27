"""Shared library utilities for the Myah backend.

Submodules under here should be free of FastAPI app imports so they can be
consumed by both the web app and the CLI without pulling in the full
backend on cold start.
"""
