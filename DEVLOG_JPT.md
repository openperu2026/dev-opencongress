# Development log

## 2026-09-09

### PDF buttons in the bill detail timeline

- Added **Descargar PDF** links to steps in `app/templates/bills/detail.html`.
- The detail route loads the bill's `raw_bill_documents` in one query and groups them by `step_id` in `documents_by_step`. Steps without usable document links show no button; multiple documents receive numbered buttons.
- No database migration or stored `has_pdf` flag was added. Availability is derived from the existing document records, avoiding a separate flag that would need synchronization.
- Added `/bills/<bill_id>/document/<step_id>/<file_id>` to download a specific S3 document as an attachment named `<bill_id>-<step_id>-<file_id>.pdf`. The lookup checks the bill, step, and file together and does not require extracted text in `bill_texts`.
- When a document has an `s3_key` and `AWS_S3_BUCKET_NAME` is configured, the detail page uses this download route. Otherwise, it uses the original HTTP(S) Congress URL when available. Congress controls its response, so this fallback may open the browser's PDF viewer instead of forcing a download.

### Important distinction: detail versus differences

- **Detail page:** uses raw document records directly, supports multiple PDFs, and provides the Congress URL fallback.
- **Differences page (Ver documento):** retains the existing `/bills/<bill_id>/document/<step_id>` route, serving the selected S3 PDF inline in a new tab. Its resolver requires a canonical `BillText` record and an S3 key; there is no Congress fallback.
- A step can have zero, one, or multiple documents. The schema does not guarantee that every step has a PDF.
- Displaying a button checks database metadata and configuration, not whether the remote file physically exists. A Congress link can indicate a missing S3 key or an unconfigured bucket; it does not prove that the physical S3 object is absent.
- Live database coverage and physical S3 file availability were not audited.
-*Note* Is every S3 configured document only used for the differences?

### Approval filter correction

- Added `status != "all"` to `search_requested` in `app/routes/bills.py`.
- Previously, selecting only approved or non-approved bills did not activate the filtered search. The page instead displayed the default recent bills, which can include unapproved bills even while the approved radio option is selected.
- The existing query already filters `Bill.bill_approved` correctly once search mode is active.
- Radio values are `all`, `approved`, and `not-approved`; the search button submits the selected value.

### Other interface changes present in today's working tree

- Added search and **Limpiar** controls beside the approval radio options in `app/templates/bills/search.html`.
- Commented out the placeholder Terms of Service, Privacy, and Contact footer links in `app/templates/base.html`; the About link remains.
- Extended the existing commented-out section in `app/templates/landing/index.html` to include the contact section, hiding it from the rendered page.

### Validation

- During the PDF implementation, 17 bill detail/difference route tests passed. A separate test for original-URL fallback when the S3 bucket is unconfigured also passed: **18 tests total**.
- Added coverage for multiple documents, hidden buttons without usable links, downloads without extracted text, attachment headers, mismatched step/file requests, and the bucket configuration fallback.
- Ruff checks passed for the modified route and test files at that point.
- These results cover the PDF implementation. The later approval-filter edit and other interface changes were not separately tested during this documentation update.

### Discussed, not implemented: download all as ZIP

- Preferred direction: generate a ZIP when the user clicks a download-all button for a step with multiple PDFs. No ZIP endpoint or button has been implemented.
- ZIP generation would fetch the PDFs, package them, and send the archive. This consumes server network bandwidth, CPU, memory or temporary disk, and request-worker capacity; concurrent downloads multiply that load.
- PDFs usually compress little, so packaging without additional compression can reduce CPU work. Temporary disk, bundle-size limits, timeouts, and concurrency limits should be considered before implementation.
- ZIP is preferred over RAR for broad support. Missing-document behavior should be explicit rather than silently returning an incomplete archive.

## 2026-09-17

### Shared visual identity and navigation

- Consolidated the active palette around `--background-hero`, `--hero-color`, `--atomic-tangerine`, `--red-crayola`, and `--flirt` in `app/static/css/layout.css`.
- The landing navbar has its own gradient treatment; non-landing views use the navy navbar with tangerine navigation links.
- Updated the Imagotipo and Isotipo treatment so their color can be controlled from CSS. The isotipo is rendered through a CSS mask on the landing page.
- Set the base font to Roboto and kept weights within the imported set (`400`, `500`, `700`) to avoid synthesized heavy weights.

### Landing, detail, and comparison views

- Split the landing content into visually distinct sections and aligned the “Acerca de” and “Qué sigue” card systems with the current palette.
- Updated the bill-detail timeline with a fixed “Línea de tiempo” heading, palette-aware cards, timeline line/dots, and a contained internal scroll area.
- Removed unwanted detail-page outer spacing and made the timeline/detail layout occupy the available width.
- Updated `/difference`: the bill identifier is now the link back to the bill detail; the separate “Volver” link was removed.
- Restyled the version comparison panel, added a compact “Documento” link aligned to the right of each version header, and removed the unresolved Material Symbols text from that control.

### Search controls and filters

- Moved the Congress search actions to the end of the form, after advanced search options. “Buscar” and “Limpiar” now share the same appearance and hover behavior as the bill-search controls.
- Kept normal and advanced bill-search fields in one form so a single Buscar action submits all selected filters while period/chamber tabs preserve active filter values.
- Corrected Congress search period scoping in `app/routes/congress.py`:
  - A stale Senate/Deputies selection is cleared when changing to the unicameral `2021-2026` period.
  - Region and special-committee filters now include the selected legislative period.
  - Region and special-committee dropdown options are now scoped to the selected period.
- Added `test_legacy_period_clears_a_carried_over_chamber_filter` to prevent a chamber filter from persisting into `2021-2026`.

### Congress detail

- Applied the shared bills-table style to the recent-bills table in `/congress/<id>`, including mobile `data-label` support.
- Restyled the three congress statistics cards using the current navy, teal, tangerine, and pink palette.
- Added targeted responsive refinements for bill detail, comparison, Congress detail cards/tables, and narrow screens.

### Validation and limitation

- `python -m py_compile app/routes/congress.py app/routes/utils.py` completed successfully.
- `git diff --check` reported no whitespace errors for the changed files (only existing line-ending warnings).
- Targeted `pytest` execution for Congress search did not emit a result and remained blocked, so it was stopped. It must be rerun in a healthy test environment before treating the new regression test as passed.

## backlog or riew
 - Top news of last scrapping view
 - Add a real email
 - make visual identity more coding-style
 - make a review of UX (specially in mobile version)
 - its pendant to recognize what kind of documention is for each one each step (we can look the ViT of DSC project )
 - Create a new difference between version view, so we can compare freely betrween diferent documents (for this we need to see what is the flag for the version). Ask cesar how this is made, and probably would be realted to previous bullet. This might open another feature in the pipeline of the database

