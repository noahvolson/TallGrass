import logging
import os

import discord
import common
import database

from dotenv import load_dotenv

load_dotenv()
log_level = int(os.getenv('LOG_LEVEL'))

# Init logging to discord.log
logger = logging.getLogger('CatchView')
logger.setLevel(log_level)

class EvolutionView(discord.ui.View):
    def __init__(self, user, original_pokemon_name, original_dex_num, original_is_shiny, original_db_id, evolutions):
        super().__init__(timeout=30)
        self.user = user
        self.original_pokemon_name = original_pokemon_name
        self.original_dex_num = original_dex_num
        self.original_is_shiny = original_is_shiny
        self.original_db_id = original_db_id
        self.message = None

        for i, evo in enumerate(evolutions):
            button = discord.ui.Button(
                label=f"{evo['name'].capitalize()}",
                style=discord.ButtonStyle.primary,
                row = i // 4
            )
            # Capture evo in the closure
            button.callback = self._make_callback(evo)
            self.add_item(button)

    def _make_callback(self, evo):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.user:
                await interaction.response.send_message("This isn't your evolution!", ephemeral=True)
                return
            self.stop()
            await interaction.response.defer(ephemeral=True)

            # Note that the pokemon and pokemon-species endpoints return slightly different names. Use the one from pokemon
            evo_dex_number = evo['dex_number']
            file, name = await common.get_resized_gif(evo_dex_number, self.original_is_shiny, 2)

            success = await database.evolve(
                interaction.user.id,
                interaction.guild_id,
                self.original_db_id,
                evo_dex_number,
                name
            )
            if not success:
                await interaction.followup.send(
                    f'Evolution failed! Either you lack Rare Candies, or you no longer own {self.original_pokemon_name.capitalize()}.',
                    ephemeral=True
                )
                return

            logger.info(f"{interaction.user} successfully evolved {self.original_pokemon_name.capitalize()} into {evo['name']}")

            embed = discord.Embed(
                title=f"**{interaction.user.display_name}'s {self.original_pokemon_name.capitalize()}** evolved into **{evo['name'].capitalize()}**!",
                color=discord.Color.purple(),
            )
            embed.set_image(url='attachment://pokemon.gif')

            await interaction.channel.send(
                file=file,
                embed=embed
            )
            await interaction.delete_original_response()

        return callback

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)