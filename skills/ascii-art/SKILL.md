---
name: ascii-art
description: Create ASCII art from a user's description (animals, objects, scenes, banners). Use when they ask for ASCII art, text art, a figlet-style banner, or to draw something in the terminal.
version: 1.1.0
---

# ASCII art from a description

## When to use

User wants ASCII / text art: "draw a cat in ASCII", "ASCII art of a rocket", "banner that says HELLO", "snoopy", "girl dancing".

## How

1. Run `/skills/ascii-art/scripts/generate.py` with `run_script` and
   `args: {"description": "<their words>", "width": 56}`.
2. Put the **final** art in a fenced code block so spacing is preserved.
3. **Quality bar:** never reply with only a figlet banner or a boxed caption.
   If the script output is a banner, a `+---+` box, a stick-figure stub, or
   motifs that do not match the scene, **compose a custom scene** (~40–70
   columns) and use that as the reply (you may keep useful motifs).
4. Characters and named figures (Snoopy, Joe Cool, a baby, a dancer) need a
   custom drawing: pose, props, and setting — not a generic dog/house.
5. Do not call web search. Keep it G-rated unless they asked otherwise.
   No ANSI color unless asked.

## Judgement

- Short slogan / name only → banner letters are OK **plus** a small motif.
- Library hit that actually depicts the subject → script art is enough.
- Named character, emotion, or multi-part scene → always compose extra ASCII.
- Stack “on / under / with” vertically (subject above object).

## Example trigger

"ASCII art of a cat under the moon"
