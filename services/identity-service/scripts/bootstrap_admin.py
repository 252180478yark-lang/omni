#!/usr/bin/env python3
"""Explicitly create or promote one Identity administrator.

This command is never called by service startup or migrations. Passwords are
accepted only from an interactive prompt or stdin and are never placed in argv,
environment variables, logs, or output.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if not SERVICE_ROOT.is_absolute() or not (SERVICE_ROOT / "app").is_dir():
    raise SystemExit("identity service root is unavailable")
sys.path.insert(0, str(SERVICE_ROOT))

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.models.user import User, UserRole
from app.utils.security import hash_password


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap one explicit Identity admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read exactly one password line from stdin instead of an interactive prompt",
    )
    parser.add_argument(
        "--promote-existing",
        action="store_true",
        help="explicitly promote/reactivate an existing account and reset its password",
    )
    return parser.parse_args()


def _read_password(password_stdin: bool) -> str:
    if password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    elif sys.stdin.isatty():
        password = getpass.getpass("Admin password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise ValueError("password confirmation does not match")
    else:
        raise ValueError("non-interactive use requires --password-stdin")
    if (
        len(password) < 12
        or len(password) > 1024
        or password.casefold() in {"password123", "administrator", "changeme12345"}
        or not any(character.isalpha() for character in password)
        or not any(character.isdigit() for character in password)
    ):
        raise ValueError("admin password does not satisfy the bootstrap policy")
    return password


async def _bootstrap(args: argparse.Namespace, password: str) -> str:
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).casefold()
    display_name = args.display_name.strip()
    if not display_name or len(display_name) > 128:
        raise ValueError("display name must contain 1..128 characters")
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                hashed_password=hash_password(password),
                display_name=display_name,
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(user)
            outcome = "created"
        elif args.promote_existing:
            user.display_name = display_name
            user.hashed_password = hash_password(password)
            user.role = UserRole.ADMIN
            user.is_active = True
            outcome = "promoted"
        elif user.role is UserRole.ADMIN and user.is_active:
            outcome = "already_active_admin"
        else:
            raise ValueError("account exists; --promote-existing is required")
        await session.commit()
        return outcome


async def _main() -> int:
    args = _arguments()
    try:
        password = _read_password(args.password_stdin)
        outcome = await _bootstrap(args, password)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, ValueError) else "runtime failure"
        print(f"bootstrap failed: {type(exc).__name__}: {detail}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()
    print(f"bootstrap admin: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
