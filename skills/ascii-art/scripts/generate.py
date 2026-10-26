"""Generate ASCII art from a short description (args.description)."""
import re
import textwrap

desc = (args.get("description") or args.get("prompt") or "").strip()
if not desc:
    result = {"error": "pass description"}
    print("error: pass description")
    raise SystemExit(0)

width = int(args.get("width") or 56)
low = desc.lower()

MOTIFS = {
    "cat": r"""
 /\_/\
( o.o )
 > ^ <
""",
    "dog": r"""
  / \__
 (    @\___
 /         O
/   (_____/
/_____/   U
""",
    "snoopy": r"""
      ,-~~-.__
     /        ~-.
    |  o    o    \
     \     -     |
      \   ___   /
       `-------'
          ||||
""",
    "joe-cool": r"""
         .--.
        / ## \
       |  o o |
        \  _ /
         `--'
        /    \
       | ____ |
       | |  | |
       | |__| |
        \    /
         |  |
        /    \
       |______|
""",
    "baby": r"""
      .---.
     /     \
    |  T T  |
     \  o  /
      \_-_/
      /   \
     |_____|
""",
    "girl": r"""
        o
       /|\
      / | \
        |
       / \
      /   \
""",
    "dancer": r"""
       \ o /
        \|/
         |
        / \
       *   *
""",
    "fish": r"""
   ><(((º>
""",
    "heart": r"""
  .:::.   .:::.
 :::::::.:::::::
 :::::::::::::::
  ':::::::::::'
    ':::::::'
      ':::'
""",
    "star": r"""
      .
     ,O,
    ,OOO,
ooOOOOOOOOoo
  `OOOOO'
   OOOO
""",
    "moon": r"""
    .---.
   /     \
  |   )   |
   \     /
    '---'
""",
    "sun": r"""
    \ | /
     \*/
  --- O ---
     /*\
    / | \
""",
    "rocket": r"""
     /\
    /  \
   |    |
   |NASA|
   |    |
  /|    |\
 / |    | \
     ^^
""",
    "house": r"""
    /\
   /  \
  /____\
  | [] |
  |    |
  |____|
""",
    "doghouse": r"""
   _______________
  /               \
 /_________________\
 |                 |
 |_________________|
""",
    "tree": r"""
    /\
   /  \
  /    \
 /______\
    ||
    ||
""",
    "flower": r"""
    (@)
     |
   \ | /
    \|/
     |
""",
    "coffee": r"""
   ( (
    ) )
 ........
 |      |]
 \      /
  `----'
""",
    "robot": r"""
  [o_o]
  /| |\
   d b
""",
    "ghost": r"""
  .-.
 (o o)
 | O |
 |   |
 '~~~'
""",
    "dragon": r"""
                \||/
                |  @___oo
      /\  /\   / (__,,,,|
     ) /^\) ^\/ _)
     )   /^\/   _)
     )   _ /  / _)
 /\  )/\/ ||  | )_)
<  >      |(,,) )__)
 ||      /    \)___)\
 | \____(      )___) )___
  \______(_______;;; __;;;
""",
    "boat": r"""
     /\
    /  \
    |  |
~~~~|~~|~~~~
 \________/
""",
    "mountain": r"""
      /\
     /  \  /\
    /    \/  \
   /          \
""",
    "cloud": r"""
     .--.
  .-(    ).
 (___.__)__)
""",
    "tears": r"""
      | |
      | |
      v v
""",
}

ALIASES = {
    "kitten": "cat",
    "kitty": "cat",
    "puppy": "dog",
    "beagle": "snoopy",
    "peanuts": "snoopy",
    "ship": "boat",
    "sail": "boat",
    "space": "rocket",
    "love": "heart",
    "night": "moon",
    "sunny": "sun",
    "forest": "tree",
    "home": "house",
    "crying": "tears",
    "cry": "tears",
    "tear": "tears",
    "dancing": "dancer",
    "dance": "dancer",
    "cool": "joe-cool",
    "sunglasses": "joe-cool",
}

FONT = {
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "B": ["#### ", "#   #", "#### ", "#   #", "#### "],
    "C": [" ####", "#    ", "#    ", "#    ", " ####"],
    "D": ["#### ", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#### ", "#    ", "#####"],
    "F": ["#####", "#    ", "#### ", "#    ", "#    "],
    "G": [" ####", "#    ", "#  ##", "#   #", " ####"],
    "H": ["#   #", "#   #", "#####", "#   #", "#   #"],
    "I": [" ### ", "  #  ", "  #  ", "  #  ", " ### "],
    "J": ["  ###", "   # ", "   # ", "#  # ", " ##  "],
    "K": ["#   #", "#  # ", "###  ", "#  # ", "#   #"],
    "L": ["#    ", "#    ", "#    ", "#    ", "#####"],
    "M": ["#   #", "## ##", "# # #", "#   #", "#   #"],
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", " ### "],
    "P": ["#### ", "#   #", "#### ", "#    ", "#    "],
    "Q": [" ### ", "#   #", "# # #", "#  # ", " ## #"],
    "R": ["#### ", "#   #", "#### ", "#  # ", "#   #"],
    "S": [" ####", "#    ", " ### ", "    #", "#### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  "],
    "U": ["#   #", "#   #", "#   #", "#   #", " ### "],
    "V": ["#   #", "#   #", "#   #", " # # ", "  #  "],
    "W": ["#   #", "#   #", "# # #", "## ##", "#   #"],
    "X": ["#   #", " # # ", "  #  ", " # # ", "#   #"],
    "Y": ["#   #", " # # ", "  #  ", "  #  ", "  #  "],
    "Z": ["#####", "   # ", "  #  ", " #   ", "#####"],
    "0": [" ### ", "#   #", "# # #", "#   #", " ### "],
    "1": ["  #  ", " ##  ", "  #  ", "  #  ", " ### "],
    "2": [" ### ", "#   #", "  ## ", " #   ", "#####"],
    "3": ["#### ", "    #", " ### ", "    #", "#### "],
    "4": ["#  # ", "#  # ", "#####", "   # ", "   # "],
    "5": ["#####", "#    ", "#### ", "    #", "#### "],
    "6": [" ### ", "#    ", "#### ", "#   #", " ### "],
    "7": ["#####", "   # ", "  #  ", " #   ", "#    "],
    "8": [" ### ", "#   #", " ### ", "#   #", " ### "],
    "9": [" ### ", "#   #", " ####", "    #", " ### "],
    " ": ["     ", "     ", "     ", "     ", "     "],
    "!": ["  #  ", "  #  ", "  #  ", "     ", "  #  "],
    "?": [" ### ", "#   #", "  ## ", "     ", "  #  "],
}


def banner(text):
    text = re.sub(r"[^A-Za-z0-9 !?]", "", text.upper())[:12]
    if not text:
        return ""
    rows = [""] * 5
    for ch in text:
        glyph = FONT.get(ch, FONT["?"])
        for i, line in enumerate(glyph):
            rows[i] += line + " "
    return "\n".join(r.rstrip() for r in rows)


def clean(art):
    return textwrap.dedent(art).strip("\n")


def pick_keys():
    keys = []
    for key in sorted(MOTIFS, key=len, reverse=True):
        token = key.replace("-", " ")
        if re.search(r"\b" + re.escape(token) + r"s?\b", low):
            keys.append(key)
    for alias, key in ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"s?\b", low) and key not in keys:
            keys.append(key)
    if "snoopy" in keys:
        keys = [k for k in keys if k != "dog"]
    if "doghouse" in keys:
        keys = [k for k in keys if k != "house"]
    if "dancer" in keys:
        keys = [k for k in keys if k != "girl"]
    if "snoopy" in low and ("house" in low or "doghouse" in low):
        if "doghouse" not in keys:
            keys.append("doghouse")
        keys = [k for k in keys if k != "house"]
    if "joe" in low and "cool" in low:
        if "joe-cool" not in keys:
            keys.insert(0, "joe-cool")
        keys = [k for k in keys if k != "snoopy"]
    # subject before setting
    order = ["joe-cool", "snoopy", "baby", "dancer", "girl", "cat", "dog", "tears", "doghouse", "house"]
    keys.sort(key=lambda k: order.index(k) if k in order else 50)
    return keys[:4]


picked_keys = pick_keys()
picked = [clean(MOTIFS[k]) for k in picked_keys]
words = desc.split()

if picked:
    if any(w in low for w in ("on", "under", "above")) and len(picked) >= 2:
        art = "\n".join(picked)
    else:
        art = "\n\n".join(picked)
elif len(words) <= 3:
    art = banner(desc)
else:
    art = clean(
        r"""
        o
       /|\
        |
       / \
"""
    )

print(art)
result = {"description": desc, "art": art, "motifs": picked_keys}
