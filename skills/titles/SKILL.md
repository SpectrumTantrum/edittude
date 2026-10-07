---
name: titles
description: Titles and captions. Load when burning an opening card, lower title, or SRT.
---

# titles

One card. Short. Then get out. No lower-third spam.

This machine's ffmpeg has no `drawtext` and no `subtitles` filter. The working path is a title PNG overlaid by `titles` or `finish`. `captions` will refuse unless ffmpeg was built with libass. Do not invent a drawtext or subtitles graph.

```
edittude media titles picture.mp4 --out titled.mp4 --title "A DAY OUT" --subtitle "city / date"
```

A second card onto the same output needs `edittude media --force titles`.

Set `title` and `subtitle` on the EDL and use `finish` when you still have grade and mix to do.

Title and subtitle are uppercased before drawing. Only A-Z, 0-9, space, `-`, `'`, `.` and `/` have glyphs; anything else raises before the card is written. Punctuate around that, or drop the character.

Completion: the words are readable on a 1080p frame and gone by about 3.5s.
