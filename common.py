import io
import os
import subprocess

import discord
import requests

from dotenv import load_dotenv

load_dotenv()
poke_api_url = os.getenv('POKE_API_URL')

async def get_resized_gif(national_dex_number: int, is_shiny: bool, scale: int) -> tuple[discord.File, str]:
    response = requests.get(poke_api_url + '/pokemon/' + str(national_dex_number))
    response.raise_for_status()
    data = response.json()
    sprite_url = data['sprites']['other']['showdown']['front_shiny' if is_shiny else 'front_default']

    # Download GIF
    response = requests.get(sprite_url)
    gif_bytes = response.content

    # Upscale with gifsicle
    process = subprocess.Popen(
        ['gifsicle', '--no-warnings', '--scale', str(scale), '--colors', '256'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE
    )
    resized_bytes, _ = process.communicate(input=gif_bytes)

    # Wrap bytes in BytesIO so discord.File can read it
    resized_file = io.BytesIO(resized_bytes)

    return discord.File(fp=resized_file, filename='pokemon.gif'), str.capitalize(data['name'])