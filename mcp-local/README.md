# Arm MCP server: knowledge-base tools

For a how-to, set-up, deployment, tuning, or migration task, use
`knowledge_base_search` once, then pass the best hit's `learning_path` to
`get_learning_path` to retrieve the stored tutorial in one call.

## Search response

`knowledge_base_search(query, invocation_reason=None, filters=None, k=5,
scope="chunks")` retains the search library's ranking and filters. `k` accepts
integers from 1 to 20. Filters `doc_type`, `product`, and `platform` accept a label
or non-empty list; labels within a field use OR, and fields use AND. `scope="page"`
expands the initially matched pages using stored ordering metadata and should be
used when the user requests or approves wider context.

Each response entry retains its citation `url`, `title`, `heading`, `snippet`,
array-valued `doc_type`, `product`, and `platform`, and `score`. Existing extra
fields, including `context`, `page_url`, and `parent_page_url`, remain available.
`edition` is no longer a filter or response field. The MCP presentation omits
`distance`, `disclaimer`, and `url_tracking_instruction`, and removes duplicate
`Document Title:` / `Heading Path:` prefixes only at the top of snippets.
Session instructions carry the original legal and URL-preservation guidance.
The shared `arm_kb_search` Python API retains its existing response contract.

Learning Path hits also contain `learning_path`, an anchored root URL such as
`https://learn.arm.com/learning-paths/servers-and-cloud-computing/nested-virtualization/`.
Other hits omit that field. Preserve citation URLs exactly as returned, including
query parameters and fragments.

## Read an offline Learning Path

```json
{"url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/nested-virtualization/"}
```

`get_learning_path(url, mode="full", page=None, invocation_reason=None)` reads
only shipped knowledge-base metadata. It makes no network requests. It groups
stored chunks into pages, restores split embedding chunks, and removes tutorial
navigation, author metadata, completion/share/feedback sections, and the
`_next-steps` page. Stored page/chunk ordering takes precedence; older snapshots
fall back to step versions and heading hierarchy.

- `full` returns ordered pages and sections with their text and citation URLs.
- `commands` returns only fenced blocks and unfenced lines starting with `sudo `,
  `export `, or `$ ` (leading whitespace is allowed). Code blocks of all languages
  are included. Page citations are supplied in the response note.
- `outline` lists pages, citation URLs, and original text character counts.

Pass `page` to retrieve one page. Supplying a step-page URL as `url` automatically
selects that page unless `page` is explicitly supplied. Lookup ignores query
parameters, fragments, and trailing slashes; displayed citations retain their
stored query parameters. A fragment on the root still selects the whole path.

```json
{"url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/nested-virtualization/", "mode": "commands"}
```

Successful responses contain `learning_path`, `mode`, `page` (the requested page,
or null), `chars`, `text`, and `note`. Text longer than 80,000 characters returns
`mode="outline"` with a note directing the caller to repeat the request with
`page=<url>` from that outline. Unknown paths/pages and invalid modes return
`{"error": "...", "hint": "..."}`. This tool does not require page-scope search
expansion metadata, so it also works with older shipped snapshots.

Search and Learning Path calls and their results are logged as paired entries in
`/workspace/mcp-traffic.jsonl`, including the optional invocation reason.
