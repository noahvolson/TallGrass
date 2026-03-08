import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

def validate_emoji_map():
    pokemon_count = int(os.getenv("POKEMON_COUNT", 0))
    if not pokemon_count:
        print("Error: POKEMON_COUNT environment variable not set")
        sys.exit(1)

    with open("emoji_map.json") as f:
        emoji_map = json.load(f)

    missing = []
    for i in range(1, pokemon_count + 1):
        if f"pokemon_{i}" not in emoji_map:
            missing.append(f"pokemon_{i}")
        if f"pokemon_{i}_shiny" not in emoji_map:
            missing.append(f"pokemon_{i}_shiny")

    if missing:
        print(f"Missing {len(missing)} entries:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)
    else:
        print(f"✓ All {pokemon_count} Pokémon (+ shinies) validated successfully")

validate_emoji_map()