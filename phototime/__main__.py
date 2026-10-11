"""`python3 -m phototime` の入口。"""

import sys

from phototime.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
