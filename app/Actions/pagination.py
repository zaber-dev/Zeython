import disnake

# Define a dummy response function
async def invalid_response(interaction):
    """
    Sends an invalid response message to the user.

    Args:
        interaction (disnake.Interaction): The interaction object.
    """
    await interaction.response.send_message("Hmm? Seem like you are not the sender of this command!", ephemeral=True)

# Define a Paginator class
class Paginator:
    """
    A class to create a paginated embed view.

    Attributes:
        segments (list): The list of segments to be paginated.
        title (str): The default title of the embed.
        color (int): The default color of the embed.
        prefix (str): The default prefix of the embed description.
        suffix (str): The default suffix of the embed description.
        target_page (int): The default target page.
        timeout (int): The default timeout for the view.
        button_style (disnake.ButtonStyle): The default button style.
        invalid_user_function (function): The function to call for invalid user interactions.
    """

    def __init__(
            self,
            segments,
            title="",  # Define the default title of the embed
            color=0x000000,
            prefix="",  # Define the default prefix of the embed
            suffix="",  # Define the default suffix of the embed
            target_page=1,  # Define the default target page
            timeout=300,  # Define the default timeout
            button_style=disnake.ButtonStyle.gray,  # Define the default button style
            invalid_user_function=invalid_response,  # Define the default invalid user function
        ):
        """
        Initializes the create class with the given parameters.

        Args:
            segments (list): The list of segments to be paginated.
            title (str): The default title of the embed.
            color (int): The default color of the embed.
            prefix (str): The default prefix of the embed description.
            suffix (str): The default suffix of the embed description.
            target_page (int): The default target page.
            timeout (int): The default timeout for the view.
            button_style (disnake.ButtonStyle): The default button style.
            invalid_user_function (function): The function to call for invalid user interactions.
        """
        self.embeds = []
        self.current_page = target_page
        self.timeout = timeout
        self.button_style = button_style
        self.invalid_user_function = invalid_user_function

        # Loop through the segments
        for segment in segments:
            if isinstance(segment, disnake.Embed):
                self.embeds.append(segment)
            else:
                self.embeds.append(
                    disnake.Embed(
                        title=title,
                        color=color,
                        description=prefix + segment + suffix,
                    ),
                )
        # Check if the target page is greater than the length of the segments
        if self.current_page > len(segments) or self.current_page < 1:
            self.current_page = 1

        # Define a PaginatorView class
        class PaginatorView(disnake.ui.View):
            """
            A class to create a paginated view with buttons.

            Attributes:
                interaction (disnake.Interaction): The interaction object.
            """

            def __init__(this, interaction):
                """
                Initializes the PaginatorView class with the given interaction.

                Args:
                    interaction (disnake.Interaction): The interaction object.
                """
                super().__init__()
                this.timeout = self.timeout
                this.interaction = interaction

            # Define an on_timeout function
            async def on_timeout(this):
                """
                Disables all buttons when the view times out.
                """
                for button in this.children:
                    button.disabled = True
                await this.interaction.edit_original_message(view=this)
                return await super().on_timeout()

            # Define an update_page function
            def update_page(this):
                """
                Updates the page number on the page button.
                """
                for button in this.children:
                    if button.label:
                        if button.label.strip() != "":
                            button.label = f"{self.current_page}/{len(self.embeds)}"

            # Define the first button - first button
            @disnake.ui.button(emoji="⏪", style=self.button_style, disabled=True if len(self.embeds) == 1 else False)
            async def first_button(this, _, button_interaction):
                """
                Handles the first button click event.

                Args:
                    button_interaction (disnake.Interaction): The interaction object.
                """
                if button_interaction.author != this.interaction.author:
                    await self.invalid_user_function(button_interaction)
                    return

                # Check if the length of the embeds is greater than or equal to 15
                if len(self.embeds) >= 15:
                    self.current_page = (self.current_page - 10) % len(self.embeds)
                    if self.current_page < 1:
                        self.current_page = len(self.embeds)
                    if self.current_page == 0:
                        self.current_page = 1
                else:
                    self.current_page = 1
                this.update_page()
                await button_interaction.response.edit_message(embed=self.embeds[self.current_page-1], view=this)

            # Define the second button - previous button
            @disnake.ui.button(emoji="◀️", style=self.button_style, disabled=True if len(self.embeds) == 1 else False)
            async def previous_button(this, _, button_interaction):
                """
                Handles the previous button click event.

                Args:
                    button_interaction (disnake.Interaction): The interaction object.
                """
                if button_interaction.author != this.interaction.author:
                    await self.invalid_user_function(button_interaction)
                    return

                # Check if the current page is less than 1
                self.current_page -= 1
                if self.current_page < 1:
                    self.current_page = len(self.embeds)
                this.update_page()
                await button_interaction.response.edit_message(embed=self.embeds[self.current_page-1], view=this)

            # Define the third button - page button
            @disnake.ui.button(label=f"{self.current_page}/{len(self.embeds)}", style=disnake.ButtonStyle.gray, disabled=True)
            async def page_button(*_):
                """
                Handles the page button click event (does nothing).
                """
                pass

            # Define the fourth button - next button
            @disnake.ui.button(emoji="▶️", style=self.button_style, disabled=True if len(self.embeds) == 1 else False)
            async def next_button(this, _, button_interaction):
                """
                Handles the next button click event.

                Args:
                    button_interaction (disnake.Interaction): The interaction object.
                """
                if button_interaction.author != this.interaction.author:
                    await self.invalid_user_function(button_interaction)
                    return

                # Check if the current page is greater than the length of the embeds
                self.current_page += 1
                if self.current_page > len(self.embeds):
                    self.current_page = 1
                this.update_page()
                await button_interaction.response.edit_message(embed=self.embeds[self.current_page-1], view=this)

            # Define the fifth button - last button
            @disnake.ui.button(emoji="⏩", style=self.button_style, disabled=True if len(self.embeds) == 1 else False)
            async def last_button(this, _, button_interaction):
                """
                Handles the last button click event.

                Args:
                    button_interaction (disnake.Interaction): The interaction object.
                """
                if button_interaction.author != this.interaction.author:
                    await self.invalid_user_function(button_interaction)
                    return
                # Check if the length of the embeds is greater than or equal to 15
                if len(self.embeds) >= 15:
                    self.current_page = (self.current_page + 10) % len(self.embeds)
                    if self.current_page > len(self.embeds):
                        self.current_page = 1
                    if self.current_page == 0:
                        self.current_page = len(self.embeds)
                else:
                    self.current_page = len(self.embeds)
                this.update_page()
                await button_interaction.response.edit_message(embed=self.embeds[self.current_page-1], view=this)

        self.view = PaginatorView

    # Define a start function
    async def start(self, interaction, ephemeral=False, deferred=False):
        """
        Starts the pagination interaction.

        Args:
            interaction (disnake.Interaction): The interaction object.
            ephemeral (bool): Whether the message should be ephemeral.
            deferred (bool): Whether the interaction is deferred.
        """
        # Check if the interaction is deferred
        if not deferred:
            await interaction.response.send_message(embed=self.embeds[self.current_page-1], view=self.view(interaction), ephemeral=ephemeral)
        else:
            await interaction.edit_original_message(embed=self.embeds[self.current_page-1], view=self.view(interaction))
            
# Example usage of Paginator class:
# segments = ["Page 1 content", disnake.Embed(title="Page 2", description="Page 2 content")]
# paginator = Paginator(segments, title="Example Pagination", color=0x00ff00, prefix="**", suffix="**")
# await paginator.start(interaction)