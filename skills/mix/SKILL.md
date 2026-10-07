---
name: mix
description: Voiceover, music, ducking, loudnorm. Load when adding VO or a music bed, or when the mix is wrong.
---

# mix

Ambient stays. Voice sits on top. Music is a bed, not a second narrator.

```
edittude media mix picture.mp4 --out mixed.mp4 --vo VO.m4a
edittude media --force mix picture.mp4 --out mixed.mp4 --vo VO.m4a --music BED.wav --music-db -22
```

`finish` does mix plus grade plus title in one encode. Use that when you already have an EDL.

Target about -16 LUFS, true peak under -1.5 dB. If QC says the mix is quiet or slammed, run `edittude media --force mix` again before you recut picture.

Completion: a file whose voice is readable and whose world noise is still there.
