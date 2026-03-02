import logging
import os
import random

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
# TODO warn if any are not set

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

    async def spawn_pokemon(self):
        pokemon_id = random.randint(1, pokemon_count)
        response = requests.get(poke_api_url + '/pokemon/' + str(pokemon_id))
        response.raise_for_status()

        data = response.json()

        # TODO add some error handling here
        sprite_url = data['sprites']['other']['official-artwork']['front_default']
        name = str.capitalize(data['name'])

        embed = discord.Embed(title=f'Wild {name} appears!')
        embed.set_image(url=sprite_url)

        logger.info(f'Spawning {name} in channel: {self.channel.name}')
        await self.channel.send(embed=embed)

    async def setup_hook(self):
        self.spawner_task.start()

    @tasks.loop(seconds=5)
    async def spawner_task(self):
        # TODO use self.spawner_task.change_interval(seconds=<RANDOM_INTERVAL_HERE>)

        if not self.channel:
            return

        await self.spawn_pokemon()


# Init TallGrass bot, enable commands
intents = discord.Intents.default()
intents.message_content = True
bot = TallGrass(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f'{bot.user.name} is now online')

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