/*
 * steam_api64.dll proxy for th06nc (Touhou Koumakyou: New Classic)
 * ---------------------------------------------------------------
 * The game imports steam_api64.dll at load time, so replacing that DLL
 * with this proxy runs our code BEFORE the game's entry point -- no
 * external injector needed.
 *
 * What it does:
 *   1. forwards the 9 SteamAPI imports to the real DLL, which must be
 *      renamed to steam_api64_orig.dll
 *   2. SteamAPI_RestartAppIfNecessary() always returns false, so the
 *      game can be started outside the Steam client
 *   3. after the loader settles, it patches the game module's USER32
 *      IAT so CreateWindowExW / SetWindowTextW / SetWindowTextA show a
 *      custom window title  (a real, visible mod)
 *   4. logs everything, including a byte-level self-check of the PKGL
 *      archive loader we reverse engineered (RVA 0x5a470) so you can
 *      confirm the build matches the analysis
 *
 * Build (mingw-w64):
 *   x86_64-w64-mingw32-gcc -O2 -shared -o steam_api64.dll proxy.c steam_api64.def
 *
 * Install:
 *   cd <game dir>
 *   mv steam_api64.dll steam_api64_orig.dll
 *   cp steam_api64.dll .
 * Uninstall: delete the proxy and rename steam_api64_orig.dll back.
 * (Or in Steam: right click game -> Properties -> Installed Files ->
 *  Verify integrity of game files.)
 */

#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define MOD_TITLE L"\u6771\u65b9\u7d05\u9b54\u90f7: New Classic  [MODDED]"

static HMODULE g_orig;
static char    g_log[MAX_PATH];

/* ---------- logging ---------- */
static void logf_(const char *fmt, ...)
{
    FILE *f = fopen(g_log, "a");
    if (!f) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(f, "[%02d:%02d:%02d.%03d] ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

/* ---------- real SteamAPI lookup ---------- */
static FARPROC orig(const char *name)
{
    if (!g_orig) {
        g_orig = LoadLibraryA("steam_api64_orig.dll");
        logf_("LoadLibrary(steam_api64_orig.dll) = %p", (void *)g_orig);
    }
    FARPROC p = g_orig ? GetProcAddress(g_orig, name) : NULL;
    if (!p) logf_("WARNING: missing original export %s", name);
    return p;
}

static void ensure_patched(void);   /* defined below */

/* ---------- exported SteamAPI wrappers ---------- */
__declspec(dllexport) void SteamAPI_RunCallbacks(void)
{
    typedef void (*F)(void);
    F f = (F)orig("SteamAPI_RunCallbacks");
    if (f) f();
}

__declspec(dllexport) unsigned int SteamAPI_GetHSteamUser(void)
{
    typedef unsigned int (*F)(void);
    F f = (F)orig("SteamAPI_GetHSteamUser");
    return f ? f() : 0;
}

/* THE MOD: pretend Steam already launched us */
__declspec(dllexport) unsigned char SteamAPI_RestartAppIfNecessary(unsigned int appid)
{
    logf_("SteamAPI_RestartAppIfNecessary(appid=%u) -> forced FALSE (run outside Steam)", appid);
    ensure_patched();
    return 0;
}

__declspec(dllexport) void SteamAPI_RegisterCallback(void *cb, int id)
{
    typedef void (*F)(void *, int);
    F f = (F)orig("SteamAPI_RegisterCallback");
    if (f) f(cb, id);
}

__declspec(dllexport) void SteamAPI_UnregisterCallback(void *cb)
{
    typedef void (*F)(void *);
    F f = (F)orig("SteamAPI_UnregisterCallback");
    if (f) f(cb);
}

__declspec(dllexport) void SteamAPI_Shutdown(void)
{
    typedef void (*F)(void);
    F f = (F)orig("SteamAPI_Shutdown");
    if (f) f();
}

__declspec(dllexport) void *SteamInternal_FindOrCreateUserInterface(unsigned int user, const char *ver)
{
    typedef void *(*F)(unsigned int, const char *);
    F f = (F)orig("SteamInternal_FindOrCreateUserInterface");
    void *p = f ? f(user, ver) : NULL;
    logf_("SteamInternal_FindOrCreateUserInterface(user=%u, \"%s\") -> %p", user, ver ? ver : "", p);
    return p;
}

__declspec(dllexport) unsigned char SteamInternal_SteamAPI_Init(const char *versions, int *err)
{
    ensure_patched();   /* patch before the game checks the result */
    typedef unsigned char (*F)(const char *, int *);
    F f = (F)orig("SteamInternal_SteamAPI_Init");
    unsigned char r = f ? f(versions, err) : 0;
#ifdef FAKE_STEAM_OK
    logf_("SteamInternal_SteamAPI_Init -> %u (err=%d); MOD forcing success", r, err ? *err : -1);
    r = 1;
#else
    logf_("SteamInternal_SteamAPI_Init -> %u (err=%d)", r, err ? *err : -1);
#endif
    return r;
}

__declspec(dllexport) void *SteamInternal_ContextInit(void *ctx)
{
    typedef void *(*F)(void *);
    F f = (F)orig("SteamInternal_ContextInit");
    return f ? f(ctx) : NULL;
}

/* ---------- window title hooks ---------- */
static HWND  (WINAPI *real_CreateWindowExW)(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
static HWND  (WINAPI *real_CreateWindowExA)(DWORD, LPCSTR, LPCSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
static BOOL  (WINAPI *real_SetWindowTextW)(HWND, LPCWSTR);
static BOOL  (WINAPI *real_SetWindowTextA)(HWND, LPCSTR);
static int   (WINAPI *real_MessageBoxA)(HWND, LPCSTR, LPCSTR, UINT);
static FARPROC (WINAPI *real_GetProcAddress)(HMODULE, LPCSTR);

static HWND WINAPI hook_CreateWindowExW(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
static HWND WINAPI hook_CreateWindowExA(DWORD, LPCSTR, LPCSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
static BOOL WINAPI hook_SetWindowTextW(HWND, LPCWSTR);
static BOOL WINAPI hook_SetWindowTextA(HWND, LPCSTR);

/* DxLib resolves most of user32 through GetProcAddress, so intercept
   that instead of relying on the static IAT. */
static FARPROC WINAPI hook_GetProcAddress(HMODULE mod, LPCSTR name)
{
    FARPROC p = real_GetProcAddress(mod, name);
    if (!name) return p;

    if (_stricmp(name, "SetWindowTextW") == 0) {
        real_SetWindowTextW = (BOOL (WINAPI *)(HWND, LPCWSTR))p;
        logf_("GetProcAddress(\"%s\") intercepted -> title hook installed", name);
        return (FARPROC)hook_SetWindowTextW;
    }
    if (_stricmp(name, "SetWindowTextA") == 0) {
        real_SetWindowTextA = (BOOL (WINAPI *)(HWND, LPCSTR))p;
        logf_("GetProcAddress(\"%s\") intercepted -> title hook installed", name);
        return (FARPROC)hook_SetWindowTextA;
    }
    if (_stricmp(name, "CreateWindowExW") == 0) {
        real_CreateWindowExW = (HWND (WINAPI *)(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID))p;
        logf_("GetProcAddress(\"%s\") intercepted -> window hook installed", name);
        return (FARPROC)hook_CreateWindowExW;
    }
    if (_stricmp(name, "CreateWindowExA") == 0) {
        real_CreateWindowExA = (HWND (WINAPI *)(DWORD, LPCSTR, LPCSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID))p;
        logf_("GetProcAddress(\"%s\") intercepted -> window hook installed", name);
        return (FARPROC)hook_CreateWindowExA;
    }
    return p;
}

/* capture any dialog the game throws at the player */
static int WINAPI hook_MessageBoxA(HWND h, LPCSTR text, LPCSTR caption, UINT type)
{
    logf_("MessageBoxA caption=\"%s\" text=\"%s\"", caption ? caption : "", text ? text : "");
    if (real_MessageBoxA) return real_MessageBoxA(h, text, caption, type);
    return 1;
}

static HWND WINAPI hook_CreateWindowExW(DWORD ex, LPCWSTR cls, LPCWSTR name, DWORD style,
                                        int x, int y, int w, int h, HWND parent, HMENU menu,
                                        HINSTANCE inst, LPVOID param)
{
    HWND hwnd = real_CreateWindowExW(ex, cls, name, style, x, y, w, h, parent, menu, inst, param);
    logf_("CreateWindowExW(%ls) -> hwnd %p; forcing modded title", name ? name : L"", (void *)hwnd);
    if (hwnd) real_SetWindowTextW(hwnd, MOD_TITLE);
    return hwnd;
}

static HWND WINAPI hook_CreateWindowExA(DWORD ex, LPCSTR cls, LPCSTR name, DWORD style,
                                        int x, int y, int w, int h, HWND parent, HMENU menu,
                                        HINSTANCE inst, LPVOID param)
{
    HWND hwnd = real_CreateWindowExA(ex, cls, name, style, x, y, w, h, parent, menu, inst, param);
    logf_("CreateWindowExA(%s) -> hwnd %p; forcing modded title", name ? name : "", (void *)hwnd);
    if (hwnd) real_SetWindowTextW(hwnd, MOD_TITLE);
    return hwnd;
}

static BOOL WINAPI hook_SetWindowTextW(HWND h, LPCWSTR s)
{
    logf_("SetWindowTextW(\"%ls\") intercepted -> \"%ls\"", s ? s : L"", MOD_TITLE);
    return real_SetWindowTextW(h, MOD_TITLE);
}

static BOOL WINAPI hook_SetWindowTextA(HWND h, LPCSTR s)
{
    logf_("SetWindowTextA(\"%s\") intercepted -> modded title", s ? s : "");
    return real_SetWindowTextW(h, MOD_TITLE);
}

/* ---------- IAT patching of the main module ---------- */
static IMAGE_THUNK_DATA64 *find_iat_slot(HMODULE mod, const char *dll, const char *func)
{
    BYTE *base = (BYTE *)mod;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY *dir = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir->Size) return NULL;

    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir->VirtualAddress);
    for (; imp->Name; ++imp) {
        const char *modname = (const char *)(base + imp->Name);
        if (_stricmp(modname, dll) != 0) continue;
        IMAGE_THUNK_DATA64 *oft = (IMAGE_THUNK_DATA64 *)(base + imp->OriginalFirstThunk);
        IMAGE_THUNK_DATA64 *ft  = (IMAGE_THUNK_DATA64 *)(base + imp->FirstThunk);
        for (; oft->u1.AddressOfData; ++oft, ++ft) {
            if (oft->u1.Ordinal & IMAGE_ORDINAL_FLAG64) continue;
            IMAGE_IMPORT_BY_NAME *ibn = (IMAGE_IMPORT_BY_NAME *)(base + oft->u1.AddressOfData);
            if (strcmp((const char *)ibn->Name, func) == 0) return ft;
        }
        return NULL;
    }
    return NULL;
}

static void patch_iat(HMODULE mod, const char *dll, const char *func, void *hook, void **out_real)
{
    IMAGE_THUNK_DATA64 *slot = find_iat_slot(mod, dll, func);
    if (!slot) { logf_("note: %s!%s not imported by main module", dll, func); return; }

    DWORD old;
    if (!VirtualProtect(&slot->u1.Function, sizeof(void *), PAGE_READWRITE, &old)) {
        logf_("VirtualProtect failed for %s!%s", dll, func);
        return;
    }
    void *prev = (void *)slot->u1.Function;
    if (out_real && !*out_real) *out_real = prev;
    slot->u1.Function = (ULONG_PTR)hook;
    VirtualProtect(&slot->u1.Function, sizeof(void *), old, &old);
    logf_("IAT hooked %s!%s -> %p (was %p)", dll, func, hook, prev);
}

/* ---------- patch stage (runs once, from the first Steam call) ---------- */
static volatile LONG g_patched = 0;

static void ensure_patched(void)
{
    if (InterlockedCompareExchange(&g_patched, 1, 0) != 0) return;
    logf_("patch stage running");

    HMODULE mod = GetModuleHandleW(NULL);
    BYTE *base = (BYTE *)mod;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    logf_("main module base=%p imageSize=0x%x entryRVA=0x%x",
          (void *)mod, nt->OptionalHeader.SizeOfImage,
          nt->OptionalHeader.AddressOfEntryPoint);

    /* self-check: PKGL archive loader we reverse engineered */
    const BYTE expected[] = { 0x48,0x89,0x5c,0x24,0x08,0x48,0x89,0x6c,0x24,0x10,0x48,0x89,0x74,0x24,0x18 };
    BYTE *loader = base + 0x5a470;
    if (memcmp(loader, expected, sizeof(expected)) == 0) {
        logf_("self-check OK: PKGL loader prologue at %p matches analysis (RVA 0x5a470)", (void *)loader);
    } else {
        logf_("self-check FAILED at %p: bytes %02x %02x %02x %02x ...",
              (void *)loader, loader[0], loader[1], loader[2], loader[3]);
    }

    /* prove we can write to the game's code (write the same byte back) */
    DWORD old;
    if (VirtualProtect(loader, 1, PAGE_EXECUTE_READWRITE, &old)) {
        BYTE b = loader[0];
        loader[0] = b;
        VirtualProtect(loader, 1, old, &old);
        logf_("code write test on %p OK (byte %02x restored)", (void *)loader, b);
    }

    patch_iat(mod, "KERNEL32.dll", "GetProcAddress", (void *)hook_GetProcAddress, (void **)&real_GetProcAddress);
    patch_iat(mod, "USER32.dll", "MessageBoxA", (void *)hook_MessageBoxA, (void **)&real_MessageBoxA);
    patch_iat(mod, "USER32.dll", "CreateWindowExW", (void *)hook_CreateWindowExW, (void **)&real_CreateWindowExW);
    patch_iat(mod, "USER32.dll", "SetWindowTextW", (void *)hook_SetWindowTextW, (void **)&real_SetWindowTextW);

    logf_("mod initialised");
}

/* ---------- polling renamer (works even if hooks are too late) ---------- */
static BOOL CALLBACK enum_cb(HWND hwnd, LPARAM lp)
{
    struct ctx { DWORD pid; HWND found; };
    struct ctx *c = (struct ctx *)lp;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != c->pid || !IsWindowVisible(hwnd)) return TRUE;
    RECT r;
    if (!GetWindowRect(hwnd, &r)) return TRUE;
    if (r.right - r.left < 64 || r.bottom - r.top < 64) return TRUE;
    c->found = hwnd;
    return FALSE;
}

static HWND find_our_window(void)
{
    struct ctx { DWORD pid; HWND found; } c;
    c.pid = GetCurrentProcessId();
    c.found = NULL;
    EnumWindows(enum_cb, (LPARAM)&c);
    return c.found;
}

static DWORD WINAPI title_thread(LPVOID p)
{
    (void)p;
    for (int i = 0; i < 240; ++i) {
        HWND h = find_our_window();
        if (h) {
            WCHAR cur[256] = {0};
            GetWindowTextW(h, cur, 255);
            if (wcscmp(cur, MOD_TITLE) != 0) {
                SetWindowTextW(h, MOD_TITLE);
                logf_("polling renamer set title (was \"%ls\")", cur);
            }
        }
        Sleep(250);
    }
    return 0;
}

static DWORD WINAPI worker(LPVOID param)
{
    (void)param;
    Sleep(300);            /* fallback path if the game never calls Steam */
    ensure_patched();

    /* the loader may finish resolving imports after we patched, and DxLib
       may cache GetProcAddress results early -- re-assert the hook twice */
    HMODULE mod = GetModuleHandleW(NULL);
    for (int i = 0; i < 2; ++i) {
        Sleep(1500);
        IMAGE_THUNK_DATA64 *slot = find_iat_slot(mod, "KERNEL32.dll", "GetProcAddress");
        if (!slot) continue;
        void *cur = (void *)slot->u1.Function;
        if (cur == (void *)hook_GetProcAddress) {
            logf_("verify: GetProcAddress hook still in place");
        } else {
            logf_("verify: GetProcAddress hook was %p -- re-hooking", cur);
            patch_iat(mod, "KERNEL32.dll", "GetProcAddress", (void *)hook_GetProcAddress,
                      (void **)&real_GetProcAddress);
        }
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)inst; (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
        /* log file next to the exe */
        wchar_t exe[MAX_PATH] = {0};
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        wchar_t *slash = wcsrchr(exe, L'\\');
        if (slash) slash[1] = 0; else exe[0] = 0;
        char narrow[MAX_PATH] = {0};
        WideCharToMultiByte(CP_ACP, 0, exe, -1, narrow, MAX_PATH, NULL, NULL);
        snprintf(g_log, MAX_PATH, "%sth06nc_mod.log", narrow);

        logf_("=== proxy steam_api64 loaded into pid %lu ===", GetCurrentProcessId());
        HANDLE t = CreateThread(NULL, 0, worker, NULL, 0, NULL);
        if (t) CloseHandle(t);
        t = CreateThread(NULL, 0, title_thread, NULL, 0, NULL);
        if (t) CloseHandle(t);
    }
    return TRUE;
}
