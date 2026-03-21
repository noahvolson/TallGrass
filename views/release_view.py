import logging
import os

import discord
import database

from dotenv import load_dotenv

load_dotenv()
log_level = int(os.getenv('LOG_LEVEL'))

logger = logging.getLogger('ReleaseView')
logger.setLevel(log_level)

class ReleaseView(discord.ui.View):
    def __init__(self, user, pokemon_name, dex_number, is_shiny, spawn_callback):
        super().__init__(timeout=30)
        self.user = user
        self.pokemon_name = pokemon_name
        self.dex_number = dex_number
        self.is_shiny = is_shiny
        self.message = None
        self.spawn_callback = spawn_callback

        self.children[0].label = f'Release {pokemon_name}!'


    @discord.ui.button(style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("This isn't your Pokémon!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success = await database.remove_user_pokemon(
            interaction.user.id,
            interaction.guild_id,
            self.dex_number,
            self.is_shiny
        )

        if not success:
            await interaction.followup.send(
                f'Release failed! You may no longer own {self.pokemon_name.capitalize()}.',
                ephemeral=True
            )
            return

        database.invalidate_pokemon_count(interaction.user.id, interaction.guild_id)

        self.stop()
        logger.info(f"{interaction.user} successfully released {self.pokemon_name.capitalize()}")

        embed = discord.Embed(
            title=f"**{interaction.user.display_name}** released **{self.pokemon_name.capitalize()}**!",
            description=f"{self.pokemon_name.capitalize()} was released into the wild. Goodbye!",
            color=discord.Color.red(),
        )

        await interaction.channel.send(embed=embed)
        await interaction.delete_original_response()
        await self.spawn_callback()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)