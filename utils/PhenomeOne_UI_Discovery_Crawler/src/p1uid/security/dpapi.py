r"""Windows DPAPI (CryptProtectData) wrapper — user-scoped encryption at rest.

Ciphertext produced here can only be decrypted by the same Windows user account
on the same machine, which is exactly the trust boundary we want for a portable
tool: copying `sessions\session.bin` to another machine yields nothing usable.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x1
ENTROPY = b"PhenomeOne-UI-Discovery/v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    _keepalive = None      # holds the backing buffer alive; see `of()`

    @classmethod
    def of(cls, data: bytes) -> "_Blob":
        buf = ctypes.create_string_buffer(data, len(data))
        blob = cls(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        # The struct holds only a raw pointer, so the buffer must be kept alive
        # for as long as the struct is - otherwise CPython frees it the moment
        # this method returns and the API reads freed memory.
        blob._keepalive = buf
        return blob

    def value(self) -> bytes:
        return ctypes.string_at(self.pbData, self.cbData)


def available() -> bool:
    return sys.platform == "win32"


def _call(fn_name: str, data: bytes) -> bytes:
    if not available():
        raise OSError("DPAPI is only available on Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    blob_in, entropy, blob_out = _Blob.of(data), _Blob.of(ENTROPY), _Blob()
    fn = getattr(crypt32, fn_name)
    ok = fn(ctypes.byref(blob_in), None, ctypes.byref(entropy), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise OSError(ctypes.get_last_error(), f"{fn_name} failed")
    try:
        return blob_out.value()
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def protect(plaintext: bytes) -> bytes:
    return _call("CryptProtectData", plaintext)


def unprotect(ciphertext: bytes) -> bytes:
    return _call("CryptUnprotectData", ciphertext)
