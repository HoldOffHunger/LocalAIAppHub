import ctypes
import sys


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class Presence:
    """Whether Ben is at the PC, for the night shift that runs until he wakes: Windows' own count of how long since the
    keyboard or mouse was last touched. Only real input counts; Chron Jobs, the workers and the pages never touch it."""

    def idle_seconds(self) -> float | None:
        # None when Windows won't say, so the shift can wait rather than guess
        if sys.platform != "win32":
            return None
        info = _LastInput(ctypes.sizeof(_LastInput), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000  # both wrap every 49 days
