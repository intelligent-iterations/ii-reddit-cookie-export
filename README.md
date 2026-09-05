# ii-reddit-cookie-export

[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/intelligent-iterations/ii-reddit-cookie-export/badge)](https://securityscorecards.dev/viewer/?uri=github.com/intelligent-iterations/ii-reddit-cookie-export)

Export the Reddit login from a local Chrome profile to a private cookie JSON
file. The file can be used by a browser adapter without giving that
application access to your entire Chrome profile.

The exporter runs locally. It does not contact Reddit, upload cookies, or
print cookie values.

## Requirements

- macOS
- Python 3.10 or newer
- Google Chrome with the Reddit account already signed in
- access to Chrome Safe Storage in the macOS login Keychain

## Install and run

From a checkout of this package:

```bash
python3 -m pip install .
ii-reddit-cookie-export
```

On macOS, you can instead double-click `reddit-cookie-export.command` in the
checkout. The launcher creates an isolated virtual environment under
`~/ii/ii-reddit-cookie-export/` before running the same command.

Choose the Chrome profile containing the Reddit account. macOS may ask whether
Terminal can access **Chrome Safe Storage**. Allow access so the tool can
decrypt that profile's cookies locally.

The export is written with mode `0600` under:

```text
~/ii/ii-reddit-cookie-export/exports/
```

Run the command once for each Reddit account.

## Select an account without a prompt

List Chrome profiles:

```bash
ii-reddit-cookie-export --list-profiles
```

Select a profile by its displayed email or Chrome directory name:

```bash
ii-reddit-cookie-export --profile example@example.com
```

Choose a specific output path:

```bash
ii-reddit-cookie-export \
  --profile example@example.com \
  --output ./private/reddit-account.cookies.json
```

## Use the exported file

Keep the cookie path in your application's private Reddit adapter:

```js
const redditAccounts = {
  "reddit-main": {
    username: "example_user",
    cookiesPath: "/private/state/reddit-main.cookies.json"
  }
};
```

The exporter includes only `reddit.com` cookies and refuses to create a file
unless the profile contains `reddit_session`. Exports are limited to 256
cookies and 40 KB.

Cookie JSON files are credentials. Never commit, upload, or log them. Delete
an old export after replacing it, and revoke the Reddit session if an export
is exposed.

## Development

Run the tests without using a real Chrome profile:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

This project is maintained by
[Intelligent Iterations](https://github.com/intelligent-iterations) and is not
affiliated with or endorsed by Reddit.
