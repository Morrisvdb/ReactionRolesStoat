# main.py

import os
import sqlite3
from contextlib import closing

from dotenv import load_dotenv
from stoat import Client, Member


# ============================================================================
# Configuration
# ============================================================================

load_dotenv()

TOKEN = os.getenv("STOAT_TOKEN")
# DATABASE = os.getenv(
#     "DATABASE",
#     "/app/data/reaction_roles.sqlite3",
# )

DATABASE = "reaction_roles.sqlite3"

if not TOKEN:
    raise RuntimeError(
        "STOAT_TOKEN is missing. Add it to your .env file."
    )


# ============================================================================
# Database
# ============================================================================

def initialise_database() -> None:
    with closing(sqlite3.connect(DATABASE)) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_roles (
                message_id TEXT NOT NULL,
                emoji TEXT NOT NULL,
                role_id TEXT NOT NULL,
                role_name TEXT NOT NULL DEFAULT 'Role',
                PRIMARY KEY (message_id, emoji)
            )
            """
        )

        # Adds role_name when upgrading an older database created by the
        # previous version of the program.
        columns = db.execute(
            "PRAGMA table_info(reaction_roles)"
        ).fetchall()

        column_names = {column[1] for column in columns}

        if "role_name" not in column_names:
            db.execute(
                """
                ALTER TABLE reaction_roles
                ADD COLUMN role_name TEXT NOT NULL DEFAULT 'Role'
                """
            )

        db.commit()


def save_reaction_role(
    message_id: str,
    emoji: str,
    role_id: str,
    role_name: str,
) -> None:
    with closing(sqlite3.connect(DATABASE)) as db:
        db.execute(
            """
            INSERT OR REPLACE INTO reaction_roles
            (message_id, emoji, role_id, role_name)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, emoji, role_id, role_name),
        )
        db.commit()


def delete_reaction_role(
    message_id: str,
    emoji: str,
) -> None:
    with closing(sqlite3.connect(DATABASE)) as db:
        db.execute(
            """
            DELETE FROM reaction_roles
            WHERE message_id = ? AND emoji = ?
            """,
            (message_id, emoji),
        )
        db.commit()


def get_reaction_role(
    message_id: str,
    emoji: str,
) -> tuple[str, str] | None:
    with closing(sqlite3.connect(DATABASE)) as db:
        result = db.execute(
            """
            SELECT role_id, role_name
            FROM reaction_roles
            WHERE message_id = ? AND emoji = ?
            """,
            (message_id, emoji),
        ).fetchone()

    return result if result else None


def get_reaction_roles(
    message_id: str,
) -> list[tuple[str, str, str]]:
    with closing(sqlite3.connect(DATABASE)) as db:
        results = db.execute(
            """
            SELECT emoji, role_id, role_name
            FROM reaction_roles
            WHERE message_id = ?
            ORDER BY rowid
            """,
            (message_id,),
        ).fetchall()

    return results


# ============================================================================
# Message formatting
# ============================================================================

def build_role_message(message_id: str) -> str:
    """
    Builds the plain-text reaction-role message.
    """

    role_rows = get_reaction_roles(message_id)

    lines = [
        "Choose your roles",
        "",
        "React with an emoji to receive a role.",
        "Remove your reaction to remove the role.",
        "",
    ]

    if not role_rows:
        lines.append("No roles have been configured yet.")
        return "\n".join(lines)

    for emoji, role_id, role_name in role_rows:
        lines.append(f"{emoji} — {role_name}")

    return "\n".join(lines)


# ============================================================================
# Event helpers
# ============================================================================

def get_event_value(event, name: str, default=None):
    """
    Supports both object-style and dictionary-style event payloads.
    """

    value = getattr(event, name, default)

    if value != default:
        return value

    if isinstance(event, dict):
        return event.get(name, default)

    return default


def get_event_emoji(event) -> str | None:
    emoji = get_event_value(event, "emoji")

    if emoji is None:
        return None

    if isinstance(emoji, str):
        return emoji

    if isinstance(emoji, dict):
        return str(
            emoji.get("name")
            or emoji.get("id")
            or ""
        )

    return str(
        getattr(emoji, "name", None)
        or getattr(emoji, "id", None)
        or emoji
    )


# ============================================================================
# Bot
# ============================================================================

class ReactionRoleClient(Client):
    async def on_ready(self, _, /):
        print(f"Logged in as {self.me}")
        print("Use !rr help to see the available commands.")

    async def on_message(self, message, /):
        if message.author_id == self.me.id:
            return
        
        author : Member = message.author
                
        if author.server_permissions.assign_roles == False:
            return 

        content = (message.content or "").strip()

        # --------------------------------------------------------------------
        # Help
        # --------------------------------------------------------------------

        if content == "!rr help":
            await message.channel.send(
                "Reaction-role commands:\n"
                "\n"
                "`!rr setup <channel_id>`\n"
                "Creates a new reaction-role message.\n"
                "\n"
                "`!rr add <message_id> <emoji> <role_id> <role_name>`\n"
                "Adds a role to an existing reaction-role message.\n"
                "\n"
                "`!rr remove <message_id> <emoji>`\n"
                "Removes a role from a reaction-role message.\n"
                "\n"
                "`!rr edit <channel_id> <message_id>`\n"
                "Updates the text of an existing reaction-role message."
            )
            return

        # --------------------------------------------------------------------
        # Setup
        #
        # Example:
        # !rr setup 01CHANNELID
        # --------------------------------------------------------------------

        if content.startswith("!rr setup"):
            parts = content.split()

            if len(parts) != 3:
                await message.channel.send(
                    "Usage: `!rr setup <channel_id>`"
                )
                return

            channel_id = parts[2]

            try:
                message_id = await self.create_reaction_role_message(
                    channel_id
                )

                await message.channel.send(
                    "Reaction-role message created.\n"
                    f"Message ID: `{message_id}`"
                )

            except Exception as error:
                print(f"Could not create reaction-role message: {error}")

                await message.channel.send(
                    f"Could not create reaction-role message: {error}"
                )

            return

        # --------------------------------------------------------------------
        # Add
        #
        # Example:
        # !rr add 01MESSAGEID 🎮 01ROLEID Gaming
        #
        # maxsplit=4 allows role names containing spaces:
        # !rr add MESSAGE_ID 🎮 ROLE_ID PC Gaming
        # --------------------------------------------------------------------

        if content.startswith("!rr add"):
            parts = content.split(maxsplit=4)

            if len(parts) != 5:
                await message.channel.send(
                    "Usage:\n"
                    "`!rr add <message_id> <emoji> "
                    "<role_id> <role_name>`"
                )
                return

            _, _, message_id, emoji, role_data = parts

            role_parts = role_data.split(maxsplit=1)

            if len(role_parts) != 2:
                await message.channel.send(
                    "You must provide both a role ID and role name.\n"
                    "Example:\n"
                    "`!rr add MESSAGE_ID 🎮 ROLE_ID Gaming`"
                )
                return

            role_id, role_name = role_parts

            try:
                save_reaction_role(
                    message_id=message_id,
                    emoji=emoji,
                    role_id=role_id,
                    role_name=role_name,
                )

                await message.channel.send(
                    f"Added role `{role_name}` for {emoji}.\n"
                    "Run `!rr edit <channel_id> <message_id>` "
                    "to update the message."
                )

            except Exception as error:
                print(f"Could not add reaction role: {error}")

                await message.channel.send(
                    f"Could not add reaction role: {error}"
                )

            return

        # --------------------------------------------------------------------
        # Remove
        #
        # Example:
        # !rr remove 01MESSAGEID 🎮
        # --------------------------------------------------------------------

        if content.startswith("!rr remove"):
            parts = content.split()

            if len(parts) != 4:
                await message.channel.send(
                    "Usage: `!rr remove <message_id> <emoji>`"
                )
                return

            _, _, message_id, emoji = parts

            try:
                delete_reaction_role(
                    message_id=message_id,
                    emoji=emoji,
                )

                await message.channel.send(
                    f"Removed the role assigned to {emoji}.\n"
                    "Run `!rr edit <channel_id> <message_id>` "
                    "to update the message."
                )

            except Exception as error:
                print(f"Could not remove reaction role: {error}")

                await message.channel.send(
                    f"Could not remove reaction role: {error}"
                )

            return

        # --------------------------------------------------------------------
        # Edit
        #
        # Example:
        # !rr edit 01CHANNELID 01MESSAGEID
        # --------------------------------------------------------------------

        if content.startswith("!rr edit"):
            parts = content.split()

            if len(parts) != 4:
                await message.channel.send(
                    "Usage: `!rr edit <channel_id> <message_id>`"
                )
                return

            _, _, channel_id, message_id = parts

            try:
                channel = self.get_channel(channel_id)

                if channel is None:
                    await message.channel.send(
                        f"Could not find channel `{channel_id}`."
                    )
                    return

                # Some stoat.py versions call this fetch_message().
                role_message = await channel.fetch_message(message_id)

                new_content = build_role_message(message_id)

                await role_message.edit(content=new_content)

                # Add any configured reactions that are missing from the
                # message. Existing reactions are left unchanged.
                for emoji, _, _ in get_reaction_roles(message_id):
                    try:
                        await role_message.react(emoji)
                    except Exception as error:
                        print(
                            f"Could not add reaction {emoji}: {error}"
                        )

                await message.channel.send(
                    "Reaction-role message updated."
                )

            except Exception as error:
                print(f"Could not edit reaction-role message: {error}")

                await message.channel.send(
                    f"Could not edit reaction-role message: {error}"
                )

            return

    async def create_reaction_role_message(
        self,
        channel_id: str,
    ) -> str:
        channel = self.get_channel(channel_id)

        if channel is None:
            raise RuntimeError(
                f"Could not find channel with ID {channel_id}"
            )

        # Send the initial plain-text message.
        reaction_message = await channel.send(
            content=(
                "Choose your roles\n\n"
                "No roles have been configured yet.\n\n"
                "Use the bot's `!rr add` command to add roles."
            )
        )

        message_id = str(reaction_message.id)

        print(
            f"Created reaction-role message {message_id} "
            f"in channel {channel_id}"
        )

        return message_id

    async def on_message_react(self, event, /):
        print("Reaction added:", repr(event))
        await self.update_role(event, add=True)

    async def on_message_unreact(self, event, /):
        print("Reaction removed:", repr(event))
        await self.update_role(event, add=False)

    async def update_role(self, event, *, add: bool) -> None:
        user_id = str(event.user_id)
        message_id = str(event.message_id)
        emoji = str(event.emoji)        

        channel = self.get_channel(event.channel_id)

        if channel is None:
            print(f"Could not find channel {event.channel_id}")
            return

        server_id = getattr(channel, "server_id", None)

        print(
            f"user_id={user_id}, "
            f"message_id={message_id}, "
            f"emoji={emoji}"
        )

        if user_id == str(self.me.id):
            return

        reaction_role = get_reaction_role(
            message_id=message_id,
            emoji=emoji,
        )

        if reaction_role is None:
            print(
                f"No configured role for message={message_id}, "
                f"emoji={emoji!r}"
            )
            return
        
        
        server = await client.fetch_server(server_id=server_id)
        member = await server.fetch_member(user_id)
        
        role_id, role_name = reaction_role
        
        print("ROLE_ID: ", role_id)
        print("REACTION_ROLE: ", reaction_role)
        
        try:
            current_roles = list(member.roles or [])
            if add:
                if role_id not in current_roles:
                    current_roles.append(role_id)
            else:
                current_roles = [
                    existing_role_id
                    for existing_role_id in current_roles
                    if existing_role_id.id != role_id
                ]
                print("CURRENT_ROLES: ", current_roles)

            await self.http.edit_member(
                server=server,
                member=member,
                roles=current_roles,
            )

            action = "Added" if add else "Removed"

            print(
                f"{action} role {role_name} ({role_id}) "
                f"{'to' if add else 'from'} user {user_id}"
            )

        except Exception as error:
            print(
                f"Could not update role for user {user_id}: {error}"
            )




    # async def update_role(self, event, *, add: bool) -> None:
    #     user_id = get_event_value(event, "user_id")
    #     message_id = get_event_value(event, "message_id")
        
    #     server_id = (
    #         get_event_value(event, "server_id")
    #         or get_event_value(event, "guild_id")
    #     )
    #     emoji = get_event_emoji(event)

    #     print(user_id, message_id, server_id, emoji)

    #     if not user_id or not message_id or not server_id or not emoji:
    #         print(f"Incomplete reaction event: {event!r}")
    #         return

    #     # Ignore reactions made by the bot itself.
    #     if str(user_id) == str(self.me.id):
    #         return

    #     reaction_role = get_reaction_role(
    #         message_id=str(message_id),
    #         emoji=str(emoji),
    #     )

    #     # This reaction is not configured as a role reaction.
    #     if reaction_role is None:
    #         return

    #     role_id, role_name = reaction_role

    #     server = self.get_server(server_id)

    #     if server is None:
    #         print(f"Could not find server {server_id}")
    #         return

    #     member = server.get_member(user_id)

    #     if member is None:
    #         print(f"Could not find member {user_id}")
    #         return

    #     try:
    #         if add:
    #             await member.add_role(role_id)

    #             print(
    #                 f"Added role {role_name} ({role_id}) "
    #                 f"to user {user_id}"
    #             )
    #         else:
    #             await member.remove_role(role_id)

    #             print(
    #                 f"Removed role {role_name} ({role_id}) "
    #                 f"from user {user_id}"
    #             )

    #     except Exception as error:
    #         print(
    #             f"Could not update role for user {user_id}: {error}"
    #         )


# ============================================================================
# Start
# ============================================================================

if __name__ == "__main__":
    initialise_database()

    client = ReactionRoleClient(token=TOKEN)
    client.run()
