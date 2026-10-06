"""Versioned password hashes with bounded work off the HTTP event loop."""
import asyncio
import hashlib
import secrets

from .registration import RegistrationError


ITERATIONS = 600_000


def validate_password(password):
    if (not isinstance(password, str) or not 8 <= len(password) <= 128
            or any(ord(char) < 32 or ord(char) == 127 for char in password)):
        raise RegistrationError("密码需为 8–128 个字符，不能包含控制字符")
    return password


def hash_password(password):
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def check_password(password, encoded):
    validate_password(password)
    try:
        algorithm, count, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or count != str(ITERATIONS) or len(salt) != 32 or len(expected) != 64:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS)
        return secrets.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


class PasswordWork:
    def __init__(self):
        self.slots, self.tasks = asyncio.Semaphore(2), set()

    async def run(self, operation, *args):
        try:
            await asyncio.wait_for(self.slots.acquire(), 2)
        except TimeoutError:
            raise RegistrationError("认证服务繁忙，请稍后重试", 503, "authentication_busy") from None
        task = asyncio.create_task(asyncio.to_thread(operation, *args))
        self.tasks.add(task)
        def completed(result):
            self.tasks.discard(result)
            self.slots.release()
            if not result.cancelled():
                result.exception()
        task.add_done_callback(completed)
        return await asyncio.shield(task)

    async def close(self):
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
