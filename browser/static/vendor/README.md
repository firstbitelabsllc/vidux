# vendor/

Third-party browser scripts vendored locally (not loaded from a CDN, no
build step — vidux's browser UI has none).

## dompurify.min.js

- Source: https://github.com/cure53/DOMPurify (npm `dompurify`)
- Version: 3.4.11
- License: Apache-2.0 OR MPL-2.0 (see `dompurify.LICENSE`; header preserved
  in the minified file itself)
- SHA-256: `dbabb5b205a333ec49c8c09e7fca30ef66df0523bb8bc0fa9ea843841f111dbd`
- Copied verbatim from `dompurify@3.4.11`'s published `dist/purify.min.js`,
  unmodified. To update: `npm view dompurify version`, download the new
  `dist/purify.min.js` from the matching npm tarball, replace this file,
  update the version/hash above.
- Used by `app.js`'s `renderMarkdownBody()` to sanitize `marked.parse()`
  output before it is ever assigned to `innerHTML` — closes a stored-XSS
  path where a crafted PLAN.md/INBOX.md/evidence file could execute script
  as the loopback client.
