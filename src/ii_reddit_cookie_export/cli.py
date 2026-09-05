"""Export a logged-in Reddit session from a local Chrome profile."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Iterable, Sequence


MAX_EXPORT_BYTES = 40 * 1024
MAX_COOKIE_COUNT = 256
REDDIT_SESSION_COOKIE = "reddit_session"
DEFAULT_CHROME_DIR = (
    Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
)
DEFAULT_EXPORT_DIR = (
    Path.home()
    / "ii"
    / "ii-reddit-cookie-export"
    / "exports"
)
LOGIN_KEYCHAIN = Path.home() / "Library" / "Keychains" / "login.keychain-db"


class CookieExportError(RuntimeError):
    """A safe, user-facing Reddit cookie export failure."""


@dataclass(frozen=True)
class ChromeProfile:
    directory: Path
    directory_name: str
    profile_name: str
    email: str

    @property
    def label(self) -> str:
        return self.email or self.profile_name


def profile_choice_labels(profiles: Sequence[ChromeProfile]) -> list[str]:
    """Return human labels, exposing Chrome's directory only for ambiguity."""
    base_labels = [profile.label for profile in profiles]
    counts = {
        label.casefold(): sum(
            candidate.casefold() == label.casefold() for candidate in base_labels
        )
        for label in base_labels
    }
    return [
        (
            f"{profile.label} [{profile.directory_name}]"
            if counts[profile.label.casefold()] > 1
            else profile.label
        )
        for profile in profiles
    ]


def _profile_sort_key(path: Path) -> tuple[int, int, str]:
    if path.name == "Default":
        return (0, 0, path.name)
    if path.name.startswith("Profile "):
        try:
            return (1, int(path.name.removeprefix("Profile ")), path.name)
        except ValueError:
            pass
    return (2, 0, path.name)


def discover_chrome_profiles(chrome_dir: Path = DEFAULT_CHROME_DIR) -> list[ChromeProfile]:
    chrome_dir = chrome_dir.expanduser()
    if not chrome_dir.is_dir():
        return []

    profiles: list[ChromeProfile] = []
    for directory in sorted(chrome_dir.iterdir(), key=_profile_sort_key):
        preferences_path = directory / "Preferences"
        if not directory.is_dir() or not preferences_path.is_file():
            continue
        try:
            preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        account_info = preferences.get("account_info")
        primary_account = (
            account_info[0]
            if isinstance(account_info, list) and account_info and isinstance(account_info[0], dict)
            else {}
        )
        profile_data = preferences.get("profile")
        profile_data = profile_data if isinstance(profile_data, dict) else {}
        profile_name = str(profile_data.get("name") or directory.name).strip()
        email = str(primary_account.get("email") or "").strip()
        profiles.append(
            ChromeProfile(
                directory=directory,
                directory_name=directory.name,
                profile_name=profile_name,
                email=email,
            )
        )
    return profiles


def resolve_profile(profiles: Sequence[ChromeProfile], requested: str) -> ChromeProfile:
    needle = requested.strip().casefold()
    if not needle:
        raise CookieExportError("A Chrome profile is required.")

    exact_directory = [
        profile for profile in profiles if profile.directory_name.casefold() == needle
    ]
    if len(exact_directory) == 1:
        return exact_directory[0]

    matches = [
        profile
        for profile in profiles
        if needle in {profile.profile_name.casefold(), profile.email.casefold()}
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CookieExportError(
            "That profile name or email is ambiguous. Pass the directory name shown in brackets."
        )
    raise CookieExportError(
        f"Chrome profile '{requested}' was not found. Run with --list-profiles."
    )


def choose_profile(profiles: Sequence[ChromeProfile], input_fn: Callable[[str], str] = input) -> ChromeProfile:
    if not profiles:
        raise CookieExportError("No Chrome profiles were found.")
    if not sys.stdin.isatty():
        raise CookieExportError(
            "Profile selection needs a terminal. Pass --profile with a listed directory name."
        )

    print("Chrome profiles:")
    for index, label in enumerate(profile_choice_labels(profiles), start=1):
        print(f"  {index}. {label}")
    while True:
        answer = input_fn(f"Choose a profile (1-{len(profiles)}): ").strip()
        try:
            selected = int(answer)
        except ValueError:
            selected = 0
        if 1 <= selected <= len(profiles):
            return profiles[selected - 1]
        print("Enter one of the numbers shown above.")


def find_cookie_database(profile: ChromeProfile) -> Path:
    candidates = (profile.directory / "Cookies", profile.directory / "Network" / "Cookies")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CookieExportError(
        f"Chrome cookie database was not found for {profile.directory_name}."
    )


def check_chrome_keychain_access(
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    if sys.platform != "darwin":
        raise CookieExportError("Chrome Keychain export is currently supported only on macOS.")
    command = [
        "/usr/bin/security",
        "-q",
        "find-generic-password",
        "-w",
        "-a",
        "Chrome",
        "-s",
        "Chrome Safe Storage",
    ]
    result = run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise CookieExportError(
            "Chrome Safe Storage is unavailable. Unlock the login keychain with "
            f"`security unlock-keychain \"{LOGIN_KEYCHAIN}\"` and try again."
        )


def _is_reddit_domain(value: object) -> bool:
    domain = str(value or "").strip().lower().lstrip(".")
    return domain == "reddit.com" or domain.endswith(".reddit.com")


def normalize_reddit_cookies(cookies: Iterable[object]) -> list[dict[str, object]]:
    normalized: dict[tuple[str, str, str], dict[str, object]] = {}
    for cookie in cookies:
        name = str(getattr(cookie, "name", "") or "").strip()
        value = getattr(cookie, "value", None)
        domain = str(getattr(cookie, "domain", "") or "").strip().lower()
        path = str(getattr(cookie, "path", "/") or "/")
        if not name or not isinstance(value, str) or not _is_reddit_domain(domain):
            continue

        has_nonstandard_attr = getattr(cookie, "has_nonstandard_attr", lambda _name: False)
        record: dict[str, object] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": bool(getattr(cookie, "secure", False)),
            "httpOnly": bool(has_nonstandard_attr("HttpOnly")),
        }
        expires = getattr(cookie, "expires", None)
        if isinstance(expires, (int, float)) and expires > 0:
            record["expires"] = expires
        normalized[(name, domain, path)] = record

    result = sorted(
        normalized.values(),
        key=lambda record: (str(record["domain"]), str(record["path"]), str(record["name"])),
    )
    if not result:
        raise CookieExportError("No reddit.com cookies were found in that Chrome profile.")
    if len(result) > MAX_COOKIE_COUNT:
        raise CookieExportError("Chrome returned too many Reddit cookies to export safely.")
    if not any(cookie["name"] == REDDIT_SESSION_COOKIE for cookie in result):
        raise CookieExportError(
            "That Chrome profile has no reddit_session cookie. Sign in to Reddit there and try again."
        )
    return result


def _load_browser_cookie3() -> Callable[..., Iterable[object]]:
    try:
        import browser_cookie3
    except ImportError as error:
        raise CookieExportError(
            "browser-cookie3 is missing. Reinstall ii-reddit-cookie-export."
        ) from error
    return browser_cookie3.chrome


def extract_reddit_cookies(
    cookie_database: Path,
    cookie_loader: Callable[..., Iterable[object]] | None = None,
) -> list[dict[str, object]]:
    loader = cookie_loader or _load_browser_cookie3()
    try:
        cookies = loader(cookie_file=str(cookie_database), domain_name="reddit.com")
        return normalize_reddit_cookies(cookies)
    except CookieExportError:
        raise
    except Exception as error:
        raise CookieExportError(
            "Chrome cookies could not be decrypted. Confirm the selected profile and unlock "
            "the login keychain before retrying."
        ) from error


def serialize_cookie_export(cookies: Sequence[dict[str, object]]) -> bytes:
    payload = (json.dumps(cookies, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(payload) > MAX_EXPORT_BYTES:
        raise CookieExportError("The Reddit cookie JSON exceeds the account connector's 40 KB limit.")
    return payload


def default_output_path(now: datetime | None = None) -> Path:
    current = now or datetime.now(timezone.utc)
    timestamp = current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = DEFAULT_EXPORT_DIR / f"reddit-cookies-{timestamp}.json"
    if not base.exists():
        return base
    for suffix in range(2, 1000):
        candidate = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
        if not candidate.exists():
            return candidate
    raise CookieExportError("Could not allocate a unique Reddit cookie export filename.")


def write_cookie_export(path: Path, payload: bytes, force: bool = False) -> Path:
    destination = Path(os.path.abspath(path.expanduser()))
    if destination.is_symlink():
        raise CookieExportError("Refusing to write a Reddit cookie export through a symlink.")
    if destination.exists() and not destination.is_file():
        raise CookieExportError(f"Output is not a regular file: {destination}.")
    if destination.exists() and not force:
        raise CookieExportError(f"Output already exists: {destination}. Pass --force to replace it.")

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".reddit-cookie-export-", suffix=".json", dir=destination.parent
        )
        temporary_path = Path(raw_path)
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temporary_path, destination)
        else:
            try:
                os.link(temporary_path, destination)
            except FileExistsError as error:
                raise CookieExportError(
                    f"Output already exists: {destination}. Pass --force to replace it."
                ) from error
            temporary_path.unlink()
        temporary_path = None
        destination.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return destination
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def reveal_output_in_finder(
    path: Path,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    """Reveal an export without turning Finder trouble into an export failure."""
    if sys.platform != "darwin":
        return False
    try:
        result = run(
            ["/usr/bin/open", "-R", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the logged-in Reddit cookies from a macOS Chrome profile to JSON."
    )
    parser.add_argument(
        "--profile",
        help="Chrome directory, profile name, or unique profile email. Prompts when omitted.",
    )
    parser.add_argument(
        "--list-profiles", action="store_true", help="List Chrome profiles without reading cookies."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=f"Output JSON path. Defaults to a unique file under {DEFAULT_EXPORT_DIR}.",
    )
    parser.add_argument(
        "--chrome-user-data-dir",
        type=Path,
        default=DEFAULT_CHROME_DIR,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--force", action="store_true", help="Replace an existing --output file."
    )
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    profiles = discover_chrome_profiles(args.chrome_user_data_dir)
    if args.list_profiles:
        if not profiles:
            raise CookieExportError("No Chrome profiles were found.")
        for label in profile_choice_labels(profiles):
            print(label)
        return 0

    profile = resolve_profile(profiles, args.profile) if args.profile else choose_profile(profiles)
    check_chrome_keychain_access()
    cookie_database = find_cookie_database(profile)
    cookies = extract_reddit_cookies(cookie_database)
    payload = serialize_cookie_export(cookies)
    output_path = write_cookie_export(args.output or default_output_path(), payload, args.force)
    print(f"Saved {len(cookies)} Reddit cookies to {output_path}")
    print("Cookie values were not printed. The mode-0600 JSON file is ready for your adapter.")
    if reveal_output_in_finder(output_path):
        print("Finder opened with the JSON file selected.")
    print("Next: configure your Reddit adapter with this file and its account username.")
    return 0


def main() -> None:
    try:
        raise SystemExit(run_cli())
    except CookieExportError as error:
        raise SystemExit(f"error: {error}") from error
