# Security and privacy

- Treat survey responses, names, ratings, spreadsheet IDs, and n8n exports as
  private data.
- Use n8n credentials for Google Sheets and webhook authentication.
- Review workflow exports before publishing; n8n may include credential names,
  IDs, URLs, pinned data, and execution metadata.
- Keep production input and output under `private/` or outside this repository.
- If sensitive data was ever committed, rotate the affected credential and
  rewrite repository history before making the repository public.
