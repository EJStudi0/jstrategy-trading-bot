"""Permite ejecutar `python -m centinela ...`."""

import sys

from .cli import main

sys.exit(main())
