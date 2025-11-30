"""
Main entry point for running cs2arb as a module.

Allows running with: python -m cs2arb [command]
"""

from .cli.main import app

if __name__ == "__main__":
    app()

