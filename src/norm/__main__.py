"""Enable `python -m norm`, mirroring the `norm` console-script entry point."""

import sys

from norm.cli import main

if __name__ == "__main__":
    sys.exit(main())
