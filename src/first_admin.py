import asyncio

from src.db.mongo import connect, disconnect
from src.repositories.admin_users_repo import create_admin_user


async def main() -> None:
    await connect()
    await create_admin_user(
        email="admin@aitc.vn",
        password="YourStrongPassword123!",  # change to whatever you want
        display_name="AITC Admin",
    )
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
