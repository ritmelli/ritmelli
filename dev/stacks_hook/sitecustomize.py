import faulthandler
import os
import socket
import sys
import threading

MARK = "---- the server's stacks, asked by the test"


def answer(port):
    with socket.create_connection(("127.0.0.1", port)) as asker:
        while asker.recv(1):
            print(MARK, file=sys.stderr, flush=True)
            faulthandler.dump_traceback(all_threads=True)


if os.environ.get("RITMELLI_STACKS_PORT"):
    threading.Thread(target=answer, args=(int(os.environ["RITMELLI_STACKS_PORT"]),), daemon=True,
                     name="stacks-on-demand").start()
