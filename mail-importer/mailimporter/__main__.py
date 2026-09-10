from __future__ import annotations

import sys

_USAGE = """\
Användning: python -m mailimporter [kommando]

  (inget)        Kör importern i loop (IMAP IDLE + periodisk poll).
  list-folders   Anslut till IMAP och lista alla mappar/labels, avsluta.
  healthcheck    Kontrollera heartbeat-filen (används av Docker HEALTHCHECK).
"""


def _list_folders() -> int:
    from .config import Config
    from .imap_source import ImapSource
    from .logging_setup import setup_logging

    cfg = Config.from_env()
    setup_logging(cfg.log_level)
    src = ImapSource(cfg)
    src.connect()
    try:
        for name in src.list_folders():
            print(name)
    finally:
        src.logout()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else ""

    if cmd in ("", "run"):
        from .app import run

        run()
        return 0
    if cmd in ("list-folders", "folders"):
        return _list_folders()
    if cmd == "healthcheck":
        from .healthcheck import main as hc_main

        return hc_main()
    if cmd in ("-h", "--help", "help"):
        print(_USAGE)
        return 0

    print(f"Okänt kommando: {cmd!r}\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
