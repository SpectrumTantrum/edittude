---
name: iterate-recut
description: Recut after QC. Load when the render failed review, feels long, or they asked to try again.
---

# iterate-recut

Change the EDL. Do not grade your way out of a bad cut.

```
edittude media recut edl.json --out edl2.json --drop-longest
```

A second recut onto the same `edl2.json` needs `edittude media --force recut`.

Then open the new EDL. Drop a duplicate wide. Shorten the longest hold. If loudness failed, remake the mix only with `edittude media --force mix`. Otherwise assemble and `finish` again:

```
edittude media --force assemble edl2.json --out picture.mp4
edittude media --force finish picture.mp4 edl2.json --out final.mp4
```

QC once more.

Stop after one honest recut unless they asked to keep going.

A reply that only lists commands is a failed turn. The new file has to exist.

Completion: a new `final.mp4` and a QC that you can explain.
