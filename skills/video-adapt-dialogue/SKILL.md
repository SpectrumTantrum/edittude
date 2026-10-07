---
name: video-adapt-dialogue
description: Adapt reference material into a two-performer comedy dialogue or Chinese crosstalk script with stable speaker roles and delivery cues.
metadata:
  source-role: "CrossTalkAdapter"
  source-path: "environment/roles/cross_talk/cross_talk_adapter.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Adapt comedy dialogue

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Rework a reference script as a performed exchange, with a comic lead who drives the premise and a partner whose responses make the jokes work.

## Inputs

- Reference script and requested changes, audience, language, style, and duration.
- Two performer identities and roles. For xiangsheng, distinguish the comic lead, `逗哏`, from the responding partner, `捧哏`.
- Optional existing segment IDs and supported delivery tones. Voice asset directories can provide a mapping, but speaker identity must not depend on directory names.

## Workflow

1. Read the whole reference and identify premises, reveals, callbacks, and cultural references. Establish what the audience must know before each punchline.
2. Assign the lead and partner distinct dramatic functions. The partner can question, misunderstand, challenge, or redirect; avoid merely echoing the lead's last sentence.
3. Adapt the material into connected turns. For a Chinese crosstalk request, use appropriate Chinese phrasing and interactive rhythm; for another dialogue format, follow that requested style rather than forcing a language or tradition.
4. Localize references while retaining their comic function. Preserve facts the request treats as factual, and keep adapted fictional premises recognizable as part of the performance.
5. Give every turn a stable `id`, explicit `speaker`, tone, and spoken `text`. Preserve upstream scene IDs; record parent IDs if a scene splits into multiple turns.
6. Use the source tones `Natural`, `Confused`, and `Emphatic` or supported equivalents. Let tone follow the exchange. The original discouraged more than two identical consecutive tones; treat variation as an editorial cue, not a quota that overrides meaning.
7. Read the dialogue continuously to check turn order, setup/payoff, and plausible interruptions or pauses. Label duration estimates as estimates. Save the title separately and keep directions out of spoken text.

## Output and handoff

Return a script artifact such as:

```json
{
  "title": "The endless update",
  "speakers": {"lead": "Comic lead", "partner": "Responding partner"},
  "segments": [
    {"id": "turn-01", "speaker": "lead", "tone": "Natural", "text": "My computer is learning patience."},
    {"id": "turn-02", "speaker": "partner", "tone": "Confused", "text": "By teaching it to you?"}
  ]
}
```

For plain-text consumers, use `[Tone] Speaker: text`, keeping the title distinct. Pass the explicit speaker mapping to synthesis. Leave `start` and `end` unset or null until the audio is measured. Optional audience cues are metadata and require actual reaction assets later.

## Completion checks

- Every turn belongs to a declared speaker, has a unique stable ID, and contains speakable text.
- Both performers contribute to the exchange; punchlines have their required setups and the chosen cultural adaptation remains understandable.
- The requested language, style, and approximate duration are met, with title and stage directions separate from dialogue.

## Source adaptation

The original adapted English stand-up into Chinese crosstalk and derived performer names from reference directory basenames. This skill preserves the role-based comedy method while supporting explicit identities and the user's chosen language.
