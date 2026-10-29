# Third-party data: lensfun lens profile

**What:** `nikon-af-p-dx-10-20mm.xml` is one lens node extracted unchanged
from the lensfun lens database: the Nikon AF-P DX Nikkor 10-20mm f/4.5-5.6G
VR (distortion rows at 10/12/14/16/20mm, TCA rows at 10-20mm, calibrated on
a Nikon D7200). It is the lens unit-a was shot with, identified from the
NEFs' own metadata (10-20mm, f/4.5-5.6, G/D/VR type bits, all 86 frames).

**Source:** https://github.com/lensfun/lensfun, file
`data/db/slr-nikon.xml`, fetched 2026-10-29. Only this lens's `<lens>`
node was kept; nothing else was changed.

**License:** Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0),
per the lensfun README. The full license text is the file next to this
one, `COPYING.CC_BY-SA_3.0` (verbatim copy of lensfun's
`data/COPYING.CC_BY-SA_3.0`).

**Used by:** `listing_partner/geometry.py` (distortion and TCA correction).
The correction math was reimplemented from the published lensfun formulas
and verified against line straightness on real photos; no lensfun code is
used or copied.
