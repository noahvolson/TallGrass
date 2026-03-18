import json
import logging
import os
import random
import re
import unicodedata

import common
import database

import discord
import requests

from datetime import datetime, timedelta
from discord.ext import commands, tasks
from dotenv import load_dotenv
from views.catch_view import CatchView
from views.trade_view import TradeView
from views.multi_trade_view import MultiTradeView
from views.evolution_view import EvolutionView

# Init environment variables
load_dotenv()
token                       = os.getenv('DISCORD_TOKEN')
poke_api_url                = os.getenv('POKE_API_URL')
notification_role_name      = os.getenv('NOTIFICATION_ROLE_NAME')
pokemon_count               = int(os.getenv('POKEMON_COUNT'))
log_level                   = int(os.getenv('LOG_LEVEL'))
rare_chance_percent         = int(os.getenv('RARE_CHANCE_PERCENT'))
shiny_chance_percent        = int(os.getenv('SHINY_CHANCE_PERCENT'))
regular_chance_percent      = int(os.getenv('REGULAR_CHANCE_PERCENT'))
shiny_spawn_one_in          = int(os.getenv('SHINY_SPAWN_ONE_IN'))
min_seconds_to_spawn        = int(os.getenv('MIN_SECONDS_TO_SPAWN'))
max_seconds_to_spawn        = int(os.getenv('MAX_SECONDS_TO_SPAWN'))
rare_candy_emoji_id         = int(os.getenv('RARE_CANDY_EMOJI_ID'))

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

        file, spawned_pokemon_name = await common.get_resized_gif(spawned_pokemon_id, is_shiny, 2)

        shiny_emoji = ' :sparkles: ' if is_shiny else ''
        embed = discord.Embed(title=f'Wild {shiny_emoji}{spawned_pokemon_name}{shiny_emoji} appears!', color=discord.Color.dark_green())
        embed.set_image(url='attachment://pokemon.gif')

        view = CatchView(
            log_handler=handler,
            spawned_pokemon_id=spawned_pokemon_id,
            spawned_pokemon_name=spawned_pokemon_name,
            spawned_pokemon_catch_percent=spawned_pokemon_catch_percent,
            is_shiny=is_shiny
        )

        logger.info(f"Spawning {'shiny ' if is_shiny else ''}{spawned_pokemon_name} in channel: {self.channel.name}")

        role = discord.utils.get(self.channel.guild.roles, name=notification_role_name)
        message = await self.channel.send(content=f'<@&{role.id}>', embed=embed, file=file, view=view)
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
        await interaction.response.send_message('Failed to initialize database. Check log.')
        return

    existing = discord.utils.get(interaction.guild.roles, name=notification_role_name)
    if not existing:
        await interaction.guild.create_role(
            name='grass-watchers',
            mentionable=True,
            reason="Created for Pokémon spawn notifications"
        )

    await interaction.response.send_message(f'Tallgrass initialized!')

@bot.tree.command(name='start', description='Start spawning Pokémon in this channel. Accepts an active window in military time')
@discord.app_commands.default_permissions(administrator=True)
async def start(interaction: discord.Interaction, start_active_hour: int | None = 0, end_active_hour: int | None = 24):
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

def build_pokemon_gallery(pokemon_list: list, num_columns: int = 4) -> str:
    emojis = [get_emoji(p['national_dex_number'], p['is_shiny'], p['name']) for p in pokemon_list]
    rows = [emojis[i:i+num_columns] for i in range(0, len(emojis), num_columns)]
    return '\n\n'.join('# ' + '\u2000\u2000'.join(row) for row in rows)

def build_candy_string(count: int) -> str:
    emojis = [f"<:rare_candy:{rare_candy_emoji_id}>"] * count
    return "\n## ".join("".join(emojis[i:i+7]) for i in range(0, count, 7))

@bot.tree.command(name='box', description='View your pokemon collection')
async def box(interaction: discord.Interaction, user: discord.Member = None):
    view_user = user if user else interaction.user
    pokemon_list = await database.get_all_user_pokemon(view_user.id, interaction.guild_id)
    num_candies = await database.get_rare_candies(view_user.id, interaction.guild_id)
    wrapped_candies = build_candy_string(num_candies)

    candy_display = '\n### Candies\n## ' + wrapped_candies if num_candies > 0 else ''

    description = build_pokemon_gallery(pokemon_list) + candy_display

    embed = discord.Embed(
        title=f"{view_user.name.capitalize()}'s Box",
        description=description,
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

    file, name = await common.get_resized_gif(offer_dex_num, offer_is_shiny, 2)
    shiny_emoji = ' :sparkles: ' if offer_is_shiny else ''
    offer_display_name = f'{shiny_emoji}{name}{shiny_emoji}'
    embed = discord.Embed(title=f"{interaction.user.name.capitalize()}'s {offer_display_name}", color=discord.Color.blue())
    embed.set_image(url='attachment://pokemon.gif')
    await interaction.channel.send(content='# Trade Offer!', embed=embed, file=file)

    file, name = await common.get_resized_gif(want_dex_num, want_is_shiny, 2)
    shiny_emoji = ' :sparkles: ' if want_is_shiny else ''
    want_display_name = f'{shiny_emoji}{name}{shiny_emoji}'
    embed = discord.Embed(title=f'For {want_display_name}',color=discord.Color.blue())
    embed.set_image(url='attachment://pokemon.gif')
    view = TradeView(
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

@bot.tree.command(name='multitrade', description='Post a trade offer with more than one offered and/or more than one wanted Pokémon')
async def multitrade(interaction: discord.Interaction, offer_csv_list: str, want_csv_list: str):
    await interaction.response.defer(ephemeral=True)

    offer_raw = [s.strip() for s in offer_csv_list.split(',')]
    want_raw  = [s.strip() for s in want_csv_list.split(',')]

    try:
        offer_parsed = [parse_pokemon(s) for s in offer_raw]  # list of (dex_num, is_shiny)
        want_parsed  = [parse_pokemon(s) for s in want_raw]
    except ValueError:
        await interaction.followup.send(
            'Example usage: `/multitrade offer_csv_list:raichu_26,shiny_ninetales_38 want_csv_list:pikachu_25,mew_151`',
            ephemeral=True
        )
        return

    # Verify the user can offer these Pokémon
    for raw, (dex_num, is_shiny) in zip(offer_raw, offer_parsed):
        owns = await database.user_has_pokemon(interaction.user.id, interaction.guild_id, dex_num, is_shiny)
        if not owns:
            await interaction.followup.send(f'You do not own {raw}', ephemeral=True)
            return

    # Resolve names for gallery display
    def resolve_pokemon_list(parsed_list):
        result = []
        for dex, shiny in parsed_list:
            result.append({'national_dex_number': dex, 'is_shiny': shiny, 'name': 'number'}) # Note this is a placeholder name for the emoji
        return result

    offer_pokemon_list = resolve_pokemon_list(offer_parsed)
    want_pokemon_list  = resolve_pokemon_list(want_parsed)

    offer_gallery = build_pokemon_gallery(offer_pokemon_list)
    want_gallery  = build_pokemon_gallery(want_pokemon_list)

    view = MultiTradeView(
        log_handler=handler,
        offer_user_id=interaction.user.id,
        offer_pokemon_list=offer_pokemon_list,
        want_pokemon_list=want_pokemon_list,
        offer_gallery=offer_gallery,
        want_gallery=want_gallery,
    )
    embed = discord.Embed(
        description=(
            f'**{interaction.user.name.capitalize()} offers:**\n{offer_gallery}\n\n'
            f'**For:**\n{want_gallery}'
        ),
        color=discord.Color.blue())

    message = await interaction.channel.send(
        content=f'# Trade Offer!',
        embed=embed,
        view=view
    )
    view.message = message

    await interaction.delete_original_response()
    logger.info(f'{interaction.user.id} posted a multitrade: {offer_csv_list} for {want_csv_list}')


@bot.tree.command(name='notifyme', description="Adds or removes the notification role from your user")
async def notifyme(interaction: discord.Interaction, enable: bool):
    member = await interaction.guild.fetch_member(interaction.user.id)
    role = discord.utils.get(interaction.guild.roles, name=notification_role_name)
    has_role = role in member.roles

    if enable:
        if has_role:
            await interaction.response.send_message(f'You already have the {notification_role_name} role', ephemeral=True)
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f'Added the {notification_role_name} role', ephemeral=True)
    else:
        if not has_role:
            await interaction.response.send_message(f"You don't have the {notification_role_name} role", ephemeral=True)
        else:
            await member.remove_roles(role)
            await interaction.response.send_message(f'Removed the {notification_role_name} role', ephemeral=True)

def get_next_evolutions(dex_number):
    species_data = requests.get(f'{poke_api_url}/pokemon-species/{dex_number}').json()
    current_name = species_data['name']

    chain_data = requests.get(species_data['evolution_chain']['url']).json()

    # Find our place in the chain
    node = chain_data['chain']
    while node and node['species']['name'] != current_name:
        node = next((child for child in node['evolves_to']), None)

    if not node or not node['evolves_to']:
        return [], current_name

    results = []
    for evo in node['evolves_to']:
        next_species = requests.get(f'{poke_api_url}/pokemon-species/{evo["species"]["name"]}').json()
        dex_number = next_species['id']
        if dex_number <= pokemon_count:
            results.append({'name': evo['species']['name'], 'dex_number': next_species['id']})
    return results, current_name


@bot.tree.command(name='evolve', description="Uses a rare candy to evolve a pokemon once")
async def evolve(interaction: discord.Interaction, pokemon: str):
    await interaction.response.defer(ephemeral=True)
    try:
        current_dex_num, current_is_shiny = parse_pokemon(pokemon)
    except ValueError:
        await interaction.followup.send('Example usage: `/evolve pokemon:shiny_eevee_133`', ephemeral=True)
        return

    current_db_id = await database.get_user_pokemon_id(interaction.user.id, interaction.guild_id, current_dex_num, current_is_shiny)
    if current_db_id is None:
        await interaction.followup.send(f'You do not own `{pokemon}`. Make sure to include the `shiny_` prefix if the pokemon is shiny', ephemeral=True)
        return

    try:
        evolutions, official_name = get_next_evolutions(current_dex_num)
    except requests.HTTPError:
        await interaction.followup.send('Failed to look up evolution data. Please try again later.', ephemeral=True)
        return

    if not evolutions:
        await interaction.followup.send(f'{pokemon.capitalize()} has no further evolutions.', ephemeral=True)
        return

    formatted_pokemon = [{'national_dex_number': e['dex_number'], 'is_shiny': current_is_shiny, 'name': e['name']} for e in evolutions]
    description = build_pokemon_gallery(formatted_pokemon) + '\n### Cost:\n## ' + f"<:rare_candy:{rare_candy_emoji_id}>"

    embed = discord.Embed(
        title=f"Please confirm the evolution for {official_name.capitalize()}",
        description=description,
        color=discord.Color.purple()
    )

    # Branching evolution — ask the user to pick
    view = EvolutionView(
        user=interaction.user,
        original_pokemon_name=official_name,
        original_dex_num=current_dex_num,
        original_is_shiny=current_is_shiny,
        original_db_id=current_db_id,
        evolutions=evolutions,
    )
    message = await interaction.followup.send(
        embed=embed,
        view=view,
        ephemeral=True
    )
    view.message = message

@bot.tree.command(name='rarecandy', description='Distributes Rare Candy to each server member, which can be claimed with /evolve')
@discord.app_commands.default_permissions(administrator=True)
async def rarecandy(interaction: discord.Interaction, quantity: int):
    if quantity <= 0:
        await interaction.response.send_message("Quantity must be a positive number.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    affected = await database.distribute_rare_candies(
        guild_id=interaction.guild.id,
        quantity=quantity
    )

    await interaction.followup.send(
        f"Distributed **{quantity} Rare Candy** to **{affected} members**.",
        ephemeral=True
    )


# Now we're ready to spin up the bot!
bot.run(token, log_handler=handler, log_level=log_level)