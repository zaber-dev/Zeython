import disnake
from disnake.ui import Button, Select

def create_embed(
    title=None, 
    description=None, 
    color=0x3498db, 
    fields=None, 
    footer=None, 
    buttons=None, 
    selects=None
):
    """
    Create a dynamic Discord embed with optional buttons and selects.

    Args:
        title (str, optional): The title of the embed. Defaults to None.
        description (str, optional): The description of the embed. Defaults to None.
        color (int, optional): The color of the embed. Defaults to 0x3498db.
        fields (list of dict or tuple, optional): A list of fields as dictionaries or tuples ('name', 'value', inline). Defaults to None.
        footer (str or dict, optional): The footer text or a dict with 'text' and optional 'icon_url'. Defaults to None.
        buttons (list of disnake.ui.Button, optional): A list of buttons to add to the embed. Defaults to None.
        selects (list of disnake.ui.Select, optional): A list of selects to add to the embed. Defaults to None.

    Returns:
        tuple: A tuple containing the embed and the components (buttons and selects).
    """
    # Create the embed with provided title, description, and color
    embed = disnake.Embed(title=title, description=description, color=color)

    # Add fields if provided
    if fields:
        for field in fields:
            if isinstance(field, dict):
                embed.add_field(name=field['name'], value=field['value'], inline=field.get('inline', True))
            elif isinstance(field, (list, tuple)) and len(field) >= 2:
                embed.add_field(name=field[0], value=field[1], inline=field[2] if len(field) > 2 else True)

    # Add footer if provided
    if footer:
        if isinstance(footer, dict):
            embed.set_footer(text=footer.get('text'), icon_url=footer.get('icon_url'))
        else:
            embed.set_footer(text=footer)

    # Handle buttons and selects (components)
    components = []
    if buttons:
        components.extend(buttons)
    if selects:
        components.extend(selects)

    return embed, components

# Example usage of create_embed function:
# embed, components = create_embed(
#     title="Sample Embed",
#     description="This is an example of a simplified embed.",
#     fields=[{"name": "Field 1", "value": "Value 1", "inline": False}, ("Field 2", "Value 2")],
#     footer={"text": "Footer text", "icon_url": "https://example.com/icon.png"},
#     buttons=[Button(label="Click me", style=disnake.ButtonStyle.primary)],
#     selects=[Select(placeholder="Choose an option", options=[disnake.SelectOption(label="Option 1", value="1")])]
# )
