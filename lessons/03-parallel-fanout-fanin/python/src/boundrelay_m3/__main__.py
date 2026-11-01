import sys
from .cli import run_cli
raise SystemExit(run_cli(sys.argv[1:]))
