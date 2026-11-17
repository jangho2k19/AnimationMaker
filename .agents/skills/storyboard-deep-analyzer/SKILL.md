---
name: storyboard-deep-analyzer
description: >-
  Deep analysis and structural blueprint framework for transforming raw story ideas,
  narrative prose, jokes/fables, and imported screenplay/storyboard texts into
  cinematic multi-scene animated storyboards in AniStory AI.
---

# Storyboard Deep Analyzer & Director Skill

Use this skill when designing, analyzing, or improving the **Generate Storyboard** stage (`ScriptAgent.deep_analyze_story_input`, `ScriptAgent._build_story_prompt`, and `ScriptAgent.parse_imported_storyboard` in `backend/agents/script_agent.py`).

## 1. Deep Idea Analysis Pipeline (`deep_analyze_story_input`)

Before generating scenes from a user's `idea`, decompose the input across five dimensions:

1. **Input Classification**:
   - `short_concept`: 1–30 words seed premise -> requires full 3-act expansion with invented causal beats and character names.
   - `narrative_story_with_dialogue`: Story prose containing quoted lines (`"..."`, `“...”`) or dash dialogue turns (`- ...`, `– ...`) -> requires **100% faithful adaptation** of every canonical character, dialogue turn, and final punchline.
   - `narrative_prose`: Multi-sentence story without explicit quotes -> requires beat segmentation and natural character dialogue synthesis where appropriate.
   - `structured_storyboard`: Pre-formatted `Scene 1` / `Cảnh 1` / JSON / Markdown table -> route to `parse_imported_storyboard` while enriching missing visual/acting prompts.

2. **Genre & Director Skill Routing**:
   - `comedy_punchline_master`: Satire, jokes, husband/wife banter, folk tales with a witty twist (`truyện cười`, `dân gian trào phúng`). Prioritizes conversational setup, reaction shots, and an unhurried final punchline scene.
   - `dialogue_drama_director`: Character-driven conversations and emotional confrontations. Uses Shot-Reverse-Shot (`speaker_focus`) camera grammar.
   - `comic_graphic_novel`: When `art_style == "comic"`. Reserves upper frame headroom for speech balloons and embeds explicit `Comic speech bubble from [Speaker]: "..."` cues in `visual_prompt`.
   - `cinematic_storyteller`: Studio Ghibli / Pixar 3-act emotional journey with visual motifs and atmospheric world-building.
   - `viral_hook_retention`: Fast-paced Shorts/Reels storytelling with a 1.5-second visual hook in Scene 1.

3. **Character & Visual Consistency Blueprint**:
   - Extract all named characters and role archetypes from the input.
   - Assign immutable visual tokens (age, hairstyle, facial expression, signature outfit, key prop) so every scene's `visual_prompt` maintains identical character appearance.

4. **Beat-by-Beat Scene Allocation**:
   - Map story sentences and extracted dialogues chronologically across scenes so each dialogue exchange or plot turn gets its own dedicated scene beat without crowding or skipping the ending punchline.

## 2. Multi-Format Storyboard Input Parsing (`parse_imported_storyboard`)

Support all common screenplay and storyboard formats pasted by users:
- Raw or fenced JSON (`{"scenes": [...]}` or `[...]`)
- Numbered / headed scenes (`Scene 1:`, `Cảnh 1:`, `### Scene 1`, `**Cảnh 1**`, `Panel 1:`, `Shot 1:`, `[00:00 - 00:08]`)
- Markdown tables (`| Scene | Visual | Narration / Dialogue |`)
- Inline speaker dialogues (`Speaker: "Line"`, `- Speaker (tone): Line`) as well as ALL-CAPS screenplay blocks
- Labeled fields in English and Vietnamese (`Visual` / `Hình ảnh` / `Prompt ảnh`, `Acting` / `Video` / `Chuyển động`, `Narration` / `Lời dẫn` / `Thuyết minh`, `Dialogue` / `Lời thoại`)
