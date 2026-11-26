"""Tests dev/so_mock.py, the lock that keeps the dev/ tools on a --mock server and off the real Ritmelli (port 8799,
which plays in the game of whoever is playing). Standard library only, and never a connection to port 8799: before
anything else, socket.connect is wrapped so a connection to that port is refused and counted, and the test fails if
the count is not zero at the end. The fake servers listen on ephemeral ports of 127.0.0.1, and the child that sobe
starts is a fake Popen: nothing is run.

- free_port never returns the app port, even when the system hands it out (a fake socket that does);
- confere and sobe refuse the app port before any connection, and sobe refuses a port where someone already answers
  (one this test holds) before the Popen;
- the /api/state that is not a --mock is refused: no marker, the marker that isn't true, a redirect (not followed,
  even to the app port), a 401 that isn't the pairing one, another status, a body that isn't JSON; the 200 and the
  pairing 401 with the marker pass;
- confere_pagina and libera_ou_barra turn away the page or document from another origin;
- the Filho sends nothing (not even /api/shutdown) once its child has exited or its port stops answering as a --mock,
  and then only kills its own handle;
- sobe returns the Filho only with the child alive and the marker, and kills the child when that doesn't happen;
- sai_se_o_app_ligado exits when the app port answers (that answer is faked: nothing connects to it).

    python dev/testa_so_mock.py

Exits 1 if something fails."""
import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

APP_PORT = 8799
attempts = []  # the connections to the app port that the guard below turned away
_connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex


def _to_app(address):
    return isinstance(address, tuple) and len(address) >= 2 and address[1] == APP_PORT


def _guarded_connect(self, address):
    if _to_app(address):
        attempts.append(address)
        raise ConnectionRefusedError(f"testa_so_mock: no connection to port {APP_PORT}")
    return _connect(self, address)


def _guarded_connect_ex(self, address):
    if _to_app(address):
        attempts.append(address)
        return 111  # ECONNREFUSED
    return _connect_ex(self, address)


socket.socket.connect, socket.socket.connect_ex = _guarded_connect, _guarded_connect_ex

sys.path.insert(0, str(Path(__file__).resolve().parent))
import so_mock  # noqa: E402

failures = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        failures.append(msg)


def refused(call, *args, **kwargs):
    """The Recusa message of call(*args), or None when it didn't refuse."""
    try:
        call(*args, **kwargs)
    except so_mock.Recusa as ex:
        return str(ex)
    return None


class FakeServer:
    """An HTTP server on an ephemeral port of 127.0.0.1 that answers every request with the current (status, headers,
    body), and keeps the (method, path) of each request."""

    def __init__(self, port=0):
        self.answer = (200, {}, b"{}")
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _reply(self):
                outer.requests.append((self.command, self.path))
                status, headers, body = outer.answer
                self.send_response(status)
                for k, v in {"Content-Type": "application/json", **headers}.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _reply

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def says(self, status, body, headers=None):
        self.answer = (status, headers or {}, body if isinstance(body, bytes) else json.dumps(body).encode())
        return self

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeChild:
    """The Popen of a child that runs nothing: poll() says whether it is alive; kill() ends it."""

    def __init__(self, alive=True):
        self.returncode = None if alive else 1
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def app_port():
    print("--- the app port is never used")
    check(so_mock.PORTA_DO_APP == APP_PORT, f"so_mock's app port is {APP_PORT} (pastas.PORTA)")

    class HandsOutTheAppPort:
        """The system socket handing out port 8799 on the first bind, then another one."""
        ports = iter([APP_PORT, 54321])
        binds = []

        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def bind(self, address):
            self.binds.append(address)
            self.port = next(self.ports)

        def getsockname(self):
            return ("127.0.0.1", self.port)

    with mock.patch.object(so_mock.socket, "socket", HandsOutTheAppPort):
        port = so_mock.free_port()
    check(port == 54321 and len(HandsOutTheAppPort.binds) == 2,
          f"free_port with the system handing out {APP_PORT}: binds again and returns another port ({port})")
    port = so_mock.free_port()
    check(port != APP_PORT and 0 < port < 65536, f"free_port, for real: an ephemeral port ({port})")

    for url in (f"http://127.0.0.1:{APP_PORT}/", f"http://localhost:{APP_PORT}/t/ritmelli/",
                f"http://[::1]:{APP_PORT}/"):
        msg = refused(so_mock.confere, url)
        check(msg is not None and str(APP_PORT) in msg, f"confere {url}: refused by the port ({msg})")
    with mock.patch.object(so_mock.subprocess, "Popen") as popen:
        msg = refused(so_mock.sobe, ["server.py", "--mock"], APP_PORT)
    check(msg is not None and not popen.called, f"sobe on port {APP_PORT}: refused before the Popen ({msg})")

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        with mock.patch.object(so_mock.subprocess, "Popen") as popen:
            msg = refused(so_mock.sobe, ["server.py", "--mock"], port)
        check(msg is not None and "responde" in msg and not popen.called,
              f"sobe on a port where someone answers ({port}, held by this test): refused before the Popen ({msg})")

    with mock.patch.object(so_mock, "porta_responde", side_effect=lambda p, *a, **k: p == APP_PORT) as answers:
        try:
            so_mock.sai_se_o_app_ligado("this measurement")
            out = None
        except SystemExit as ex:
            out = str(ex.code)
    check(out is not None and str(APP_PORT) in out and answers.call_args.args[0] == APP_PORT,
          f"sai_se_o_app_ligado with the app port answering (faked): exits ({out})")


def state(srv):
    print("--- only a --mock passes (fake servers on ephemeral ports)")
    cases = (
        ("200 without the marker", 200, {"ok": True}, {}, "mock"),
        ("200 with a marker that isn't true", 200, {"mock": "true"}, {}, "mock"),
        ("302 to the app port", 302, {"mock": True}, {"Location": f"http://127.0.0.1:{APP_PORT}/api/state"},
         "redireciona"),
        ("307 to another origin", 307, {"mock": True}, {"Location": "http://127.0.0.2:1/api/state"}, "redireciona"),
        ("401 with the marker but without parear", 401, {"mock": True}, {}, "401"),
        ("401 without the marker", 401, {"parear": True}, {}, "mock"),
        ("500 with the marker", 500, {"mock": True}, {}, "500"),
        ("200 that isn't JSON", 200, b"<html>mock</html>", {"Content-Type": "text/html"}, "mock"),
        ("200 with a JSON list", 200, [{"mock": True}], {}, "mock"),
    )
    for name, status, body, headers, word in cases:
        srv.says(status, body, headers)
        n = len(srv.requests)
        msg = refused(so_mock.confere, srv.base + "/t/ritmelli/")
        check(msg is not None and word in msg and srv.requests[n:] == [("GET", "/api/state")],
              f"{name}: refused after one GET /api/state ({msg})")
    srv.says(200, {"mock": True, "status": "idle"})
    check(refused(so_mock.confere, srv.base + "/t/ritmelli/") is None
          and so_mock.confere(srv.base + "/") == srv.base, "the 200 with \"mock\": true passes")
    srv.says(401, {"ok": False, "parear": True, "mock": True})
    check(so_mock.confere(srv.base + "/") == srv.base, "the pairing 401 with \"mock\": true passes")

    print("--- the page and its documents stay on the --mock's origin")
    srv.says(200, {"mock": True})
    other = f"http://127.0.0.1:{so_mock.free_port()}"
    check(so_mock.confere_pagina(srv.base + "/", srv.base) == srv.base, "confere_pagina on the same origin passes")
    msg = refused(so_mock.confere_pagina, srv.base + "/", other)
    check(msg is not None, f"confere_pagina with the page gone to another origin: refused ({msg})")
    msg = refused(so_mock.confere, f"http://127.0.0.1:{so_mock.free_port()}/")
    check(msg is not None, f"confere on a port nobody answers: refused ({msg})")
    for url in ("https://127.0.0.1:8801/", "http://127.0.0.1/", "file:///C:/x.html", "http://127.0.0.1:x/"):
        check(refused(so_mock.origem, url) is not None, f"origem {url}: refused (a --mock is http://host:port)")
    pedido = {"requestId": "1", "request": {"url": srv.base + "/t/ritmelli/index.html"}}
    check(so_mock.libera_ou_barra(pedido, srv.base) == ("Fetch.continueRequest", {"requestId": "1"}),
          "libera_ou_barra: the document of the same origin goes on")
    for url in (f"http://127.0.0.1:{APP_PORT}/", "http://localhost:" + str(srv.port) + "/", "about:blank"):
        pedido = {"requestId": "2", "request": {"url": url}}
        check(so_mock.libera_ou_barra(pedido, srv.base)[0] == "Fetch.failRequest",
              f"libera_ou_barra: the document of {url} is blocked")


def child(srv):
    print("--- the Filho talks only to its live child that answers as a --mock")
    srv.says(200, {"mock": True})
    f = so_mock.Filho(FakeChild(), srv.port)
    check(f.api("GET", "/api/state") == {"mock": True}, "alive and a --mock: the request goes")
    dead = FakeChild(alive=False)
    f = so_mock.Filho(dead, srv.port)
    n = len(srv.requests)
    f.encerra(espera=1)
    check(srv.requests[n:] == [] and dead.returncode == 1,
          f"the child already exited: encerra sends nothing, not even /api/shutdown ({srv.requests[n:]})")
    srv.says(200, {"ok": True})
    alive = FakeChild()
    f = so_mock.Filho(alive, srv.port)
    n = len(srv.requests)
    f.encerra(espera=1)
    check(srv.requests[n:] == [("GET", "/api/state")] and alive.killed,
          f"the port stopped answering as a --mock: no /api/shutdown, only the child's handle ({srv.requests[n:]})")
    srv.says(200, {"mock": True})
    alive = FakeChild()
    f = so_mock.Filho(alive, srv.port)
    n = len(srv.requests)
    f.encerra(espera=1)
    check(("POST", "/api/shutdown") in srv.requests[n:], "a live --mock child: encerra sends the /api/shutdown")


def starts():
    print("--- sobe returns the Filho only with the child alive and the marker")
    started = []

    children = []

    def popen_that_serves(body, alive=True):
        """A fake Popen whose 'child' is a fake server on the port sobe was given."""
        def popen(cmd, **kw):
            srv = FakeServer(port).says(200, body)
            started.append(srv)
            children.append(FakeChild(alive))
            return children[-1]
        return popen

    port = so_mock.free_port()
    with mock.patch.object(so_mock.subprocess, "Popen", side_effect=popen_that_serves({"mock": True})):
        f = so_mock.sobe(["server.py", "--mock"], port, limite=5)
    check(isinstance(f, so_mock.Filho) and f.porta == port and f.srv.poll() is None,
          f"the child alive and answering as a --mock: sobe returns it (port {port})")
    started.pop().close()

    port = so_mock.free_port()
    with mock.patch.object(so_mock.subprocess, "Popen", side_effect=popen_that_serves({"ok": True})):
        msg = refused(so_mock.sobe, ["server.py", "--mock"], port, limite=5)
    srv = started.pop()
    check(msg is not None and "mock" in msg and children[-1].killed,
          f"the child answering without the marker: refused, and its handle killed ({msg})")
    srv.close()

    port = so_mock.free_port()
    children.clear()
    with mock.patch.object(so_mock.subprocess, "Popen", side_effect=lambda cmd, **kw: children.append(FakeChild())
                           or children[-1]):
        msg = refused(so_mock.sobe, ["server.py", "--mock"], port, limite=0.5)
    check(msg is not None and children and children[0].killed,
          f"the child that never answers: refused at the limit, and its handle killed ({msg})")

    with mock.patch.object(so_mock.subprocess, "Popen", return_value=FakeChild(alive=False)):
        msg = refused(so_mock.sobe, ["server.py", "--mock"], so_mock.free_port(), limite=5)
    check(msg is not None and "saiu" in msg, f"the child that exits while starting: refused ({msg})")

    class DiesOnceAsked(FakeChild):
        """Alive until the first poll after someone answered on its port: the port taken by another --mock, and
        the child exiting for not getting it."""
        polls = 0

        def poll(self):
            self.polls += 1
            if self.polls == 2:
                self.returncode = 1
            return self.returncode

    port = so_mock.free_port()
    with mock.patch.object(so_mock.subprocess, "Popen",
                           side_effect=lambda cmd, **kw: started.append(FakeServer(port).says(200, {"mock": True}))
                           or DiesOnceAsked()):
        msg = refused(so_mock.sobe, ["server.py", "--mock"], port, limite=5)
    started.pop().close()
    check(msg is not None and "saiu" in msg,
          f"another --mock answering on the port while the child exits: refused, the answer isn't the child's ({msg})")


HOLDS = "import sys\nheld = open(sys.argv[1], 'rb')\nprint('ready', flush=True)\nsys.stdin.read()"
STARTS = ("import subprocess, sys\np = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]],"
          " stdout=subprocess.PIPE)\nprint(p.stdout.readline().decode().strip(), flush=True)\n")


def the_tree():
    print("--- mata ends every process the child started, through its job")
    for title, tail in (("waits for it", "p.wait()"), ("exits and leaves it", "")):
        with tempfile.TemporaryDirectory(prefix="ritmelli-so-mock-") as folder:
            held = os.path.join(folder, "held.wav")
            open(held, "wb").close()
            parent, job = so_mock.start_job([sys.executable, "-c", STARTS + tail, HOLDS, held],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                ready = parent.stdout.readline().decode().strip()
                if not tail:
                    parent.wait()
                so_mock.Filho(parent, 0, job).mata()
                try:
                    os.remove(held)
                    gone = True
                except PermissionError:
                    gone = False
            finally:
                parent.stdin.close()
                parent.stdout.close()
            check(ready == "ready" and gone, f"a child that {title} its own child holding a file: after mata the "
                                             f"file can go ({ready!r}, {gone})")
    parent, job = so_mock.start_job([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    f = so_mock.Filho(parent, so_mock.free_port(), job)
    f.mata()
    again = refused(f.encerra, espera=1)
    parent.stdin.close()
    check(parent.returncode is not None and again is None,
          f"mata and then encerra, as the compara does on a failed setup: the second stop raises nothing ({again})")
    made = []
    real = subprocess.Popen
    with mock.patch.object(so_mock.subprocess, "Popen", side_effect=lambda *a, **k: made.append(real(*a, **k)) or made[-1]), \
            mock.patch.object(so_mock, "_resume", return_value=0xC0000001):
        msg = refused(so_mock.start_job, [sys.executable, "-c", "pass"])
    check(msg is not None and made and made[0].poll() is not None,
          f"a child that cannot be resumed is not left suspended: start_job ends it and says why ({msg})")
    made.clear()

    def interrupted(*a, **k):
        made.append(real(*a, **k))
        signal.raise_signal(signal.SIGINT)
        return made[-1]

    with mock.patch.object(so_mock.subprocess, "Popen", side_effect=interrupted):
        try:
            so_mock.start_job([sys.executable, "-c", "pass"])
            raised = None
        except KeyboardInterrupt as ex:
            raised = ex
    check(isinstance(raised, KeyboardInterrupt) and made and made[0].poll() is not None,
          f"a Ctrl+C right after the Popen: the child is ended, not left suspended, and the Ctrl+C goes on ({raised!r})")
    restored = [signal.getsignal(signal.SIGINT) is signal.default_int_handler]
    with mock.patch.object(so_mock, "_Job", side_effect=so_mock.Recusa("no job")):
        refused(so_mock.start_job, [sys.executable, "-c", "pass"])
    restored.append(signal.getsignal(signal.SIGINT) is signal.default_int_handler)
    check(all(restored), f"start_job gives the Ctrl+C back as it was, after a stop and after a job that failed ({restored})")
    with tempfile.TemporaryDirectory(prefix="ritmelli-so-mock-") as folder:
        held = os.path.join(folder, "held.wav")
        open(held, "wb").close()
        made.clear()
        resume = so_mock._resume

        def resumed_then_interrupted(handle):
            status = resume(handle)
            made[-1].stdout.readline()
            signal.raise_signal(signal.SIGINT)
            return status

        with mock.patch.object(so_mock.subprocess, "Popen", side_effect=lambda *a, **k: made.append(real(*a, **k))
                               or made[-1]), mock.patch.object(so_mock, "_resume", resumed_then_interrupted):
            try:
                so_mock.start_job([sys.executable, "-c", STARTS + "p.wait()", HOLDS, held],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                raised = None
            except KeyboardInterrupt as ex:
                raised = ex
        try:
            os.remove(held)
            gone = True
        except PermissionError:
            gone = False
        made[0].stdin.close()
        made[0].stdout.close()
    check(isinstance(raised, KeyboardInterrupt) and gone,
          f"a Ctrl+C once the child runs and its own child holds a file: start_job ends the whole job, the file can go, "
          f"and the Ctrl+C goes on ({raised!r}, {gone})")
    started, filho = [], so_mock.Filho

    def filho_then_interrupted(*a, **k):
        started.append(filho(*a, **k))
        signal.raise_signal(signal.SIGINT)
        return started[-1]

    with mock.patch.object(so_mock, "Filho", filho_then_interrupted):
        try:
            so_mock.sobe([sys.executable, "-c", "import time; time.sleep(60)"], so_mock.free_port(), limite=5)
            raised = None
        except KeyboardInterrupt as ex:
            raised = ex
    check(isinstance(raised, KeyboardInterrupt) and started and started[0].srv.poll() is not None,
          f"a Ctrl+C once start_job has given the child back: sobe ends it, and the Ctrl+C goes on ({raised!r})")
    parent, job = so_mock.start_job([sys.executable, "-c", STARTS + "p.wait()", HOLDS, os.devnull],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    parent.stdout.readline()
    pids = job.pids(1)
    so_mock.Filho(parent, 0, job).mata()
    parent.stdin.close()
    parent.stdout.close()
    check(len(pids) == 2, f"the job lists all its processes even past the first buffer ({len(pids)} of 2)")
    parent, job = so_mock.start_job([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    with mock.patch.object(job.k, "OpenProcess", return_value=0):
        unsure = refused(so_mock.Filho(parent, 0, job).mata)
    again = refused(so_mock.Filho(parent, 0, job).mata)
    parent.stdin.close()
    check(unsure is not None and again == unsure,
          f"a process of the job that cannot be opened: the stop is not taken as done, and a second stop says the "
          f"same ({unsure}; {again})")
    parent, job = so_mock.start_job([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    opened, closed = [], set()
    open_process, close_handle, pids = job.k.OpenProcess, job.k.CloseHandle, job.pids

    def opening(*a):
        opened.append(open_process(*a))
        return opened[-1]

    def closing(handle):
        closed.add(handle.value)
        return close_handle(handle)

    with mock.patch.object(job.k, "OpenProcess", side_effect=opening), \
            mock.patch.object(job.k, "CloseHandle", side_effect=closing), \
            mock.patch.object(job, "pids", side_effect=[pids(), so_mock.Recusa("second list")]):
        failed = refused(so_mock.Filho(parent, 0, job).mata)
    parent.stdin.close()
    parent.wait(10)
    check(failed is not None and opened and set(opened) <= closed,
          f"the second list of the job fails: the stop refuses and closes every handle it opened ({failed}; "
          f"{len(opened)} opened, {len(set(opened) - closed)} left open)")


app_port()
the_tree()
fake = FakeServer()
try:
    state(fake)
    child(fake)
finally:
    fake.close()
starts()
check(not attempts, f"no connection went to port {APP_PORT} ({attempts})")

print("\nFAILED: " + "; ".join(failures) if failures else "\nall ok")
sys.exit(1 if failures else 0)
