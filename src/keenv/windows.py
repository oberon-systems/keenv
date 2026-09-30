"""The reduced Windows client: a waiter that knows nothing, and a resolver.

Windows has no exec, so the process that opened the database cannot become
the command. The waiter starts a resolver, which opens the database, starts
the command, hands the waiter a handle on it and exits, taking the database
and the resolved values with it. The waiter only ever holds that handle.
"""

import ctypes
import os
import shutil
import signal
import subprocess
import sys

# `<waiter pid>:<pipe handle>`, set for the resolver and never for the command.
RESOLVER = 'KEENV_RESOLVER'

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_CLOSE_SOURCE = 0x1
DUPLICATE_SAME_ACCESS = 0x2
INFINITE = 0xFFFFFFFF
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x4


def _kernel32() -> ctypes.CDLL:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle, dword, boolean = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    signatures = {
        'OpenProcess': (handle, (dword, boolean, dword)),
        'GetCurrentProcess': (handle, ()),
        'DuplicateHandle': (boolean, (
            handle, handle, handle, ctypes.POINTER(handle), dword, boolean,
            dword,
        )),
        'WaitForSingleObject': (dword, (handle, dword)),
        'GetExitCodeProcess': (boolean, (handle, ctypes.POINTER(dword))),
        'CloseHandle': (boolean, (handle,)),
        'GetStdHandle': (handle, (dword,)),
        'GetConsoleMode': (boolean, (handle, ctypes.POINTER(dword))),
        'SetConsoleMode': (boolean, (handle, dword)),
    }
    for name, (restype, argtypes) in signatures.items():
        function = getattr(kernel32, name)
        function.restype, function.argtypes = restype, argtypes
    return kernel32


def console() -> bool:
    """Let the console draw colour, false when there is no console to ask."""
    from ctypes import wintypes

    kernel32 = _kernel32()
    enabled = False
    for std in (STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
        handle = kernel32.GetStdHandle(std & 0xFFFFFFFF)
        mode = wintypes.DWORD()
        if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            wanted = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            enabled = bool(kernel32.SetConsoleMode(handle, wanted)) or enabled
    return enabled


def wait(argv: list[str]) -> int:
    """Start the resolver on the same arguments, then wait on the command.

    Nothing here reads a config or the database: the only thing that ever
    reaches this process is a handle on the command the resolver started.
    """
    import msvcrt

    read_end, write_end = os.pipe()
    pipe = msvcrt.get_osfhandle(write_end)
    os.set_handle_inheritable(pipe, True)
    environment = {**os.environ, RESOLVER: f'{os.getpid()}:{pipe}'}

    # Ctrl-C belongs to the prompt or the command, which share this console.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    resolver = subprocess.Popen(
        [sys.executable, '-m', 'keenv', *argv],
        env=environment,
        startupinfo=subprocess.STARTUPINFO(
            lpAttributeList={'handle_list': [pipe]},
        ),
    )
    os.close(write_end)

    reply = b''
    while chunk := os.read(read_end, 64):
        reply += chunk
    os.close(read_end)
    code = resolver.wait()
    if not reply:
        return code
    return _exit_code(int(reply))


def _exit_code(process: int) -> int:
    from ctypes import wintypes

    kernel32 = _kernel32()
    code = wintypes.DWORD()
    try:
        kernel32.WaitForSingleObject(process, INFINITE)
        if not kernel32.GetExitCodeProcess(process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(process)
    return code.value


def hand_over(command: list[str], environment: dict[str, str],
              resolver: str) -> None:
    """Start the command, give the waiter a handle on it, and return.

    A command the waiter cannot be handed is killed rather than waited on
    here, since waiting here would keep the database in memory with it.
    """
    import msvcrt
    from ctypes import wintypes

    waiter_pid, pipe = (int(part) for part in resolver.split(':'))
    found = shutil.which(command[0], path=environment.get('PATH'))
    child = subprocess.Popen(
        [found or command[0], *command[1:]], env=environment,
    )

    kernel32 = _kernel32()
    duplicate = wintypes.HANDLE()
    handed = False
    waiter = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, waiter_pid)
    # The Popen handle keeps the pid from being reused while this runs.
    own = kernel32.OpenProcess(
        SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, child.pid,
    )
    if waiter and own:
        handed = bool(kernel32.DuplicateHandle(
            kernel32.GetCurrentProcess(), own, waiter,
            ctypes.byref(duplicate), 0, False,
            DUPLICATE_SAME_ACCESS | DUPLICATE_CLOSE_SOURCE,
        ))
    elif own:
        kernel32.CloseHandle(own)
    if waiter:
        kernel32.CloseHandle(waiter)
    if not handed:
        child.kill()
        raise ValueError('could not hand the command over to the waiter')

    with open(msvcrt.open_osfhandle(pipe, 0), 'wb') as channel:
        channel.write(str(duplicate.value).encode())
