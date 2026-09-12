"""Smart-money screening bot for gmgn.ai.

Independent of the `bot/` package (the Polymarket trading bot) — this one
never places trades. It polls gmgn.ai's public token/wallet data, looks for
tokens that multiple tagged "smart money" wallets are accumulating, and
raises alerts (console / Telegram / Discord) so a human can decide what to
do with the information.
"""
