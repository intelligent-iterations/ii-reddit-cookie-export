from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
from typing import Iterator

from ii_reddit_cookie_export import cli


@contextmanager
def owned_temporary_directory(prefix: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=prefix) as raw_directory:
        directory = Path(raw_directory)
        marker = directory / ".ii-reddit-cookie-export-test-owned"
        marker.touch()
        yield directory
        if not marker.is_file():
            raise RuntimeError("test ownership marker disappeared before cleanup")


@dataclass
class Cookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = True
    expires: int | None = None

    def has_nonstandard_attr(self, name: str) -> bool:
        return name == "HttpOnly"


class RedditCookieExportTest(unittest.TestCase):
    def test_normalizes_only_reddit_cookies_and_requires_session(self) -> None:
        cookies = cli.normalize_reddit_cookies(
            [
                Cookie("reddit_session", "secret", ".reddit.com"),
                Cookie("token", "value", "www.reddit.com"),
                Cookie("unrelated", "value", "example.com"),
            ]
        )

        self.assertEqual(
            [cookie["name"] for cookie in cookies], ["reddit_session", "token"]
        )
        self.assertTrue(
            all(str(cookie["domain"]).endswith("reddit.com") for cookie in cookies)
        )

        with self.assertRaisesRegex(
            cli.CookieExportError, "no reddit_session"
        ):
            cli.normalize_reddit_cookies(
                [Cookie("token", "value", "reddit.com")]
            )

    def test_cookie_loader_is_scoped_to_reddit(self) -> None:
        received: dict[str, str] = {}

        def loader(**kwargs: str) -> list[Cookie]:
            received.update(kwargs)
            return [Cookie("reddit_session", "secret", ".reddit.com")]

        result = cli.extract_reddit_cookies(Path("chrome-cookies"), loader)

        self.assertEqual(result[0]["name"], "reddit_session")
        self.assertEqual(
            received,
            {"cookie_file": "chrome-cookies", "domain_name": "reddit.com"},
        )

    def test_cookie_count_is_bounded(self) -> None:
        cookies = [Cookie("reddit_session", "secret", ".reddit.com")]
        cookies.extend(
            Cookie(f"cookie-{index}", "value", ".reddit.com")
            for index in range(cli.MAX_COOKIE_COUNT)
        )

        with self.assertRaisesRegex(cli.CookieExportError, "too many"):
            cli.normalize_reddit_cookies(cookies)

    def test_private_export_refuses_to_replace_existing_file(self) -> None:
        payload = cli.serialize_cookie_export(
            [{"name": "reddit_session", "value": "secret", "domain": ".reddit.com"}]
        )
        with owned_temporary_directory(
            "reddit-cookie-export-test-"
        ) as directory:
            destination = directory / "account.json"
            result = cli.write_cookie_export(destination, payload)

            self.assertEqual(result.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o600)
            with self.assertRaisesRegex(
                cli.CookieExportError, "already exists"
            ):
                cli.write_cookie_export(destination, payload)

    def test_private_export_refuses_a_symlink(self) -> None:
        payload = b"[]\n"
        with owned_temporary_directory(
            "reddit-cookie-export-symlink-test-"
        ) as directory:
            target = directory / "target.json"
            target.write_bytes(b"keep")
            link = directory / "account.json"
            link.symlink_to(target)

            with self.assertRaisesRegex(cli.CookieExportError, "symlink"):
                cli.write_cookie_export(link, payload, force=True)

            self.assertEqual(target.read_bytes(), b"keep")

    def test_export_size_is_bounded(self) -> None:
        with self.assertRaisesRegex(
            cli.CookieExportError, "40 KB limit"
        ):
            cli.serialize_cookie_export(
                [{"name": "reddit_session", "value": "x" * (41 * 1024)}]
            )

    def test_default_output_path_is_package_owned_and_unique(self) -> None:
        with owned_temporary_directory(
            "reddit-cookie-export-path-test-"
        ) as directory:
            original_directory = cli.DEFAULT_EXPORT_DIR
            cli.DEFAULT_EXPORT_DIR = directory
            try:
                now = datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc)
                first = cli.default_output_path(now)
                first.touch()
                second = cli.default_output_path(now)
            finally:
                cli.DEFAULT_EXPORT_DIR = original_directory

        self.assertEqual(first.name, "reddit-cookies-20260905T180000Z.json")
        self.assertEqual(second.name, "reddit-cookies-20260905T180000Z-2.json")

    def test_keychain_check_requests_only_chrome_safe_storage(self) -> None:
        calls: list[list[str]] = []

        def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(cli.sys, "platform", "darwin"):
            cli.check_chrome_keychain_access(run)

        self.assertEqual(
            calls,
            [[
                "/usr/bin/security",
                "-q",
                "find-generic-password",
                "-w",
                "-a",
                "Chrome",
                "-s",
                "Chrome Safe Storage",
            ]],
        )


if __name__ == "__main__":
    unittest.main()
