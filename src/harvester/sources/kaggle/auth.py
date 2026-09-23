"""Log in to Kaggle with the official API."""

from __future__ import annotations

import contextlib
import io
from typing import Any

from harvester.utils import first_line

LOGIN_HELP = (
    "Couldn't log in to Kaggle. Create an API token at https://www.kaggle.com/settings/api, then\n"
    "  - set the KAGGLE_API_TOKEN environment variable, or\n"
    "  - save it to ~/.kaggle/access_token (an older ~/.kaggle/kaggle.json also works).\n"
    "You can also run `kaggle auth login` once to log in through your browser."
)


class KaggleAuthError(RuntimeError):
    pass


def connect() -> Any:
    """Log in and return a `KaggleApi`. Raises KaggleAuthError instead of exiting."""
    try:
        # The kaggle package prints a long help text (twice) when login fails,
        # so we hide its output and raise our own shorter message instead.
        with contextlib.redirect_stdout(io.StringIO()):
            # Imported here rather than at the top: the kaggle package tries to
            # log in the moment it's imported.
            from kaggle.api.kaggle_api_extended import KaggleApi

            api = KaggleApi()
            api.authenticate()  # looks for the env var, ~/.kaggle/access_token, or kaggle.json
    except SystemExit:  # the kaggle package quits when it can't find a valid login
        raise KaggleAuthError(LOGIN_HELP) from None
    except Exception as e:  # e.g. no internet connection
        raise KaggleAuthError(f"Couldn't reach Kaggle to log in: {first_line(e)}") from e
    return api
