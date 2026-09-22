# Publishing brief (Handover v2 → Notion)

Repository: `/Users/elliotwoods/Downloads/jinhee SOS` (quote the path). Drafts: `console/docs/handover_v2/NN-*.md`,
page ids: `PAGES.json`, screenshots: `console/docs/shots/<ID>.png` (+ `manifest.json` with EN/KR titles).
Renderer: `python3 console/tools/handover_render.py NN --uploads <your uploads json> --out <tmp>/NN.md`
(resolves `{{shot:ID}}` → `![caption](markdown_source)`, `{{page:NN}}` → `<mention-page url=…/>`, `{{v1-root}}`,
`{{v1-14}}`, `{{test-report-table}}`; exits 1 on any unresolved placeholder).

Per chapter you own:
1. For every shot id in the chapter's `shots` list (INDEX.json; or grep `{{shot:` in the draft): load the Notion tools
   (`ToolSearch select:mcp__claude_ai_Notion__notion-create-file-upload,mcp__claude_ai_Notion__notion-update-page,mcp__claude_ai_Notion__notion-fetch`),
   call `notion-create-file-upload` with `filename: "<ID>.png"`, then upload with exactly one request:
   `curl -sS -X POST "<upload_url>" <every header from upload_headers as -H "Name: value"> -F "file=@console/docs/shots/<ID>.png"`
   and record `{"<ID>": "<markdown_source from the response>"}` into `console/docs/handover_v2/uploads-<yourname>.json`
   (merge, never overwrite other ids). Never print the upload headers/tokens into the report.
2. Render the chapter with your uploads json; read the rendered file once for sanity (no `{{`, images present).
3. `notion-update-page` `command: replace_content` with `page_id` from PAGES.json and `new_str` = the rendered markdown
   (`allow_async: false`). If the tool rejects the size, split: `replace_content` with the first half and `insert_content`
   (`position: end`) with the rest.
4. `notion-fetch` the page back: confirm the title is unchanged, no raw `{{` remains, every image renders (image blocks
   present, count equals the number of shots), every `<mention-page>` resolved. Fix and re-update if not.
5. Do not touch any v1 page (ids listed in INDEX.json), do not create new pages, do not edit code, do not commit.

Report per chapter: page URL, number of images, fetch-back verification result, and anything you had to change.
