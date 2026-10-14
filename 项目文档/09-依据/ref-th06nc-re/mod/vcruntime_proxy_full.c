/*
 * vcruntime140.dll proxy (complete) for th06nc
 * --------------------------------------------
 * Exports every function vcruntime140 exports (74 on Wine / VC++ 14.4x),
 * each as a one-instruction thunk (in .text) that tail-jumps through a
 * pointer resolved at load time from the real DLL in
 * C:\Windows\System32\vcruntime140.dll.
 *
 * This makes the proxy safe even when other modules in the process
 * (msvcp140, icu, vcruntime140_1, ...) import vcruntime140 symbols the
 * game itself does not use.
 *
 * Loaded at process start (the game statically imports VCRUNTIME140.dll),
 * so hooks are installed before any game code runs. Steam/Proton do not
 * manage this file.
 *
 * Build:
 *   x86_64-w64-mingw32-gcc -O2 -shared -o vcruntime140.dll \
 *       vcruntime_proxy_full.c vcruntime_thunks.S vcruntime140_full.def \
 *       -Wl,--exclude-all-symbols
 */

#include <windows.h>
#include <stdio.h>
#include <string.h>

#include "vcruntime_syms.h"

#define MOD_LOGFILE  "th06nc_vcmod.log"
#define MOD_LOGPREFIX "[vcruntime]"
#include "mod_core.h"

static HMODULE g_real;

static void resolve_all(void)
{
    g_real = LoadLibraryW(L"C:\\Windows\\System32\\vcruntime140.dll");
    logf_("real vcruntime140 = %p", (void *)g_real);
    if (!g_real) return;

    int ok = 0, missing = 0, nonexec = 0;
    for (unsigned i = 0; i < sizeof(g_syms) / sizeof(g_syms[0]); ++i) {
        void *p = (void *)GetProcAddress(g_real, g_syms[i].name);
        if (p) {
            MEMORY_BASIC_INFORMATION mbi;
            if (VirtualQuery(p, &mbi, sizeof(mbi))) {
                DWORD e = mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ |
                                         PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY);
                if (!e) {
                    ++nonexec;
                    logf_("WARNING: %s -> %p is not executable (protect=0x%lx)",
                          g_syms[i].name, p, (unsigned long)mbi.Protect);
                }
            }
            *g_syms[i].slot = p;
            ++ok;
        } else {
            ++missing;
            logf_("WARNING: real DLL has no %s", g_syms[i].name);
        }
    }
    logf_("forwarded %d/%d symbols (%d missing, %d non-executable)",
          ok, ok + missing, missing, nonexec);
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        wchar_t exe[MAX_PATH] = {0};
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        wchar_t *slash = wcsrchr(exe, L'\\');
        if (slash) slash[1] = 0;
        char narrow[MAX_PATH] = {0};
        WideCharToMultiByte(CP_ACP, 0, exe, -1, narrow, MAX_PATH, NULL, NULL);
        snprintf(g_log_path, MAX_PATH, "%s" MOD_LOGFILE, narrow);

        logf_("proxy base=%p", (void *)inst);
        resolve_all();
        mod_start(inst);
    }
    return TRUE;
}
