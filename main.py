import io
import logging
import os
import random
import subprocess
import time

import discord
import requests

from discord.ext import commands, tasks
from dotenv import load_dotenv

# Init environment variables
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
pokemon_count = int(os.getenv('POKEMON_COUNT'))
poke_api_url = os.getenv('POKE_API_URL')
log_level = int(os.getenv('LOG_LEVEL'))
catch_cooldown_sec = int(os.getenv('CATCH_COOLDOWN_SEC'))

# TODO warn if any are not set

# Init logging to discord.log
logger = logging.getLogger('TallGrass')
logger.setLevel(log_level)

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# The ID of a Pokémon available for catching
spawned_pokemon_id = -1

class CatchView(discord.ui.View):

    # user_id -> (last_click_time, last_message)
    cooldowns = {}

    @discord.ui.button(label="Throw a Poké Ball!", style=discord.ButtonStyle.primary)
    async def button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        user_id = interaction.user.id
        now = time.monotonic()

        last_click, last_msg = self.cooldowns.get(user_id, (0, None))
        remaining = catch_cooldown_sec - (now - last_click)

        if remaining > 0 and last_msg:
            # Edit the previous message instead of sending a new one
            await last_msg.edit(content=f"⏳ Slow down! Try again in {remaining:.1f}s.")
            await interaction.response.defer()  # Acknowledge the interaction without sending a new message
            return
        elif last_msg:
            await last_msg.delete()

        # Send a new message
        msg = await interaction.response.send_message("Button clicked!", ephemeral=True)
        sent_msg = await interaction.original_response()  # Get the actual message object

        # Store the time and message object
        self.cooldowns[user_id] = (now, sent_msg)

# Extend commands.Bot to schedule Pokémon spawning
class TallGrass(commands.Bot):
    channel = None

    async def spawn_pokemon(self):

        # Retrieve url and name info for a random Pokémon from PokeApi
        pokemon_id = random.randint(1, pokemon_count)
        response = requests.get(poke_api_url + '/pokemon/' + str(pokemon_id))
        response.raise_for_status()
        data = response.json()
        sprite_url = data['sprites']['other']['showdown']['front_default']
        name = str.capitalize(data['name'])

        # Download GIF
        response = requests.get(sprite_url)
        gif_bytes = response.content

        # Upscale with gifsicle
        process = subprocess.Popen(
            ["gifsicle", "--no-warnings", "--scale", "2", "--colors", "256"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        resized_bytes, _ = process.communicate(input=gif_bytes)

        # Wrap bytes in BytesIO so discord.File can read it
        resized_file = io.BytesIO(resized_bytes)

        file = discord.File(fp=resized_file, filename="pokemon.gif")
        embed = discord.Embed(title=f"Wild {name} appears!", color=discord.Color.dark_green())
        embed.set_image(url="attachment://pokemon.gif")

        # Add catch button
        view = CatchView()

        logger.info(f'Spawning {name} in channel: {self.channel.name}')
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
async def catch(ctx):
    #TODO
    print("Implement me!")
    pass

# Now we're ready to spin up the bot!
bot.run(token, log_handler=handler, log_level=log_level)