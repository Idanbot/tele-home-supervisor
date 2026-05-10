"""Centralized UI strings and emojis for the bot."""

# Icons/Emojis
ICON_WAIT = "⏱"
ICON_LOCK = "🔒"
ICON_ERROR = "❌"
ICON_SUCCESS = "✅"
ICON_WARN = "⚠️"
ICON_INFO = "ℹ️"
ICON_REMIDER = "⏰"
ICON_TRASH = "🗑"
ICON_DOCKER = "🐳"
ICON_TORRENT = "📥"
ICON_AI = "🤖"
ICON_HEALTH = "❤️"

# Common messages
MSG_NOT_AUTHORIZED = f"{ICON_ERROR} Not authorized."
MSG_OWNER_ONLY = "⛔ Owner only."
MSG_AUTH_REQUIRED = f"{ICON_LOCK} This command requires authentication. Use <code>/auth &lt;totp_code&gt;</code> to gain access for 7 days."
MSG_RATE_LIMIT = f"{ICON_WAIT} Rate limit: please wait {{:.1f}}s"
MSG_ERROR = f"{ICON_ERROR} Error: {{}}"
MSG_UNKNOWN_COMMAND = "❓ Unknown command."
