# Publishing brief (Handover v2 → Notion)

Repository: `/Users/elliotwoods/Downloads/jinhee SOS` (quote the path). The documentation owner is the designated docs
session (see AGENTS.md "Handoff and hygiene").

## Sources

- **Drafts:** `console/docs/handover_v2/handbook/H0..H6-*.md` (bilingual) and `extended/X01..X13-*.md` (English).
  Files starting with `_` are coverage notes and are never published.
- **Page ids:** `PAGES.json`, with keys root (= H0), H1–H6, XP (the Extended reference parent), X01–X13.
- **Titles:** the tables in `STYLE_GUIDE.md` "Two sections". A Notion title is `KEY · EN title | KR title` for handbook
  pages (e.g. `H3 · Cube procedures | 큐브 작업`) and `KEY · EN title` for extended pages (e.g.
  `X06 · Pool / forest — detail`).
- **Screenshots:** `console/docs/shots/<ID>.png`, with captions in `shots/manifest.json`. Only handbook pages use them.

## Render

```
python3 console/tools/handover_render.py KEY --uploads <uploads json> --out <tmp>/KEY.md
```

The render exits 1 on any unresolved placeholder. `--all --outdir DIR` renders every page.

## Per page

1. **Upload screenshots.** For every shot id in the draft (`grep '{{shot:'`):
   - load the Notion tools (`ToolSearch select:mcp__claude_ai_Notion__notion-create-file-upload,mcp__claude_ai_Notion__notion-update-page,mcp__claude_ai_Notion__notion-fetch,mcp__claude_ai_Notion__notion-move-pages`);
   - call `notion-create-file-upload` with `filename: "<ID>.png"`;
   - upload with exactly one request:
     `curl -sS -X POST "<upload_url>" <each upload_header as -H> -F "file=@console/docs/shots/<ID>.png"`;
   - record `{"<ID>": "<markdown_source>"}` in your own uploads json.

   Uploads expire if they are not attached within about an hour, so upload right before you publish. Never print the
   upload headers or tokens. Use a private scratch sub-folder; other publishers share the scratchpad.
2. **Set the title.** Use `notion-update-page` `update_properties` with the title rule above.
3. **Replace the content.** Use `replace_content` with `allow_async: false`. If the page is too big, split it at a `## `
   boundary: `replace_content` for the first part, then `insert_content` with `position: end` for the rest. If the tool
   says child pages would be deleted, stop and report; never pass `allow_deleting_content`.
4. **Fetch the page back and check it.** Confirm:
   - the title and the parent are right;
   - there is no `{{`;
   - the image count equals the shot count;
   - tables, callouts, toggles and mermaid blocks are present;
   - mentions resolve;
   - numbered lists continue after images.

## Structure rules

- X pages live under the XP page; H pages and XP live directly under the root.
- The root is published last. Its content ends with `<page url="…">` blocks for H1–H6 and XP, in that order, so every
  child stays attached.
- Never touch the v1 pages.
