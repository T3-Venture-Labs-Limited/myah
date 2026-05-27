"""CLI-specific lib utilities. Imported by the CLI command modules.

Do NOT import myah.main from here — would pull in the FastAPI app and
break the < 200 ms CLI cold-start target.
"""
