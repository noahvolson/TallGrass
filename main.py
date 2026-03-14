import io
import json
import logging
import os
import random
import re
import subprocess
import unicodedata

import database
import catch_view
import trade_view

import discord
import requests

from datetime import datetime, timedelta
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Init environment variables
load_dotenv()
token                       = os.getenv('DISCORD_TOKEN')
poke_api_url                = os.getenv('POKE_API_URL')
pokemon_count               = int(os.getenv('POKEMON_COUNT'))
log_level                   = int(os.getenv('LOG_LEVEL'))
rare_chance_percent         = int(os.getenv('RARE_CHANCE_PERCENT'))
shiny_chance_percent        = int(os.getenv('SHINY_CHANCE_PERCENT'))
regular_chance_percent      = int(os.getenv('REGULAR_CHANCE_PERCENT'))
shiny_spawn_one_in          = int(os.getenv('SHINY_SPAWN_ONE_IN'))
min_seconds_to_spawn        = int(os.getenv('MIN_SECONDS_TO_SPAWN'))
max_seconds_to_spawn        = int(os.getenv('MAX_SECONDS_TO_SPAWN'))

# Map of emoji_name -> emoji_id used to display a user's box
with open('emoji_upload/emoji_map.json', 'r') as f:
    emoji_map = json.load(f)

# Init logging to discord.log
logger = logging.getLogger('TallGrass')
logger.setLevel(log_level)

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

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


# Extend commands.Bot to schedule Pokémon spawning
class TallGrass(commands.Bot):
    channel = None
    start_active_hour: int
    end_active_hour: int

    async def spawn_pokemon(self):

        # Roll for shiny
        is_shiny = random.randint(1, shiny_spawn_one_in) == 1

        # Pick a random Pokémon
        spawned_pokemon_id = random.randint(1, pokemon_count)

        # Determine catch percent from the species endpoint
        response = requests.get(poke_api_url + '/pokemon-species/' + str(spawned_pokemon_id))
        data = response.json()

        if data['is_legendary'] or data['is_mythical']:
            spawned_pokemon_catch_percent = rare_chance_percent
        elif is_shiny:
            spawned_pokemon_catch_percent = shiny_chance_percent
        else:
            spawned_pokemon_catch_percent = regular_chance_percent

        file, spawned_pokemon_name = await get_resized_gif(spawned_pokemon_id, is_shiny, 2)

        shiny_emoji = ' :sparkles: ' if is_shiny else ''
        embed = discord.Embed(title=f'Wild {shiny_emoji}{spawned_pokemon_name}{shiny_emoji} appears!', color=discord.Color.dark_green())
        embed.set_image(url='attachment://pokemon.gif')

        view = catch_view.CatchView(
            log_handler=handler,
            spawned_pokemon_id=spawned_pokemon_id,
            spawned_pokemon_name=spawned_pokemon_name,
            spawned_pokemon_catch_percent=spawned_pokemon_catch_percent,
            is_shiny=is_shiny
        )

        logger.info(f"Spawning {'shiny ' if is_shiny else ''}{spawned_pokemon_name} in channel: {self.channel.name}")
        message = await self.channel.send(embed=embed, file=file, view=view)
        view.message = message

    @tasks.loop(seconds=1) # Updated on each task run
    async def spawner_task(self):
        if not self.channel:
            return

        seconds = random.randint(min_seconds_to_spawn, max_seconds_to_spawn)

        now = datetime.now()

        if self.start_active_hour <= self.end_active_hour:
            # Active window is a normal range e.g. 8–22
            in_downtime = now.hour < self.start_active_hour or now.hour >= self.end_active_hour
        else:
            # Active window wraps midnight e.g. 22–6
            in_downtime = self.end_active_hour <= now.hour < self.start_active_hour

        if in_downtime:
            next_active = now.replace(hour=self.start_active_hour, minute=0, second=0, microsecond=0)

            if next_active < now:
                next_active += timedelta(days=1)

            seconds_until_active = int((next_active - now).total_seconds())
            total_seconds = seconds_until_active + seconds  # wake up + random delay before first spawn

            next_spawn_time = next_active + timedelta(seconds=seconds)
            logger.info(
                f'Skipping spawn during downtime. Next active window starts at '
                f'{next_active}, scheduling wake-up in {seconds_until_active}s '
                f'(+{seconds}s random delay). Next spawn at {next_spawn_time}.'
            )

            self.spawner_task.change_interval(seconds=total_seconds)
            return

        await self.spawn_pokemon()

        logger.info(f'Next spawn will occur {seconds} seconds from now at {datetime.now() + timedelta(seconds=seconds)}')
        self.spawner_task.change_interval(seconds=seconds)

# Init TallGrass bot
intents = discord.Intents.default()
bot = TallGrass(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    logger.info(f'{bot.user.name} is now online with {len(synced)} active commands')

# Define bot commands
@bot.tree.command(name='init', description='Initialize TallGrass')
@discord.app_commands.default_permissions(administrator=True)
async def init(interaction: discord.Interaction):
    try:
        await database.init_db()
    except Exception as e:
        logger.error(f'Failed to initialize database: {e}')
        interaction.response.send_message('Failed to initialize database. Check log.')

    await interaction.response.send_message(f'Tallgrass initialized!')

@bot.tree.command(name='start', description='Start spawning Pokémon in this channel. Accepts an active window in military time')
@discord.app_commands.default_permissions(administrator=True)
async def start(interaction: discord.Interaction, start_active_hour: int | None = 0, end_active_hour: int | None = 23):
    if bot.spawner_task.is_running():
        await interaction.response.send_message(f'Spawning already active in {interaction.channel.name}')
        return

    bot.channel = interaction.channel
    bot.start_active_hour = start_active_hour
    bot.end_active_hour = end_active_hour
    bot.spawner_task.change_interval(seconds=1) # Reset interval if we had already started
    bot.spawner_task.start()

    logger.info(f'{interaction.user.display_name} activated spawning in channel: {interaction.channel.name}')
    await interaction.response.send_message(f'Spawning Pokémon in {interaction.channel.name}...')

# Define bot commands
@bot.tree.command(name='stop', description='Stop spawning Pokémon in this channel')
@discord.app_commands.default_permissions(administrator=True)
async def stop(interaction: discord.Interaction):
    bot.spawner_task.cancel()
    logger.info(f'{interaction.user.display_name} deactivated spawning in channel: {interaction.channel.name}')
    await interaction.response.send_message(f'Spawning deactivated in {interaction.channel.name}')

# Helper for box()
def get_emoji(national_dex_number: int, is_shiny: bool, name: str) -> str:
    sanitized_name = sanitize_emoji_name(name)
    key = 'pokemon_' + str(national_dex_number) + ("_shiny" if is_shiny else "")
    emoji_id = emoji_map.get(key)

    if emoji_id is None:
        raise KeyError(f"No emoji found for Pokémon #{national_dex_number}{' (shiny)' if is_shiny else ''}")

    return f"<:{'shiny_' if is_shiny else ''}{sanitized_name}_{national_dex_number}:{emoji_id}>"

def sanitize_emoji_name(name: str) -> str:
    replacements = {
        '♀': '_f',
        '♂': '_m',
        ' ': '_',
        '-': '_',
        ':': '_',
    }

    # Apply explicit mappings
    for char, replacement in replacements.items():
        name = name.replace(char, replacement)

    # Decompose accented chars (é -> e + combining accent)
    name = unicodedata.normalize('NFKD', name)

    # Keep only ASCII alphanumeric and underscores, drop everything else
    name = ''.join(
        c for c in name
        if c == '_' or c.isascii() and c.isalnum()
    )

    # Collapse multiple underscores and strip edges
    name = re.sub(r'_+', '_', name).strip('_')

    return name.lower()

@bot.tree.command(name='box', description='View your pokemon collection')
async def box(interaction: discord.Interaction, user: discord.Member = None):

    view_user = user if user else interaction.user

    pokemon_list = await database.get_all_user_pokemon(view_user.id, interaction.guild_id)
    emojis = [get_emoji(p['national_dex_number'], p['is_shiny'], p['name']) for p in pokemon_list]
    num_columns = 4 # More than 4 columns and the mobile view will be squished
    rows = [emojis[i:i+num_columns] for i in range(0, len(emojis), num_columns)]
    embed = discord.Embed(
        title=f"{view_user.name}'s Box",
        description='\n\n'.join('# ' + '\u2000\u2000'.join(row) for row in rows),
        color=discord.Color.purple()
    )
    embed.set_thumbnail(url=view_user.display_avatar.url)

    await interaction.response.send_message(embed=embed)

def parse_pokemon(pokemon: str) -> tuple[int, bool]:
    # Parse a pokemon token like 'shiny_bulbasaur_1' or 'ninetales_38'
    parts = pokemon.split('_')
    is_shiny = parts[0].lower() == 'shiny'
    dex_num = int(parts[-1])  # last element is always the dex number
    return dex_num, is_shiny

@bot.tree.command(name='trade', description='Post a trade offer')
async def trade(interaction: discord.Interaction, offer_pokemon: str, want_pokemon: str):
    await interaction.response.defer(ephemeral=True) # DB checking can take a bit
    try:
        offer_dex_num, offer_is_shiny = parse_pokemon(offer_pokemon)
        want_dex_num, want_is_shiny = parse_pokemon(want_pokemon)
    except ValueError as e:
        await interaction.followup.send('Example usage: `/trade offer_pokemon:raichu_26 want_pokemon:shiny_ninetales_38`', ephemeral=True)
        return

    own_offer = await database.user_has_pokemon(interaction.user.id, interaction.guild_id, offer_dex_num, offer_is_shiny)
    if not own_offer:
        await interaction.followup.send(f'You do not own {offer_pokemon}', ephemeral=True)
        return

    file, name = await get_resized_gif(offer_dex_num, offer_is_shiny, 2)
    shiny_emoji = ' :sparkles: ' if offer_is_shiny else ''
    offer_display_name = f'{shiny_emoji}{name}{shiny_emoji}'
    embed = discord.Embed(title=f"{interaction.user.name}'s {offer_display_name}", color=discord.Color.blue())
    embed.set_image(url='attachment://pokemon.gif')
    await interaction.channel.send(content='# Trade Offer!', embed=embed, file=file)

    file, name = await get_resized_gif(want_dex_num, want_is_shiny, 2)
    shiny_emoji = ' :sparkles: ' if want_is_shiny else ''
    want_display_name = f'{shiny_emoji}{name}{shiny_emoji}'
    embed = discord.Embed(title=f'For {want_display_name}',color=discord.Color.blue())
    embed.set_image(url='attachment://pokemon.gif')
    view = trade_view.TradeView(
        log_handler=handler,
        offer_user_id=interaction.user.id,
        offer_dex_num=offer_dex_num,
        offer_is_shiny=offer_is_shiny,
        want_dex_num=want_dex_num,
        want_is_shiny=want_is_shiny,
        offer_display_name=offer_display_name,
        want_display_name=want_display_name
    )
    message = await interaction.channel.send(embed=embed, file=file, view=view)
    view.message = message

    await interaction.delete_original_response()
    logger.info(f'{interaction.user.id} posted a trade offer: {offer_pokemon} for {want_pokemon}')


# Now we're ready to spin up the bot!
bot.run(token, log_handler=handler, log_level=log_level)