"""Generate a brand-new Solana wallet, entirely offline/locally, for use as
a dedicated bot wallet — separate from any wallet you use for manual
trading or hold meaningful funds in.

Usage:
    python scripts/generate_wallet.py

This does NOT touch pump.fun, PumpPortal, any RPC, or the network at all —
it just generates a random keypair on this machine using the same solders
library the bot itself uses to sign transactions. Nothing is sent
anywhere; nothing is written to any file automatically.

The private key is shown ONCE. Save it somewhere safe immediately (a
password manager, or written down) — if you lose it before saving, the
wallet and anything in it is gone for good; there is no recovery.
"""
from __future__ import annotations

import sys


def main() -> int:
    from solders.keypair import Keypair

    keypair = Keypair()
    address = str(keypair.pubkey())
    private_key_base58 = str(keypair)

    print("=" * 70)
    print("WALLET BARU BERHASIL DIBUAT")
    print("=" * 70)
    print()
    print(f"Alamat publik (aman dibagikan, dipakai untuk menerima SOL):")
    print(f"  {address}")
    print()
    print(f"Private key (RAHASIA — JANGAN pernah dibagikan ke siapa pun):")
    print(f"  {private_key_base58}")
    print()
    print("=" * 70)
    print("LANGKAH SELANJUTNYA")
    print("=" * 70)
    print(f"""
1. Salin private key di atas, buka file .env, isi baris:
     SOLANA_PRIVATE_KEY={private_key_base58}
     SOLANA_WALLET_ADDRESS={address}

2. (Opsional tapi disarankan) Import private key ini ke aplikasi Phantom/
   Solflare di HP/browser Anda, supaya bisa lihat saldo & kirim SOL ke
   wallet ini dengan mudah lewat UI biasa:
     Phantom: Settings -> Import Private Key -> tempel private key di atas

3. Kirim sedikit SOL ke alamat publik di atas (jumlah yang Anda ikhlas
   kehilangan sepenuhnya — ini wallet khusus bot, bukan tabungan utama).

4. Jalankan `python scripts/check_pumpbot_setup.py` untuk memastikan
   semuanya terbaca dengan benar sebelum set LIVE_TRADING=true.

PENTING: private key di atas TIDAK disimpan di mana pun oleh script ini —
begitu jendela terminal ini ditutup/di-scroll hilang, tidak ada cara
mengambilnya lagi kecuali Anda sudah menyalinnya. Simpan sekarang juga.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
