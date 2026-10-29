# Third-party code: meta-sam-parser

**What:** `meta-sam-parser==0.1.0` (declared in `pyproject.toml`) is Meta's
official reader for SAM 3.1's wire grammar. It parses the streamed
`output_text` lane into typed records and decodes the arithmetic-coded
mask payloads into binary rasters. Writing that decoder by hand is not
sensible: the body is arithmetic-coded under a model only Meta's code
implements, so the official zero-dependency reader is the correct tool.

**Source:** https://pypi.org/project/meta-sam-parser/ (also
https://github.com/meta-models/meta-sam), fetched 2026-10-29.

**License:** SAM License (Meta Platforms). The full text is the file next
to this one, `SAM-LICENSE` (verbatim copy of the sdist's `LICENSE`).

**Used by:** `listing_partner/segment.py` (window masks). Only the parsing
and mask-decoding functions are used; no model weights ship with it.
