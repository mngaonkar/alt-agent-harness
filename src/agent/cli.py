"""Process entry: boot a Session, then hand it to an interface."""

import argparse
import sys

from agent import setup
from agent.runtime import boot, default_workspace
from agent.session import Session, Turn


BANNER = r"""
        _ _     ___                   _     _  _
   __ _| | |_  / _ \                 | |   | || |
  / _` | | __|/ /_\ \ __ _  ___ _ __ | |_  | || | __ _ _ __ _ __   ___  ___ ___
 | (_| | | |_|  _  |/ _` |/ _ \ '_ \| __| | __ |/ _` | '__| '_ \ / _ \/ __/ __|
  \__,_|_|\__| | | | (_| |  __/ | | | |_  | || | (_| | |  | | | |  __/\__ \__ \
             \_| |_/\__, |\___|_| |_|\__|  \_| |_/\__,_|_|  |_| |_|\___||___/___/
                     __/ |
                    |___/   skill-based alt-agent-harness
"""


def _print_event(kind, text):
    print("[%s] %s" % (kind, text))


def _show_turn(turn: Turn):
    if turn.kind == "quit":
        return
    if turn.kind == "empty":
        return
    if turn.kind == "reply":
        elapsed = ""
        if turn.elapsed_s is not None:
            elapsed = "\n(%.1fs)" % turn.elapsed_s
        print("\n%s%s" % (turn.text, elapsed))
        return
    print(turn.text)


def run_once(session: Session, prompt: str):
    session.subscribe(_print_event)
    _show_turn(session.submit(prompt))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Skill-based alt-agent-harness")
    parser.add_argument(
        "-c", "--command",
        help="Run one prompt and exit (non-interactive).",
    )
    parser.add_argument(
        "--workspace",
        default=str(default_workspace()),
        help="Workspace root (default: cwd, or this checkout).",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Plain stdin REPL instead of the TUI.",
    )
    parser.add_argument(
        "--interface",
        choices=("tui", "repl"),
        default="tui",
        help="Chat front-end (default: tui).",
    )
    args = parser.parse_args(argv)
    interface = "repl" if args.repl else args.interface

    if args.command or interface == "repl":
        print(BANNER)

    try:
        session = boot(args.workspace)
    except setup.SetupAborted:
        print("\n[boot] setup aborted")
        sys.exit(1)

    if args.command:
        run_once(session, args.command)
        return

    if interface == "repl":
        from interfaces.repl import run as run_repl
        try:
            run_repl(session)
        except SystemExit:
            print("[boot] bye")
        return

    from interfaces.tui import run as run_tui
    run_tui(session)
