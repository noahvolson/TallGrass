import asyncio
import io
import logging
import os
import random
import subprocess
import time
import database

import discord
import requests
from discord import NotFound

from discord.ext import commands, tasks
from dotenv import load_dotenv

# Init environment variables
load_dotenv()
token                       = os.getenv('DISCORD_TOKEN')
poke_api_url                = os.getenv('POKE_API_URL')
pokemon_count               = int(os.getenv('POKEMON_COUNT'))
log_level                   = int(os.getenv('LOG_LEVEL'))
catch_cooldown_sec          = int(os.getenv('CATCH_COOLDOWN_SEC'))
rare_chance_percent         = int(os.getenv('RARE_CHANCE_PERCENT'))
shiny_chance_percent        = int(os.getenv('SHINY_CHANCE_PERCENT'))
regular_chance_percent      = int(os.getenv('REGULAR_CHANCE_PERCENT'))
shiny_spawn_one_in          = int(os.getenv('SHINY_SPAWN_ONE_IN'))

# TODO warn if any are not set

# Init logging to discord.log
logger = logging.getLogger('TallGrass')
logger.setLevel(log_level)

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class CatchView(discord.ui.View):

    def __init__(self, spawned_pokemon_id, spawned_pokemon_name, spawned_pokemon_catch_percent, sprite_url, is_shiny, *args, **kwargs):

        self.cooldowns = {} # user_id -> (last_click_time, last_message)
        self.claimed = False
        self.claim_lock = asyncio.Lock()

        # Details of the Pokémon available for catching
        self.spawned_pokemon_id = spawned_pokemon_id
        self.spawned_pokemon_name = spawned_pokemon_name
        self.spawned_pokemon_catch_percent = spawned_pokemon_catch_percent
        self.sprite_url = sprite_url
        self.is_shiny = is_shiny

        super().__init__(*args, **kwargs)

    @discord.ui.button(label='Throw a Poké Ball!', style=discord.ButtonStyle.primary)
    async def button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        async with self.claim_lock:
            if self.claimed:
                await interaction.response.send_message(f'Too slow! {self.spawned_pokemon_name} already caught.', ephemeral=True)
                return

            user_id = interaction.user.id
            now = time.monotonic()

            last_click, last_msg = self.cooldowns.get(user_id, (0, None))
            remaining = catch_cooldown_sec - (now - last_click)

            if last_msg:
                # Need to acknowledge the interaction within 3 seconds or discord invalidates
                await interaction.response.defer()
                if remaining > 0:
                    try:
                        await last_msg.edit(content=f':hourglass: Slow down! Try again in {remaining:.1f}s.')
                    except discord.NotFound:
                        pass
                    return
                else:
                    try:
                        await last_msg.delete()
                    except discord.NotFound:
                        pass

            # Attempt to catch
            roll = random.randint(1, 100)
            success = roll <= self.spawned_pokemon_catch_percent
            logger.debug(f'{interaction.user.display_name} Rolled: {roll}, Required: {self.spawned_pokemon_catch_percent} or lower')

            if success:
                try:
                    await database.add_user_pokemon(
                        interaction.user.id,
                        self.spawned_pokemon_id,
                        self.spawned_pokemon_name,
                        self.spawned_pokemon_name,
                        self.sprite_url,
                        self.is_shiny
                    )
                except Exception as e:
                    logger.error(f'Failed to add {self.spawned_pokemon_name} to user {interaction.user.id}: {e}')
                    return

                self.claimed = True
                button.disabled = True
                if last_msg:
                    await interaction.edit_original_response(view=self)
                else:
                    await interaction.response.edit_message(view=self)
                self.cooldowns = {}
                message_string = f'Gotcha! {self.spawned_pokemon_name} was caught by {interaction.user.display_name}!'
                await interaction.followup.send(message_string)
                logger.info(f'{self.spawned_pokemon_name} was caught by {interaction.user.display_name}')
            else:
                message_string = 'Aww! It appeared to be caught!'
                if last_msg:
                    sent_msg = await interaction.followup.send(message_string, ephemeral=True)
                else:
                    await interaction.response.send_message(message_string, ephemeral=True)
                    sent_msg = await interaction.original_response()

                # Store the time and message object
                self.cooldowns[user_id] = (now, sent_msg)

# Extend commands.Bot to schedule Pokémon spawning
class TallGrass(commands.Bot):
    channel = None

    async def spawn_pokemon(self):

        # Roll for shiny
        is_shiny = random.randint(1, shiny_spawn_one_in) == 1

        # Retrieve url and name info for a random Pokémon from PokeApi
        spawned_pokemon_id = random.randint(1, pokemon_count)
        response = requests.get(poke_api_url + '/pokemon/' + str(spawned_pokemon_id))
        response.raise_for_status()
        data = response.json()
        sprite_url = data['sprites']['other']['showdown']['front_shiny' if is_shiny else 'front_default']
        spawned_pokemon_name = str.capitalize(data['name'])

        # Determine catch percent from the species endpoint
        response = requests.get(poke_api_url + '/pokemon-species/' + str(spawned_pokemon_id))
        data = response.json()

        if data['is_legendary'] or data['is_mythical']:
            spawned_pokemon_catch_percent = rare_chance_percent
        elif is_shiny:
            spawned_pokemon_catch_percent = shiny_chance_percent
        else:
            spawned_pokemon_catch_percent = regular_chance_percent

        # Download GIF
        response = requests.get(sprite_url)
        gif_bytes = response.content

        # Upscale with gifsicle
        process = subprocess.Popen(
            ['gifsicle', '--no-warnings', '--scale', '2', '--colors', '256'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        resized_bytes, _ = process.communicate(input=gif_bytes)

        # Wrap bytes in BytesIO so discord.File can read it
        resized_file = io.BytesIO(resized_bytes)

        file = discord.File(fp=resized_file, filename='pokemon.gif')
        embed = discord.Embed(title=f'Wild {spawned_pokemon_name} appears!', color=discord.Color.dark_green())
        embed.set_image(url='attachment://pokemon.gif')

        view = CatchView(
            spawned_pokemon_id=spawned_pokemon_id,
            spawned_pokemon_name=spawned_pokemon_name,
            spawned_pokemon_catch_percent=spawned_pokemon_catch_percent,
            sprite_url=sprite_url,
            is_shiny=is_shiny
        )

        logger.info(f'Spawning {spawned_pokemon_name} in channel: {self.channel.name}')
        await self.channel.send(embed=embed, file=file, view=view)

    async def setup_hook(self):
        self.spawner_task.start()

    @tasks.loop(seconds=10)
    async def spawner_task(self):
        # TODO use self.spawner_task.change_interval(seconds=<RANDOM_INTERVAL_HERE>)

        if not self.channel:
            return

        await self.spawn_pokemon()

# Init TallGrass bot
intents = discord.Intents.default()
intents.message_content = True
bot = TallGrass(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f'{bot.user.name} is now online')

# Enable command parsing
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

# Define bot commands
@bot.command()
async def init(ctx):
    if ctx.message.author.guild_permissions.administrator:
        try:
            await database.init_db()
        except Exception as e:
            logger.error(f'Failed to initialize database: {e}')

        await ctx.send(f'Tallgrass initialized!')

@bot.command()
async def start(ctx):
    if ctx.message.author.guild_permissions.administrator:
        bot.channel = ctx.channel
        logger.info(f'{ctx.message.author.display_name} activated spawning in channel: {ctx.channel.name}')

# Define bot commands
@bot.command()
async def stop(ctx):
    if ctx.message.author.guild_permissions.administrator:
        bot.channel = None
        logger.info(f'{ctx.message.author.display_name} deactivated spawning in channel: {ctx.channel.name}')

@bot.command()
async def channel(ctx):
    await ctx.send(f'Channel ID: {ctx.channel.id}')
    pass

# Now we're ready to spin up the bot!
bot.run(token, log_handler=handler, log_level=log_level)