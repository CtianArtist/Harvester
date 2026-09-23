# 001: Official API first, browser only for thread text

**Status:** accepted (revised September 2026: threads are now found through the API)

## Context

Kaggle pages are drawn with JavaScript, so plain HTTP scraping returns empty
shells, and a browser is slow and breaks when the layout changes. The official
API returns search results, file lists, sizes, dates, licenses and
descriptions as structured data. It can also list a dataset's discussion
threads (titles, links, dates, comment counts), but not what they say.

## Decision

Use the official `kaggle` API for everything it covers, including finding
threads. Use a headless browser (Playwright) only to read the text of threads
the API has listed, and only for datasets that have passed every other check.

Two API fields turned out to be unreliable and are not used: the search
result's `topic_count` is always 0 (uciml/iris has 33 threads), and a topic's
`content` is always empty.

Scraping stays polite: a small number of tabs, a pause before each page load,
no images or fonts, and robots.txt is honoured. (kaggle.com currently answers
`/robots.txt` with its HTML home page; the code treats a non-`text/plain`
response as "no robots file" explicitly instead of parsing HTML by accident.)

## Consequences

- Most of a run is fast, structured and stable, and the browser never starts
  when no kept dataset has threads.
- The browser stage is the fragile part, and it does as little as possible: it
  opens known thread URLs and saves one element's text. That selector lives in
  settings, and a run warns when it stops matching.
