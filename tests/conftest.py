import sys


def ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


ensure_utf8_stdio()


def pytest_configure(config) -> None:
    ensure_utf8_stdio()


def pytest_runtest_setup(item) -> None:
    ensure_utf8_stdio()
