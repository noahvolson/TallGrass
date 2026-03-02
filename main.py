import logging
import os
import random

import discord
import requests

from discord.ext import commands, tasks
from dotenv import load_dotenv
from numpy.core.defchararray import capitalize

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
pokemon_count = int(os.getenv('POKEMON_COUNT'))
poke_api_url = os.getenv('POKE_API_URL')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True

# class TallGrass(commands.Bot):
#     async def setup_hook(self):
#         #TODO start background task
#         pass
#
#     # https://stackoverflow.com/questions/67245314/randomize-time-for-looping-task-in-discord
#     @tasks.loop(minutes=1)
#     async def spawn_pokemon(self):
#         print("Spawning a Pokemon")
#
#         if test.current_loop % 2 == 0:
#             test.change_interval(minutes=3)
#         else:
#             test.change_interval(minutes=1)


bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user.name} started!")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention}!")

@bot.command()
async def catch(ctx):
    pokemon_id = random.randint(1, pokemon_count)
    response = requests.get(poke_api_url + '/pokemon/' + str(pokemon_id))
    response.raise_for_status()

    data = response.json()

    # Navigate to sprites -> other -> official-artwork -> front_default
    sprite_url = data["sprites"]["other"]["official-artwork"]["front_default"]
    name = capitalize(data["name"])

    embed = discord.Embed(title=f"Wild {name} appears!")
    embed.set_image(url=sprite_url)
    await ctx.send(embed=embed)

bot.run(token, log_handler=handler, log_level=logging.DEBUG)
print("After run")