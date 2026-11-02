# Listing Partner

Takes one rental unit's raw bracketed camera exposures and returns a listing package ready to post. No Lightroom. (Full setup, model use, and costs land here with unit 7; see `PRODUCT.md` for what it is.)

## Fresh clone

`pytest` passes on a clone without the gitignored raw photos and outputs: tests that need those files skip and print their reason. `./scripts/check` failing loudly on such a clone is by design: the banned-strings list lives outside the repo (see `AGENTS.md`), and the check refuses to run without it rather than scan against nothing.

## Known limits

Window pulls and exposure balance (unit 2), measured on the 17-photo test set and accepted as they stand:

- **Colored strips on window views, photos 001 and 003.** The fade at the edge of the cool-view correction shows up on the view. On 003, a blue and green strip runs along the left and bottom pane edges: at y=2150, 16 px inside the mask, a* -25.5 and b* +28.4, against about a* -7 and b* +8 from 60 px in. On 001, a yellow and green strip about 50 px wide (judged by eye) runs down the left pane edge.
- **Trim and wall streak, photo 009.** The same fade lands on trim and wall beside the right window and leaves a gray-white streak with a ragged edge. At y=2000, b* falls from 20.3 to 3.5 over about 60 px.
- **Floor check fails on 7 of 17 photos:** 003 (8.3%), 004 (12.1%), 006 (39.8%), 007 (30.9%), 008 (8.1%), 009 (27.9%), 012 (12.9%), against an 8% limit.
- **Photo 012's bright-surface share** is 1.51% on the saved file, over the 1% line where a photo gets listed.
