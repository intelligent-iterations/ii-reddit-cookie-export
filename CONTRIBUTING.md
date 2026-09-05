# Contributing

Contributions are welcome through GitHub pull requests.

Before submitting a change:

1. Never use or commit real browser cookies, account names, or profile data.
2. Keep cookie extraction local and limited to Reddit domains.
3. Preserve mode-`0600`, no-overwrite, size, and cookie-count safeguards.
4. Run `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
5. Install into a disposable virtual environment and run
   `ii-reddit-cookie-export --help`.

By contributing, you agree that your contribution is licensed under the MIT
License.
