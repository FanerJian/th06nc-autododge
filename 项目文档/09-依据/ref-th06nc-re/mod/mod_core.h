/*
 * mod_core.h -- shared mod machinery for the th06nc DLL proxies.
 *
 * Included by exactly one .c file per DLL. The includer must define:
 *   MOD_LOGFILE   log file name, e.g. "th06nc_vcmod.log"
 *   MOD_LOGPREFIX short tag, e.g. "[vcruntime]"
 * and provide mod_resolve_symbols() (forwarders) if it needs them.
 *
 * Provides: logging, IAT helpers, GetProcAddress/MessageBoxA/
 * SetWindowTextW hooks, the PKGL self-check, a polling window renamer
 * and mod_start() to spawn the worker threads.
 */

#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#ifndef MOD_LOGFILE
#define MOD_LOGFILE "th06nc_mod.log"
#endif
#ifndef MOD_LOGPREFIX
#define MOD_LOGPREFIX "[mod]"
#endif

#define MOD_TITLE L"\u6771\u65b9\u7d05\u9b54\u90f7: New Classic  [MODDED]"

static WCHAR g_title[256] = MOD_TITLE;
static double g_frame_scale = 1.0;   /* <1.0 = shorter waits = higher loop rate */
static double g_target_fps = 60.0;   /* patches the hardcoded 60.0 frame-rate constant */

static char g_log_path[MAX_PATH];

static void logf_(const char *fmt, ...)
{
    FILE *f = fopen(g_log_path, "a");
    if (!f) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(f, "[%02d:%02d:%02d.%03d] %s ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, MOD_LOGPREFIX);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}


/* ---------------- config file (th06nc_mod.ini) ---------------- */
static void mod_load_config(void)
{
    char path[MAX_PATH];
    strncpy(path, g_log_path, MAX_PATH - 1);
    path[MAX_PATH - 1] = 0;
    char *slash = strrchr(path, '\\');
    if (slash) slash[1] = 0; else path[0] = 0;
    strncat(path, "th06nc_mod.ini", MAX_PATH - strlen(path) - 1);
    FILE *f = fopen(path, "r");
    if (!f) { logf_("no config file (%s); using defaults", path); return; }
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = 0;
        char *k = line, *v = eq + 1;
        while (*k == ' ' || *k == '\t') ++k;
        while (*v == ' ' || *v == '\t') ++v;
        char *end = v + strlen(v);
        while (end > v && (end[-1] == '\n' || end[-1] == '\r' || end[-1] == ' ')) *--end = 0;
        if (!_stricmp(k, "title")) {
            MultiByteToWideChar(CP_UTF8, 0, v, -1, g_title, 256);
        } else if (!_stricmp(k, "frame_scale")) {
            double d = atof(v);
            if (d > 0.05 && d < 20.0) g_frame_scale = d;
        } else if (!_stricmp(k, "target_fps")) {
            double d = atof(v);
            if (d >= 10.0 && d <= 1000.0) g_target_fps = d;
        }
    }
    fclose(f);
    logf_("config: title set, frame_scale=%.4f, target_fps=%.1f", g_frame_scale, g_target_fps);
}


/* ---------------- frame-rate constant patch ----------------
 * The limiter computes its frame interval as (freq / 60.0 + 0.5)
 * from a hardcoded double at RVA 0x30ce38 (single reference:
 * 0x14003cb85). Rewriting it changes the pacing target.
 */
static void mod_patch_frame_rate(void)
{
    if (g_target_fps <= 0.0 || g_target_fps == 60.0) return;
    HMODULE main = GetModuleHandleW(NULL);
    if (!main) { logf_("frame-rate patch: no main module"); return; }
    BYTE *addr = (BYTE *)main + 0x30ce38;
    double cur = 0.0;
    memcpy(&cur, addr, sizeof(cur));
    logf_("frame-rate constant at %p = %.4f (want %.1f)", (void *)addr, cur, g_target_fps);
    if (cur < 55.0 || cur > 65.0) {
        logf_("frame-rate constant unexpected - NOT patching");
        return;
    }
    DWORD old;
    if (!VirtualProtect(addr, sizeof(double), PAGE_READWRITE, &old)) {
        logf_("frame-rate patch: VirtualProtect failed");
        return;
    }
    memcpy(addr, &g_target_fps, sizeof(g_target_fps));
    VirtualProtect(addr, sizeof(double), old, &old);
    logf_("patched frame-rate constant: %.4f -> %.4f", cur, g_target_fps);
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
static MMRESULT (WINAPI *real_timeSetEvent)(UINT, UINT, LPTIMECALLBACK, DWORD_PTR, UINT);
static MMRESULT WINAPI hook_timeSetEvent(UINT, UINT, LPTIMECALLBACK, DWORD_PTR, UINT);
static BOOL  (WINAPI *real_SetWindowTextW)(HWND, LPCWSTR);
static int   (WINAPI *real_MessageBoxA)(HWND, LPCSTR, LPCSTR, UINT);
static FARPROC (WINAPI *real_GetProcAddress)(HMODULE, LPCSTR);

static BOOL WINAPI hook_SetWindowTextW(HWND h, LPCWSTR s)
{
    logf_("SetWindowTextW(\"%ls\") intercepted -> modded title", s ? s : L"");
    return real_SetWindowTextW ? real_SetWindowTextW(h, g_title) : FALSE;
}

static int WINAPI hook_MessageBoxA(HWND h, LPCSTR text, LPCSTR caption, UINT type)
{
    logf_("MessageBoxA caption=\"%s\" text=\"%s\"", caption ? caption : "", text ? text : "");
    return real_MessageBoxA ? real_MessageBoxA(h, text, caption, type) : 1;
}

static FARPROC WINAPI hook_GetProcAddress(HMODULE mod, LPCSTR name)
{
    FARPROC p = real_GetProcAddress(mod, name);
    if (name && _stricmp(name, "timeSetEvent") == 0) {
        real_timeSetEvent = (MMRESULT (WINAPI *)(UINT, UINT, LPTIMECALLBACK, DWORD_PTR, UINT))p;
        logf_("GetProcAddress(\"timeSetEvent\") intercepted -> timer hook installed");
        return (FARPROC)hook_timeSetEvent;
    }
    if (name && _stricmp(name, "SetWindowTextW") == 0) {
        real_SetWindowTextW = (BOOL (WINAPI *)(HWND, LPCWSTR))p;
        logf_("GetProcAddress(\"SetWindowTextW\") intercepted -> title hook installed");
        return (FARPROC)hook_SetWindowTextW;
    }
    return p;
}


/* ---------------- frame-timing instrumentation ---------------- */
static BOOL (WINAPI *real_SetWaitableTimerEx)(HANDLE, const LARGE_INTEGER *, LONG,
        PTIMERAPCROUTINE, LPVOID, PREASON_CONTEXT, ULONG);
static HANDLE (WINAPI *real_CreateWaitableTimerExW)(LPSECURITY_ATTRIBUTES, LPCWSTR, DWORD, DWORD);

static BOOL WINAPI hook_SetWaitableTimerEx(HANDLE h, const LARGE_INTEGER *due, LONG period,
        PTIMERAPCROUTINE fn, LPVOID arg, PREASON_CONTEXT ctx, ULONG tol)
{
    static DWORD last = 0; static int n = 0; static double lastms = 0;
    DWORD now = GetTickCount();
    ++n;
    if (due && due->QuadPart < 0) lastms = (double)(-due->QuadPart) / 10000.0;
    if (now - last >= 1000) {
        logf_("frame timer: %d waits/sec, last wait %.3f ms, period=%ld, scale=%.4f",
              n, lastms, period, g_frame_scale);
        n = 0; last = now;
    }
    const LARGE_INTEGER *pd = due;
    LARGE_INTEGER scaled;
    LONG sp = period;
    if (g_frame_scale != 1.0) {
        if (due && due->QuadPart < 0) {          /* relative: scale the wait */
            scaled.QuadPart = (LONGLONG)((double)due->QuadPart * g_frame_scale);
            pd = &scaled;
        }
        if (period > 0) sp = (LONG)(period * g_frame_scale);   /* periodic: scale rate */
    }
    return real_SetWaitableTimerEx ? real_SetWaitableTimerEx(h, pd, sp, fn, arg, ctx, tol) : FALSE;
}

static HANDLE WINAPI hook_CreateWaitableTimerExW(LPSECURITY_ATTRIBUTES sa, LPCWSTR name,
        DWORD flags, DWORD access)
{
    logf_("CreateWaitableTimerExW flags=0x%lx (high-res=%d)", (unsigned long)flags,
          (flags & 0x2) ? 1 : 0);
    return real_CreateWaitableTimerExW ? real_CreateWaitableTimerExW(sa, name, flags, access) : NULL;
}


/* ---------------- other pacing primitives ---------------- */
static DWORD (WINAPI *real_WaitForSingleObject)(HANDLE, DWORD);
static BOOL  (WINAPI *real_SleepConditionVariableSRW)(PCONDITION_VARIABLE, PCRITICAL_SECTION, DWORD, ULONG);
static BOOL  (WINAPI *real_QueryPerformanceCounter)(LARGE_INTEGER *);

static DWORD WINAPI hook_WaitForSingleObject(HANDLE h, DWORD ms)
{
    static DWORD last = 0; static int n = 0; static DWORD lastms = 0;
    DWORD now = GetTickCount(); ++n; lastms = ms;
    if (now - last >= 1000) { logf_("WaitForSingleObject: %d/sec, last timeout=%lu", n, lastms); n = 0; last = now; }
    return real_WaitForSingleObject ? real_WaitForSingleObject(h, ms) : 0;
}

static BOOL WINAPI hook_SleepConditionVariableSRW(PCONDITION_VARIABLE cv, PCRITICAL_SECTION cs, DWORD ms, ULONG flags)
{
    static DWORD last = 0; static int n = 0; static DWORD lastms = 0;
    DWORD now = GetTickCount(); ++n; lastms = ms;
    if (now - last >= 1000) { logf_("SleepConditionVariableSRW: %d/sec, last timeout=%lu ms", n, lastms); n = 0; last = now; }
    return real_SleepConditionVariableSRW ? real_SleepConditionVariableSRW(cv, cs, ms, flags) : 0;
}

static BOOL WINAPI hook_QueryPerformanceCounter(LARGE_INTEGER *pc)
{
    static DWORD last = 0; static int n = 0;
    DWORD now = GetTickCount(); ++n;
    if (now - last >= 1000) { logf_("QueryPerformanceCounter: %d calls/sec", n); n = 0; last = now; }
    return real_QueryPerformanceCounter ? real_QueryPerformanceCounter(pc) : 0;
}

/* winmm timer: DxLib may drive its frame signal with timeSetEvent */
static MMRESULT (WINAPI *real_timeSetEvent)(UINT, UINT, LPTIMECALLBACK, DWORD_PTR, UINT);
static MMRESULT WINAPI hook_timeSetEvent(UINT delay, UINT res, LPTIMECALLBACK cb, DWORD_PTR user, UINT mode)
{
    UINT d = delay;
    if (g_frame_scale != 1.0) { d = (UINT)(delay * g_frame_scale); if (d < 1) d = 1; }
    logf_("timeSetEvent(delay=%u -> %u, res=%u, mode=0x%x)", delay, d, res, mode);
    return real_timeSetEvent ? real_timeSetEvent(d, res, cb, user, mode) : 0;
}

/* ---------------- polling renamer ---------------- */
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
    logf_("renamer start");
    for (int i = 0; i < 240; ++i) {
        HWND h = find_our_window();
        if (h) {
            WCHAR cur[256] = {0};
            GetWindowTextW(h, cur, 255);
            if (wcscmp(cur, g_title) != 0) {
                SetWindowTextW(h, g_title);
                logf_("polling renamer set title (was \"%ls\")", cur);
            }
        }
        Sleep(250);
    }
    return 0;
}

/* ---------------- worker ---------------- */
static DWORD WINAPI mod_worker(LPVOID p)
{
    (void)p;
    logf_("worker start");
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
    patch_iat(main, "KERNEL32.dll", "SetWaitableTimerEx", (void *)hook_SetWaitableTimerEx, (void **)&real_SetWaitableTimerEx);
    patch_iat(main, "KERNEL32.dll", "CreateWaitableTimerExW", (void *)hook_CreateWaitableTimerExW, (void **)&real_CreateWaitableTimerExW);
    patch_iat(main, "KERNEL32.dll", "WaitForSingleObject", (void *)hook_WaitForSingleObject, (void **)&real_WaitForSingleObject);
    patch_iat(main, "KERNEL32.dll", "SleepConditionVariableSRW", (void *)hook_SleepConditionVariableSRW, (void **)&real_SleepConditionVariableSRW);
    patch_iat(main, "KERNEL32.dll", "QueryPerformanceCounter", (void *)hook_QueryPerformanceCounter, (void **)&real_QueryPerformanceCounter);

    for (int i = 0; i < 2; ++i) {
        Sleep(1000);
        IMAGE_THUNK_DATA64 *slot = find_iat_slot(main, "KERNEL32.dll", "GetProcAddress");
        if (slot && (void *)slot->u1.Function != (void *)hook_GetProcAddress) {
            logf_("re-asserting GetProcAddress hook (was %p)", (void *)slot->u1.Function);
            patch_iat(main, "KERNEL32.dll", "GetProcAddress", (void *)hook_GetProcAddress, NULL);
        }
    }
    logf_("hook stage done; title renamer running");
    return 0;
}

/* called from DllMain after any forwarder setup */
static void mod_start(HINSTANCE inst)
{
    DisableThreadLibraryCalls(inst);

    wchar_t exe[MAX_PATH] = {0};
    GetModuleFileNameW(NULL, exe, MAX_PATH);
    wchar_t *slash = wcsrchr(exe, L'\\');
    if (slash) slash[1] = 0;
    char narrow[MAX_PATH] = {0};
    WideCharToMultiByte(CP_ACP, 0, exe, -1, narrow, MAX_PATH, NULL, NULL);
    snprintf(g_log_path, MAX_PATH, "%s" MOD_LOGFILE, narrow);

    mod_load_config();
    mod_patch_frame_rate();
    logf_("=== proxy loaded into pid %lu ===", GetCurrentProcessId());
    HANDLE t = CreateThread(NULL, 0, mod_worker, NULL, 0, NULL);
    logf_("worker thread handle=%p err=%lu", (void *)t, t ? 0UL : GetLastError());
    if (t) CloseHandle(t);
    t = CreateThread(NULL, 0, title_thread, NULL, 0, NULL);
    if (t) CloseHandle(t);
}
