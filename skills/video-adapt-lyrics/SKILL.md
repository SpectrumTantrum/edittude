---
name: video-adapt-lyrics
description: Rewrite lyrics to fit an existing melody and video brief while preserving sung syllable slots, phrasing, rests, and meaning. Use for lyric adaptations and music-video covers.
metadata:
  source-role: "SVCAdapter"
  source-path: "environment/roles/svc/svc_adapter.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Adapt lyrics to an existing melody

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Make the lyric express the requested story while remaining singable on the supplied melody. Keep notes and timing fixed unless the brief explicitly permits musical changes.

## Inputs and tools

- Required: `reqs`, a lyric adaptation brief; `name`; and `analysis_path`, a score with original lyrics, melody, and timing.
- The portable analysis contains `name`, `language`, `duration_seconds`, and ordered `units`. Each unit has `id`, `kind`, `text`, `start`, `end`, and `notes`. A lyric unit represents one sung syllable/token; its notes contain `pitch`, `start`, and `end`. A rest has empty text and notes. All times are seconds from audio start.
- Establish the desired language, tone, must-keep wording, and the story or images the song should support. Infer ordinary stylistic choices from the brief.
- An agent can draft lyrics directly. Use an available pronunciation dictionary, grapheme-to-phoneme frontend, or singer preview to check syllables and stress. Missing audio synthesis does not block a text adaptation, but leaves sung quality unverified.

## Workflow

1. Read the full lyric and timed units. Build a phrase map with each phrase's syllable slots, stresses, rhyme, rests, and sustained notes. Keep a syllable tied across several notes as one unit.
2. Draft the complete adaptation around the video's story and emotional progression. Put important words on audible stressed positions. Prefer vowel sounds that can be held on long notes and leave room for consonants before the next onset.
3. Map each new sung syllable to an existing lyric unit. Preserve every rest and note interval. Check pronunciation in context, particularly names, numbers, abbreviations, and words with multiple readings.
4. Revise whole phrases when the meaning or fit fails. Check neighboring phrases for narrative continuity and rhyme after each revision. Use character counts only for a language/frontend where one character is verified to occupy one lyric slot.
5. Validate the unit count, phonetic fit, stresses, and all must-keep terms. If the brief cannot fit the available slots, identify the exact phrase and return a viable alternate wording. Do not silently pad with filler syllables or truncate words to force a count.
6. Write an adapted copy of the analysis. Change lyric text and language metadata as needed; preserve unit IDs, kinds, note pitches, and times. Preserve the original analysis and original lyric.
7. Read or sing the phrases against the melody, using a preview when available. Fix rushed diction and broken word boundaries before handing off.

## Handoff

Return:

- `adapted_lyrics`: readable lyrics with phrase line breaks.
- `analysis_path`: absolute path to the new analysis containing the adapted unit text and unchanged musical timing.
- `name`, `language`, and any unresolved pronunciation or fit issue.

Singing synthesis and lyric timing should consume the adapted `analysis_path`, so their token mapping remains identical. The readable lyric alone is insufficient to reconstruct a multilingual note alignment.

For legacy input with `text`, `notes`, `notes_duration`, and `input_type: word`, treat `AP` as one rest marker and ` | ` as the unit separator. First reconstruct the explicit units and verify tokenization. Preserve literal letters in words such as `CAP`; token markers must not be inferred by splitting arbitrary Latin text on `AP`.

## Verification

- Each adapted lyric unit fits the same sequential notes and interval as its source unit.
- Every phrase is meaningful, pronounced as intended, and consistent with the brief. Rhyme does not justify a factual or narrative error.
- Record whether the result received text-only, spoken, or sung review. Claim timing and diction quality only to the extent actually checked.
