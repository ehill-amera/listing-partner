# Listing Partner

## What it is

Listing Partner takes one rental unit's raw bracketed camera exposures and returns a listing package ready to post. One folder of brackets in, one folder out: the best photos merged, tidied, labeled and in order, plus a listing description and social captions built on the unit's real facts.

Built for Meta's Global AI Developer Hackathon (Indie track, solo), Oct 26 to Nov 4, 2026.

## Who it serves

- **Bokani Property Management Group's leasing and media work.** Bokani manages roughly 493 residential, commercial and HOA units in Metro Detroit and shoots its own listing media in-house. Today a vacant unit's photos go through manual HDR merging, culling, ordering and writing before a listing can go live. Every day a unit sits unlisted is lost rent for the owner.
- **Prospective renters.** They need photos that show the unit honestly (bright, clear, in a sensible walkthrough order) and a description whose facts are correct.
- **Property owners.** They want the unit listed fast and shown well.
- **Hackathon judges.** They weigh impact, creative use of Meta tooling, technical depth and the demo equally.

## What it does

1. **HDR merge.** Each bracket set (the same shot at several exposures) becomes one natural-looking photo where the window view and the dark corners are both visible.
2. **Curate.** Muse Spark drops weak and duplicate shots, labels each room, and puts the best photos in walkthrough order.
3. **Tidy.** SAM 3.1 finds things a quick tidy would remove (trash bins, boxes, cords, hoses, packing plastic). Muse Image removes only those. It never touches walls, fixtures, flooring or damage. The untouched merged photo is always kept beside the tidied one.
4. **Write.** Muse Spark writes the listing description and social captions from the unit facts.
5. **Unit facts.** Beds, baths, square feet, rent and amenities come from Bokani's existing read-only AppFolio connector. That connector was built before the hackathon and is presented as an existing tool being plugged in.

Stretch, only if time allows: a vertical walkthrough tour from real footage, with SAM 3.1 keeping each room framed.

## What it does not do

- Schedule posts, or post anywhere automatically.
- Commercial listing formats.
- Hide, remove or soften damage, or change anything structural in a photo.
- Send tenant, applicant or owner data anywhere. Only public unit facts and Bokani's own photos go to Meta's API.

## Hard rules

- Every model call goes to Meta models (Muse Spark, SAM 3.1, Muse Image) through the Meta Model API, through one spend-capped function. The cap is $100. No Contributor models.
- The repo is public. No keys, tokens, names, phone numbers, emails or AppFolio data beyond public listing facts are ever committed.
- Only photos and data Bokani has rights to.
- The demo, README and submission present only what was built Oct 26 to Nov 4, 2026, and label anything older as existing.

## Done looks like

Erik drops one unit's bracket folder in, runs one command, and opens one page that shows the ordered, labeled, tidied photos, the description and the captions, ready to copy into a listing. Submission is due Wed Nov 4, 2026, 9:00 PM ET: public repo, three minute demo video, working product.
