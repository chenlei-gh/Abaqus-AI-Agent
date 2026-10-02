"""Package executable entry point for python -m abaqus_ai_agent."""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
