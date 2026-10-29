# Listing Partner

## What it is

Listing Partner takes one rental unit's raw bracketed camera exposures and returns a listing package ready to post. The photographer drops the raw files into a folder and it goes: the best photos merged, window-pulled, balanced, tidied, labeled and in order, plus a listing description and social captions built on the unit's real facts. No Lightroom.

Built for Meta's Global AI Developer Hackathon (Indie track, solo), Oct 26 to Nov 4, 2026.

## Who it serves

- **Real estate photographers**, starting with Erik, who today merges brackets, draws window and exposure masks, and removes clutter by hand across Lightroom and Gemini for every listing.
- **Bokani Property Management Group's leasing and media work.** Bokani manages roughly 493 residential, commercial and HOA units in Metro Detroit and shoots its own listing media in-house. Today a vacant unit's photos go through manual HDR merging, culling, ordering and writing before a listing can go live. Every day a unit sits unlisted is lost rent for the owner.
- **Prospective renters.** They need photos that show the unit honestly (bright, clear, in a sensible walkthrough order) and a description whose facts are correct.
- **Property owners.** They want the unit listed fast and shown well.
- **Hackathon judges.** They weigh impact, creative use of Meta tooling, technical depth and the demo equally.

## What it does

1. **HDR merge.** Each bracket set (the same shot at several exposures) becomes one natural-looking photo where the window view and the dark corners are both visible.
2. **Window pulls and exposure balance.** SAM 3.1 finds every window, and the view inside it comes from the real darker brackets, so the outdoors is clear and true. Dark corners, hot floors and dim hallways are evened out automatically, the work a photographer does today with hand-drawn linear, radial and luminance masks. Real pixels only, never generated.
3. **Curate.** Muse Spark drops weak and duplicate shots, labels each room, and puts the best photos in walkthrough order.
4. **Tidy.** SAM 3.1 finds things a quick tidy would remove (trash bins, boxes, cords, hoses, packing plastic). Muse Image removes only those. It never touches walls, fixtures, flooring or damage. The untouched merged photo is always kept beside the tidied one.
5. **Write.** Muse Spark writes the listing description and social captions from the unit facts.
6. **Unit facts.** Beds, baths, square feet, rent and amenities come from Bokani's existing read-only AppFolio connector. That connector was built before the hackathon and is presented as an existing tool being plugged in.

Stretch, only if time allows: brush touch-up, where the photographer paints over anything the automatic tidy missed and Muse Image removes it inside the stroke only, with the same honesty audit.

## Why not just a phone and a general image model

Phones already make good HDR photos, and general image models can clean them up. That is not the whole job, and Listing Partner does not compete on the merge alone.
- A general image model regenerates the whole photo. It can quietly change fixtures, walls or damage, and nothing proves what it touched. Listing Partner edits only inside saved masks and proves, pixel by pixel, that nothing else changed.
- A phone gives one processed file per shot. A listing is a set: culled, labeled, ordered, checked for missing rooms, described accurately, and screened for fair housing problems. Listing Partner does the whole listing and checks its own work.
- Photographers who want to keep editing keep their latitude: a high bit-depth master is saved beside every finished JPEG.

## What it takes in

Any bracketed set, raw or JPEG. Raw brackets (Nikon NEF, Canon CR3, Sony ARW, DNG) give the best windows and the cleanest shadows. JPEG brackets work too, with a lower ceiling, and the difference is measured, not claimed. Tested on Nikon raw. Other raw formats are read through LibRaw and stay labeled untested until a second camera is actually run.

## What it does not do

- Schedule posts, or post anywhere automatically.
- Commercial listing formats.
- Hide, remove or soften damage, or change anything structural in a photo.
- Send tenant, applicant or owner data anywhere. Only public unit facts and Bokani's own photos go to Meta's API.

## The honesty rule, in Erik's words

An edit is allowed only if the photo still shows what the place would really look like after a physical cleanup, plus the weather. Allowed, always inside a saved mask and always listed: clutter a person could carry out in a day, and the sky on exterior shots (labeled "sky replaced"). Never allowed: repairs, damage, stains, permanent fixtures, walls, flooring, or anything that changes the property itself.

## Hard rules

- Every model call goes to Meta models (Muse Spark, SAM 3.1, Muse Image) through the Meta Model API, through one spend-capped function. The cap is $100. No Contributor models.
- The repo is public. No keys, tokens, names, phone numbers, emails or AppFolio data beyond public listing facts are ever committed.
- Only photos and data Bokani has rights to.
- The demo, README and submission present only what was built Oct 26 to Nov 4, 2026, and label anything older as existing.

## Done looks like

Erik drops one unit's bracket folder in, runs one command, and opens one page that shows the ordered, labeled, tidied photos, the description and the captions, ready to copy into a listing. Submission is due Wed Nov 4, 2026, 9:00 PM ET: public repo, three minute demo video, working product.
