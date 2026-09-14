"""Plain stdin REPL. Useful for pipes, dumb terminals, and `--repl`."""

from agent.session import HELP, Session, Turn


def _print_event(kind, text):
    print("[%s] %s" % (kind, text))


def _show(turn: Turn):
    if turn.kind == "quit":
        raise SystemExit
    if turn.kind == "empty":
        return
    if turn.kind == "reply":
        elapsed = " (%.1fs)" % turn.elapsed_s if turn.elapsed_s is not None else ""
        print("\n%s\n%s" % (turn.text, elapsed.strip()))
        return
    print(turn.text)


def run(session: Session):
    session.subscribe(_print_event)
    print("\nType a message and press enter. %s\n" % HELP)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit
        if not line:
            continue
        _show(session.submit(line))
