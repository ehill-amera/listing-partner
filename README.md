# Listing Partner

Takes one rental unit's raw bracketed camera exposures and returns a listing package ready to post. No Lightroom. (Full setup, model use, and costs land here with unit 7; see `PRODUCT.md` for what it is.)

## Fresh clone

`pytest` passes on a clone without the gitignored raw photos and outputs: tests that need those files skip and print their reason. `./scripts/check` failing loudly on such a clone is by design: the banned-strings list lives outside the repo (see `AGENTS.md`), and the check refuses to run without it rather than scan against nothing.
