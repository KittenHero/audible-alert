import asyncio
import logging
import sys

from repl import repl

if __name__ == '__main__':
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    asyncio.run(repl())
