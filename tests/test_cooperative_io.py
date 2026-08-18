"""The monkey-patching that makes this service concurrent.

flask-socketio picks eventlet as its async driver, so the server is a single
event loop. If a blocking call does not yield, it stalls that loop and the
process serves exactly one request at a time. That was the measured behaviour:

    users=1   p50   280ms
    users=2   p50   335ms
    users=4   p50   664ms
    users=8   p50  1229ms

Latency rising 1:1 with concurrency is full serialisation.

Both halves matter and they fail independently, which is why there are two
tests. eventlet.monkey_patch() rewrites the standard library, but psycopg2 is a
C extension it cannot touch -- so patching sockets alone fixes the auth call and
leaves every database query blocking, which looks like a fix and mostly is not.

None of this is visible in a functional test: the service returns correct
answers either way. It only shows up as latency under load, so it needs pinning
here or a future import reordering will quietly undo it.
"""

import subprocess
import sys
import textwrap


# config.py refuses to import without these. They are throwaway values: the
# checks below only import the module, they never open a socket or a connection.
IMPORT_ENV = {
    "PHASICON_DISABLE_S3_INIT": "1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "test",
}


def _in_subprocess(body):
    """Run a check in a clean interpreter.

    Importing app.py patches the interpreter globally and irreversibly, so this
    cannot be asserted in-process without contaminating every test that follows.
    """
    import os

    env = dict(os.environ)
    env.update(IMPORT_ENV)
    # sqlite keeps the import from needing a live Postgres; the patch under test
    # is registered by psycogreen at import, not by connecting.
    env["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    code = textwrap.dedent(body)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert proc.returncode == 0, f"check failed:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout.strip()


def test_importing_the_app_patches_sockets():
    """Importing app must leave the standard library cooperative."""
    out = _in_subprocess(
        """
        # app.py runs db.create_all() at import, so point the URI at sqlite
        # first -- the same trick the rest of the suite uses. eventlet patches
        # already-imported modules in place, so this does not weaken the check.
        import config
        config.Config.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        import app  # noqa: F401
        import socket
        print(socket.socket.__module__)
        """
    )
    assert out.startswith("eventlet"), (
        f"socket.socket comes from {out!r}, not eventlet: monkey_patch() is "
        "missing or something imported sockets before it ran"
    )


def test_importing_the_app_patches_psycopg2():
    """And the database driver, which monkey_patch() cannot reach on its own."""
    out = _in_subprocess(
        """
        import config
        config.Config.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        import app  # noqa: F401
        import psycopg2.extensions as ext
        print(ext.get_wait_callback() is not None)
        """
    )
    assert out == "True", (
        "psycopg2 has no wait callback, so queries block the event loop even "
        "though sockets are patched -- psycogreen.eventlet.patch_psycopg() is "
        "missing or ran too late"
    )


def test_the_patch_runs_before_anything_imports_sockets():
    """Order is the whole game.

    eventlet rewrites modules at import time; anything imported earlier keeps
    the blocking originals. Asserting on source rather than behaviour because
    by the time behaviour is observable the damage is already done.
    """
    src = open("app.py").read()
    patch_at = src.index("eventlet.monkey_patch()")

    before = src[:patch_at]
    stripped = []
    in_doc = False
    for line in before.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.endswith('"""'):
            in_doc = not in_doc if s.count('"""') == 1 else in_doc
            continue
        if in_doc or not s or s.startswith("#"):
            continue
        stripped.append(s)

    assert stripped == ["import eventlet"], (
        "something is imported before eventlet.monkey_patch(): "
        f"{stripped}. Those modules keep the unpatched, blocking versions."
    )
