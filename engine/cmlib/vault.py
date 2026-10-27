"""vault.py - tokens and passwords, encrypted with Windows DPAPI.

DPAPI ties the encryption to this Windows user on this computer: the vault file is
useless if copied elsewhere. Values are never printed; only names are listed.

On non-Windows systems the vault refuses to work unless CM_VAULT_PLAINTEXT=1 is set
(tests only); then values are stored base64-encoded with 0600 permissions.
"""

import base64
import ctypes
import json
import os
import stat
import sys

from . import paths

ENTROPY = b"content-manager-fa/v1"


class VaultError(Exception):
    pass


def _win():
    return sys.platform == "win32"


if _win():
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _protect(data):
        src, _a = _blob(data)
        ent, _b = _blob(ENTROPY)
        out = _Blob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):
            raise VaultError("DPAPI encrypt failed")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)

    def _unprotect(data):
        src, _a = _blob(data)
        ent, _b = _blob(ENTROPY)
        out = _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):
            raise VaultError("DPAPI decrypt failed (different Windows user or computer?)")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)
else:
    def _check_plain():
        if os.environ.get("CM_VAULT_PLAINTEXT") != "1":
            raise VaultError("encrypted vault needs Windows (DPAPI); set CM_VAULT_PLAINTEXT=1 only for tests")

    def _protect(data):
        _check_plain()
        return data

    def _unprotect(data):
        _check_plain()
        return data


def _file():
    return os.path.join(paths.secrets_dir(), "vault.json")


def _load():
    try:
        with open(_file(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save(d):
    os.makedirs(paths.secrets_dir(), exist_ok=True)
    tmp = _file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp, _file())


def key(brand, name):
    return f"{brand}:{name}"


def put(brand, name, value):
    value = (value or "").strip()
    if not value:
        raise VaultError("empty value")
    d = _load()
    d[key(brand, name)] = base64.b64encode(_protect(value.encode("utf-8"))).decode()
    _save(d)


def get(brand, name, required=True):
    v = _load().get(key(brand, name))
    if v is None:
        if required:
            raise VaultError(f"secret '{name}' for brand '{brand}' is not set (cm secret set {brand} {name})")
        return None
    return _unprotect(base64.b64decode(v)).decode("utf-8")


def delete(brand, name):
    d = _load()
    if d.pop(key(brand, name), None) is None:
        return False
    _save(d)
    return True


def names(brand=None):
    out = sorted(_load())
    return [k.split(":", 1)[1] for k in out if brand is None or k.startswith(brand + ":")] if brand else out


def redact(text, brand):
    """Remove every stored secret value of the brand from text (for logs and errors)."""
    if not text:
        return text
    for n in names(brand):
        try:
            v = get(brand, n)
        except VaultError:
            continue
        if v and len(v) > 4:
            text = text.replace(v, "***")
    return text
