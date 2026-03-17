"""
create_admin.py - Rode na pasta backend para criar/corrigir o admin

Uso:
  python create_admin.py

Coloque na pasta E:\nutty-saas\backend\ e rode com o backend PARADO.
"""
import sys
import os

# Adiciona o path do backend
sys.path.insert(0, os.path.dirname(__file__))

import bcrypt
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

EMAIL    = "admin@nuttylogic.com.br"
PASSWORD = "NuttyAdmin@2026!"
NAME     = "Admin Master"

def main():
    print(f"Conectando ao Supabase: {SUPABASE_URL}")
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Gerar hash
    hashed = bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")
    print(f"Hash gerado: {hashed[:30]}...")

    # Verificar hash
    ok = bcrypt.checkpw(PASSWORD.encode("utf-8"), hashed.encode("utf-8"))
    print(f"Verificação: {'✅ OK' if ok else '❌ FALHOU'}")

    if not ok:
        print("Erro ao gerar hash!")
        return

    # Upsert na tabela app_users
    result = supabase.table("app_users").upsert({
        "email": EMAIL,
        "password_hash": hashed,
        "full_name": NAME,
        "role": "admin",
        "is_active": True,
    }, on_conflict="email").execute()

    if result.data:
        user = result.data[0]
        print(f"\n✅ Admin criado/atualizado com sucesso!")
        print(f"   ID:    {user['id']}")
        print(f"   Email: {user['email']}")
        print(f"   Role:  {user['role']}")
        print(f"\n🔑 Login: {EMAIL}")
        print(f"🔑 Senha: {PASSWORD}")
    else:
        print("❌ Erro ao salvar no banco")
        print(result)

if __name__ == "__main__":
    main()