import logging
import os

import discord
import database

from dotenv import load_dotenv

load_dotenv()
log_level = int(os.getenv('LOG_LEVEL'))

logger = logging.getLogger('RegisterView')
logger.setLevel(log_level)

class RegisterView(discord.ui.View):
    def __init__(self, log_handler, user_id, tournament_code, team_pokemon_list, team_gallery):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.tournament_code = tournament_code
        self.team_pokemon_list = team_pokemon_list
        self.team_gallery = team_gallery
        self.message = None

        logger.addHandler(log_handler)

    @discord.ui.button(label='Register', style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your registration!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success = await database.register_tournament_team(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            tournament_code=self.tournament_code,
            team_pokemon_list=[(p['national_dex_number'], p['is_shiny']) for p in self.team_pokemon_list],
        )

        if not success:
            await interaction.followup.send(
                f'Registration failed! The tournament `{self.tournament_code}` may not exist, '
                f'may be inactive, or you may already be registered.',
                ephemeral=True
            )
            return

        self.stop()
        logger.info(
            f"{interaction.user} successfully registered for tournament '{self.tournament_code}' "
            f"with team: {[p['national_dex_number'] for p in self.team_pokemon_list]}"
        )

        embed = discord.Embed(
            title=f"**{interaction.user.display_name}** registered for **{self.tournament_code}**!",
            description=f"{self.team_gallery}\nYour team has been locked in. Good luck!",
            color=discord.Color.green(),
        )

        await interaction.channel.send(embed=embed)
        await interaction.delete_original_response()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your registration!", ephemeral=True)
            return

        self.stop()
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)
