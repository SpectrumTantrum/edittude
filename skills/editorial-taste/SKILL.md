---
name: editorial-taste
description: Shot selection, pacing, and structure. Load when writing an EDL, choosing coverage, or deciding what to drop.
---

# editorial-taste

You are picking a cut, not listing options.

## House style

Cut the day, don't illustrate it. Chronology is the spine unless the brief names another structure. One idea per shot. Get in late, get out early.

Alternate scale: wide, person, detail, person, wide. Two wides in a row need a reason.

Cap a hold at about 5 seconds. Screen recordings and static inserts cap at 4. iPhone starts have a button. Drop ~0.12s off the head and ~0.08s off the tail.

Hard cuts. A dissolve means you did not find the join.

If a voiceover exists, picture serves it. Fit duration to the VO. Keep ambient, ducked. Mute-and-replace is a slideshow.

## Plan

```
edittude media plan INVENTORY.json --out edl.json --title "TITLE" --aspect source --look warm
```

Then open `edl.json` and rewrite reasons until each event earns its place. Drop a duplicate. Shorten a screen. Move a detail next to the wide it explains.

`plan` refuses to overwrite an EDL you already edited. Replanning from scratch is `edittude media --force plan`; anything else, edit the JSON.

Completion: an EDL you would defend, with `in`/`out`/`reason` on every event, duration within ~1s of the VO or the brief.
