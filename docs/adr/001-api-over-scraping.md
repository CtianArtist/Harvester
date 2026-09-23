# 001: Official API first, browser only for discussions

**Status:** accepted

## Context

Kaggle pages are drawn with JavaScript, so plain HTTP scraping returns empty
shells, and a browser is slow and breaks when the layout changes. The official
API returns search results, file lists, sizes, dates and licenses as structured
data, but it has no endpoint for discussion threads.

## Decision

Use the official `kaggle` API for everything it covers. Use a headless browser
(Playwright) only for discussion threads, and only for datasets that have
already passed every other check and that the API reports as having
discussions.

Scraping stays polite: a small number of tabs, a pause before each page load,
no images or fonts, and robots.txt is honoured. (kaggle.com currently answers
`/robots.txt` with its HTML home page; the code treats a non-`text/plain`
response as "no robots file" explicitly instead of parsing HTML by accident.)

## Consequences

- Most of a run is fast, structured and stable.
- The browser stage is the fragile part. Its selectors live in settings, and a
  run warns when no threads are found anywhere, which usually means the layout
  changed.
