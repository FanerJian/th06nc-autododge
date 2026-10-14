/*
 * vcruntime140.dll proxy for th06nc (Touhou Koumakyou: New Classic)
 * ----------------------------------------------------------------
 * Why this DLL: the game statically imports VCRUNTIME140.dll, so it is
 * loaded at process start -- before the game's entry point and before
 * DxLib resolves anything. Steam/Proton do not manage this file, so
 * (unlike steam_api64.dll) it does not get restored or replaced.
 *
 * It forwards every function the game imports from VCRUNTIME140 to the
 * real DLL in C:\Windows\System32 (native Windows: the VC++ runtime;
 * Wine/Proton: the builtin), then installs the mod.
 *
 * The mod itself:
 *   - IAT-hooks kernel32!GetProcAddress + user32!MessageBoxA in the game
 *   - catches DxLib's dynamic user32 resolution and forces a modded
 *     window title
 *   - ALSO runs a polling renamer, which does not depend on hook timing:
 *     it finds our process's top-level window and sets the title directly
 *
 * Build:
 *   x86_64-w64-mingw32-gcc -O2 -shared -o vcruntime140.dll \
 *       vcruntime_proxy.c vcruntime140.def -Wl,--exclude-all-symbols
 *
 * Install (game dir):
 *   copy vcruntime140.dll .
 *   launch option: WINEDLLOVERRIDES="vcruntime140=n,b" %command%
 * Log: th06nc_vcmod.log next to the exe.
 */

#include <windows.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define MOD_TITLE L"\u6771\u65b9\u7d05\u9b54\u90f7: New Classic  [MODDED]"

static HMODULE g_real;
static char    g_log[MAX_PATH];

/* ---------------- logging ---------------- */
static void logf_(const char *fmt, ...)
{
    FILE *f = fopen(g_log, "a");
    if (!f) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(f, "[%02d:%02d:%02d.%03d] [vcruntime] ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

/* ---------------- real CRT lookup ---------------- */
static FARPROC real(const char *name)
{
    if (!g_real) {
        g_real = LoadLibraryW(L"C:\\Windows\\System32\\vcruntime140.dll");
        logf_("LoadLibrary(system32 vcruntime140) = %p", (void *)g_real);
    }
    FARPROC p = g_real ? GetProcAddress(g_real, name) : NULL;
    if (!p) logf_("WARNING: missing real export %s", name);
    return p;
}

/* ---------------- forwarded CRT functions ---------------- */
void *proxy_memset(void *d, int c, size_t n)
{
    typedef void *(*F)(void *, int, size_t);
    F f = (F)real("memset");
    return f ? f(d, c, n) : d;
}
void *proxy_memcpy(void *d, const void *s, size_t n)
{
    typedef void *(*F)(void *, const void *, size_t);
    F f = (F)real("memcpy");
    return f ? f(d, s, n) : d;
}
void *proxy_memmove(void *d, const void *s, size_t n)
{
    typedef void *(*F)(void *, const void *, size_t);
    F f = (F)real("memmove");
    return f ? f(d, s, n) : d;
}
int proxy_memcmp(const void *a, const void *b, size_t n)
{
    typedef int (*F)(const void *, const void *, size_t);
    F f = (F)real("memcmp");
    return f ? f(a, b, n) : 0;
}
char *proxy_strchr(const char *s, int c)
{
    typedef char *(*F)(const char *, int);
    F f = (F)real("strchr");
    return f ? f(s, c) : NULL;
}
char *proxy_strrchr(const char *s, int c)
{
    typedef char *(*F)(const char *, int);
    F f = (F)real("strrchr");
    return f ? f(s, c) : NULL;
}
int proxy_purecall(void)
{
    typedef int (*F)(void);
    F f = (F)real("_purecall");
    return f ? f() : 0;
}
void proxy_std_terminate(void)
{
    typedef void (*F)(void);
    F f = (F)real("__std_terminate");
    if (f) f();
}
void proxy_CxxThrowException(void *obj, void *type)
{
    typedef void (*F)(void *, void *);
    F f = (F)real("_CxxThrowException");
    if (f) f(obj, type);
}
long proxy_C_specific_handler(void *rec, void *frame, void *ctx, void *disp)
{
    typedef long (*F)(void *, void *, void *, void *);
    F f = (F)real("__C_specific_handler");
    return f ? f(rec, frame, ctx, disp) : 1;
}
void *proxy_current_exception(void)
{
    typedef void *(*F)(void);
    F f = (F)real("__current_exception");
    return f ? f() : NULL;
}
void *proxy_current_exception_context(void)
{
    typedef void *(*F)(void);
    F f = (F)real("__current_exception_context");
    return f ? f() : NULL;
}
void proxy_std_exception_copy(void *src, void *dst)
{
    typedef void (*F)(void *, void *);
    F f = (F)real("__std_exception_copy");
    if (f) f(src, dst);
}
void proxy_std_exception_destroy(void *data)
{
    typedef void (*F)(void *);
    F f = (F)real("__std_exception_destroy");
    if (f) f(data);
}

/* ---------------- IAT helpers ---------------- */
static IMAGE_THUNK_DATA64 *find_iat_slot(HMODULE mod, const char *dll, const char *func)
{
    BYTE *base = (BYTE *)mod;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY *dir = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir->Size) return NULL;
    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir->VirtualAddress);
    for (; imp->Name; ++imp) {
        if (_stricmp((const char *)(base + imp->Name), dll) != 0) continue;
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
    if (!slot) { logf_("note: %s!%s not imported", dll, func); return; }
    DWORD old;
    if (!VirtualProtect(&slot->u1.Function, sizeof(void *), PAGE_READWRITE, &old)) return;
    void *prev = (void *)slot->u1.Function;
    if (out_real && !*out_real) *out_real = prev;
    slot->u1.Function = (ULONG_PTR)hook;
    VirtualProtect(&slot->u1.Function, sizeof(void *), old, &old);
    logf_("IAT hooked %s!%s -> %p (was %p)", dll, func, hook, prev);
}

/* ---------------- hooks ---------------- */
static BOOL  (WINAPI *real_SetWindowTextW)(HWND, LPCWSTR);
static int   (WINAPI *real_MessageBoxA)(HWND, LPCSTR, LPCSTR, UINT);
static FARPROC (WINAPI *real_GetProcAddress)(HMODULE, LPCSTR);

static BOOL WINAPI hook_SetWindowTextW(HWND h, LPCWSTR s)
{
    logf_("SetWindowTextW(\"%ls\") intercepted -> modded title", s ? s : L"");
    return real_SetWindowTextW(h, MOD_TITLE);
}

static int WINAPI hook_MessageBoxA(HWND h, LPCSTR text, LPCSTR caption, UINT type)
{
    logf_("MessageBoxA caption=\"%s\" text=\"%s\"", caption ? caption : "", text ? text : "");
    return real_MessageBoxA ? real_MessageBoxA(h, text, caption, type) : 1;
}

static FARPROC WINAPI hook_GetProcAddress(HMODULE mod, LPCSTR name)
{
    FARPROC p = real_GetProcAddress(mod, name);
    if (name && _stricmp(name, "SetWindowTextW") == 0) {
        real_SetWindowTextW = (BOOL (WINAPI *)(HWND, LPCWSTR))p;
        logf_("GetProcAddress(\"SetWindowTextW\") intercepted -> title hook installed");
        return (FARPROC)hook_SetWindowTextW;
    }
    return p;
}

/* ---------------- polling renamer (timing independent) ---------------- */
static BOOL CALLBACK enum_cb(HWND hwnd, LPARAM lp)
{
    struct ctx { DWORD pid; HWND found; };
    struct ctx *c = (struct ctx *)lp;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != c->pid) return TRUE;
    if (!IsWindowVisible(hwnd)) return TRUE;
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

/* ---------------- worker ---------------- */
static DWORD WINAPI worker(LPVOID p)
{
    (void)p;
    /* wait until the main module's imports are resolved, then hook */
    HMODULE main = NULL;
    for (int i = 0; i < 2000; ++i) {
        HMODULE m = GetModuleHandleW(NULL);
        IMAGE_THUNK_DATA64 *slot = m ? find_iat_slot(m, "KERNEL32.dll", "GetProcAddress") : NULL;
        if (slot && slot->u1.Function) { main = m; break; }
        Sleep(5);
    }
    if (!main) { logf_("timed out waiting for main module imports"); return 0; }

    BYTE *base = (BYTE *)main;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    logf_("main module base=%p imageSize=0x%x entryRVA=0x%x",
          (void *)main, nt->OptionalHeader.SizeOfImage, nt->OptionalHeader.AddressOfEntryPoint);

    const BYTE expected[] = { 0x48,0x89,0x5c,0x24,0x08,0x48,0x89,0x6c,0x24,0x10,0x48,0x89,0x74,0x24,0x18 };
    BYTE *loader = base + 0x5a470;
    if (memcmp(loader, expected, sizeof(expected)) == 0)
        logf_("self-check OK: PKGL loader at %p matches analysis", (void *)loader);
    else
        logf_("self-check FAILED at %p (%02x %02x %02x %02x)", (void *)loader,
              loader[0], loader[1], loader[2], loader[3]);

    patch_iat(main, "KERNEL32.dll", "GetProcAddress", (void *)hook_GetProcAddress, (void **)&real_GetProcAddress);
    patch_iat(main, "USER32.dll", "MessageBoxA", (void *)hook_MessageBoxA, (void **)&real_MessageBoxA);
    patch_iat(main, "USER32.dll", "SetWindowTextW", (void *)hook_SetWindowTextW, (void **)&real_SetWindowTextW);

    /* re-assert the GetProcAddress hook in case the loader finished later */
    for (int i = 0; i < 2; ++i) {
        Sleep(1000);
        IMAGE_THUNK_DATA64 *slot = find_iat_slot(main, "KERNEL32.dll", "GetProcAddress");
        if (slot && (void *)slot->u1.Function != (void *)hook_GetProcAddress) {
            logf_("re-asserting GetProcAddress hook (was %p)", (void *)slot->u1.Function);
            patch_iat(main, "KERNEL32.dll", "GetProcAddress", (void *)hook_GetProcAddress, NULL);
        }
    }
    logf_("hook stage done; starting title renamer");
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
        wchar_t exe[MAX_PATH] = {0};
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        wchar_t *slash = wcsrchr(exe, L'\\');
        if (slash) slash[1] = 0;
        char narrow[MAX_PATH] = {0};
        WideCharToMultiByte(CP_ACP, 0, exe, -1, narrow, MAX_PATH, NULL, NULL);
        snprintf(g_log, MAX_PATH, "%sth06nc_vcmod.log", narrow);

        logf_("=== vcruntime140 proxy loaded into pid %lu ===", GetCurrentProcessId());
        HANDLE t = CreateThread(NULL, 0, worker, NULL, 0, NULL);
        if (t) CloseHandle(t);
        t = CreateThread(NULL, 0, title_thread, NULL, 0, NULL);
        if (t) CloseHandle(t);
    }
    return TRUE;
}
