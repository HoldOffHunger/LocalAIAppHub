// ClaudiaMini.exe, the Minis: Claudia, floating on top of everything, showing what Claude Code is doing, and Bit beside
// her, showing what the AI Workers are doing.
//
// Four jobs in one small process:
//   - the windows: borderless, always on top, per-pixel alpha, drawn with UpdateLayeredWindow
//   - the ear: a UDP socket on 127.0.0.1:8781 that claudia-signal.exe reports hook events to
//   - Bit's eyes: every two seconds, the hub's GPU desk and Ollama's loaded models
//   - the control page: a tiny HTTP server on 127.0.0.1:8780, which is also the Minis' AppHub pane
//
// Every Claude Code session has its own state; she shows whichever matters most right now.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <wincodec.h>
#include <mmsystem.h>
#include <shellapi.h>
#include <winhttp.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <deque>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

static const unsigned short HTTP_PORT = 8780;
static const unsigned short SIGNAL_PORT = 8781;
static const UINT WM_APP_EVENT = WM_APP + 1;    // lParam: std::string* "event\tsession"
static const UINT WM_APP_COMMAND = WM_APP + 2;  // lParam: std::string* from the control page
static const UINT_PTR TIMER_TICK = 1;
static const int TICK_MS = 50;

// ---------------------------------------------------------------- settings

struct Settings {
    int scale = 3;               // each sprite pixel drawn as scale x scale screen pixels
    bool sound = true;           // one chime on entering NeedsYou, Stuck or OutOfMana
    bool click_through = false;  // clicks pass straight through her to whatever is underneath
    int x = -1, y = -1;          // window position; -1 means bottom-right of the main screen
    int done_seconds = 90;       // Done relaxes into Idle after this long
    int asleep_minutes = 30;     // Idle dozes off into Asleep after this long
    int oops_failures = 3;       // this many failed tools...
    int oops_window_seconds = 120;  // ...within this window shows Oops
    int oops_seconds = 20;       // and Oops lasts this long
    int bit_size = 96;           // Bit's width on screen, in pixels
    int bit_x = -1, bit_y = -1;  // his window position; -1 means just left of Claudia's default spot
    bool bit_shown = true;
};

static std::wstring g_home;  // the folder ClaudiaMini.exe lives in
static Settings g_settings;

static std::string read_file(const std::wstring& path)
{
    std::ifstream in(path, std::ios::binary);
    std::stringstream text;
    text << in.rdbuf();
    return text.str();
}

static bool json_number(const std::string& json, const char* key, int& out)
{
    std::string pattern = std::string("\"") + key + "\"";
    size_t at = json.find(pattern);
    if (at == std::string::npos)
        return false;
    at = json.find(':', at);
    if (at == std::string::npos)
        return false;
    at = json.find_first_not_of(" \t\r\n", at + 1);
    if (at == std::string::npos)
        return false;
    if (json.compare(at, 4, "true") == 0) { out = 1; return true; }
    if (json.compare(at, 5, "false") == 0) { out = 0; return true; }
    try { out = std::stoi(json.substr(at)); } catch (...) { return false; }
    return true;
}

static void load_settings()
{
    std::string json = read_file(g_home + L"\\data\\settings.json");
    int v;
    if (json_number(json, "scale", v)) g_settings.scale = std::clamp(v, 1, 8);
    if (json_number(json, "sound", v)) g_settings.sound = v != 0;
    if (json_number(json, "click_through", v)) g_settings.click_through = v != 0;
    if (json_number(json, "x", v)) g_settings.x = v;
    if (json_number(json, "y", v)) g_settings.y = v;
    if (json_number(json, "done_seconds", v)) g_settings.done_seconds = v;
    if (json_number(json, "asleep_minutes", v)) g_settings.asleep_minutes = v;
    if (json_number(json, "oops_failures", v)) g_settings.oops_failures = std::max(1, v);
    if (json_number(json, "oops_window_seconds", v)) g_settings.oops_window_seconds = v;
    if (json_number(json, "oops_seconds", v)) g_settings.oops_seconds = v;
    if (json_number(json, "bit_size", v)) g_settings.bit_size = std::clamp(v, 48, 256);
    if (json_number(json, "bit_x", v)) g_settings.bit_x = v;
    if (json_number(json, "bit_y", v)) g_settings.bit_y = v;
    if (json_number(json, "bit_shown", v)) g_settings.bit_shown = v != 0;
}

static void save_settings()
{
    const Settings& s = g_settings;
    char text[1024];
    std::snprintf(text, sizeof text,
        "{\n  \"scale\": %d,\n  \"sound\": %s,\n  \"click_through\": %s,\n  \"x\": %d,\n  \"y\": %d,\n"
        "  \"done_seconds\": %d,\n  \"asleep_minutes\": %d,\n  \"oops_failures\": %d,\n"
        "  \"oops_window_seconds\": %d,\n  \"oops_seconds\": %d,\n"
        "  \"bit_size\": %d,\n  \"bit_x\": %d,\n  \"bit_y\": %d,\n  \"bit_shown\": %s\n}\n",
        s.scale, s.sound ? "true" : "false", s.click_through ? "true" : "false", s.x, s.y,
        s.done_seconds, s.asleep_minutes, s.oops_failures, s.oops_window_seconds, s.oops_seconds,
        s.bit_size, s.bit_x, s.bit_y, s.bit_shown ? "true" : "false");
    std::ofstream out(g_home + L"\\data\\settings.json", std::ios::binary | std::ios::trunc);
    out << text;
}

// ---------------------------------------------------------------- sprites

struct Frame {
    int w = 0, h = 0;
    std::vector<uint32_t> pixels;  // premultiplied BGRA, top-down
};

static std::map<std::string, std::vector<Frame>> g_art;  // art name -> poses
static int g_frame_w = 1, g_frame_h = 1;

static bool load_png(IWICImagingFactory* wic, const std::wstring& path, Frame& frame)
{
    IWICBitmapDecoder* decoder = nullptr;
    IWICBitmapFrameDecode* source = nullptr;
    IWICBitmapSource* converted = nullptr;
    bool ok = false;
    if (SUCCEEDED(wic->CreateDecoderFromFilename(path.c_str(), nullptr, GENERIC_READ,
                                                 WICDecodeMetadataCacheOnDemand, &decoder)) &&
        SUCCEEDED(decoder->GetFrame(0, &source)) &&
        SUCCEEDED(WICConvertBitmapSource(GUID_WICPixelFormat32bppPBGRA, source, &converted))) {
        UINT w = 0, h = 0;
        converted->GetSize(&w, &h);
        frame.w = (int)w;
        frame.h = (int)h;
        frame.pixels.resize((size_t)w * h);
        ok = SUCCEEDED(converted->CopyPixels(nullptr, w * 4, (UINT)(frame.pixels.size() * 4),
                                             (BYTE*)frame.pixels.data()));
    }
    if (converted) converted->Release();
    if (source) source->Release();
    if (decoder) decoder->Release();
    return ok;
}

static void load_art()
{
    IWICImagingFactory* wic = nullptr;
    if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&wic))))
        return;
    std::wstring root = g_home + L"\\art\\sprites\\";
    WIN32_FIND_DATAW folder;
    HANDLE folders = FindFirstFileW((root + L"*").c_str(), &folder);
    if (folders != INVALID_HANDLE_VALUE) {
        do {
            if (!(folder.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || folder.cFileName[0] == L'.')
                continue;
            std::wstring name_w = folder.cFileName;
            std::string name(name_w.begin(), name_w.end());
            std::vector<std::wstring> files;
            WIN32_FIND_DATAW file;
            HANDLE found = FindFirstFileW((root + name_w + L"\\*.png").c_str(), &file);
            if (found != INVALID_HANDLE_VALUE) {
                do files.push_back(file.cFileName); while (FindNextFileW(found, &file));
                FindClose(found);
            }
            std::sort(files.begin(), files.end());
            for (const std::wstring& f : files) {
                Frame frame;
                if (load_png(wic, root + name_w + L"\\" + f, frame)) {
                    g_frame_w = std::max(g_frame_w, frame.w);
                    g_frame_h = std::max(g_frame_h, frame.h);
                    g_art[name].push_back(std::move(frame));
                }
            }
        } while (FindNextFileW(folders, &folder));
        FindClose(folders);
    }
    wic->Release();
}

// ---------------------------------------------------------------- what Claude Code is doing

// Display states, most important first; with several sessions open the most important wins
static const char* STATES[] = {"needsyou", "stuck", "outofmana", "oops", "working", "done", "idle", "asleep"};

static int priority(const std::string& state)
{
    for (int i = 0; i < (int)(sizeof STATES / sizeof *STATES); i++)
        if (state == STATES[i]) return i;
    return 99;
}

// Which pose folder each state wears. Stuck borrows NeedsYou's wave, OutOfMana naps
static std::string art_for(const std::string& state)
{
    if (state == "stuck") return "needsyou";
    if (state == "outofmana") return "asleep";
    return state;
}

struct Session {
    std::string state = "idle";
    ULONGLONG since = 0;       // when it entered state
    ULONGLONG last_event = 0;
    std::deque<ULONGLONG> failures;
    ULONGLONG oops_until = 0;
};

static std::map<std::string, Session> g_sessions;
static std::string g_last_session;  // the most recently heard-from session, for Claude's own oops
static std::string g_forced;        // a pose the control page asked to preview
static ULONGLONG g_forced_until = 0;

static void set_state(Session& s, const char* state, ULONGLONG now)
{
    if (s.state != state) {
        s.state = state;
        s.since = now;
    }
}

static void handle_event(const std::string& event, std::string id, ULONGLONG now)
{
    if (id.empty()) {
        // Claude's own oops report carries no session; it belongs to whoever spoke last
        if (g_last_session.empty() || !g_sessions.count(g_last_session)) return;
        id = g_last_session;
    }
    if (event == "sessionend") {
        g_sessions.erase(id);
        return;
    }
    Session& s = g_sessions[id];
    if (s.since == 0) s.since = now;
    s.last_event = now;
    g_last_session = id;

    if (event == "sessionstart") {
        set_state(s, "idle", now);
    } else if (event == "prompt" || event == "pretool" || event == "posttool") {
        set_state(s, "working", now);
    } else if (event == "toolfail" || event == "denied") {
        set_state(s, "working", now);
        s.failures.push_back(now);
        while (!s.failures.empty() && now - s.failures.front() > (ULONGLONG)g_settings.oops_window_seconds * 1000)
            s.failures.pop_front();
        if ((int)s.failures.size() >= g_settings.oops_failures) {
            s.oops_until = now + (ULONGLONG)g_settings.oops_seconds * 1000;
            s.failures.clear();
        }
    } else if (event == "oops") {
        s.oops_until = now + (ULONGLONG)g_settings.oops_seconds * 1000;
    } else if (event == "needsyou" || event == "permission") {
        set_state(s, "needsyou", now);
    } else if (event == "idle") {
        // Claude Code's "still waiting for you" nudge; it never overrides a real request
        if (s.state == "working" || s.state == "done") set_state(s, "idle", now);
    } else if (event == "stop") {
        set_state(s, "done", now);
    } else if (event == "stuck") {
        set_state(s, "stuck", now);
    } else if (event == "outofmana") {
        set_state(s, "outofmana", now);
    }
}

// Time passing: Done relaxes, Idle dozes, and sessions that went silent are let go
static void age_sessions(ULONGLONG now)
{
    for (auto it = g_sessions.begin(); it != g_sessions.end();) {
        Session& s = it->second;
        ULONGLONG in_state = now - s.since, silent = now - s.last_event;
        if (silent > 12ull * 3600 * 1000) {  // closed without saying goodbye
            it = g_sessions.erase(it);
            continue;
        }
        if (s.state == "done" && in_state > (ULONGLONG)g_settings.done_seconds * 1000)
            set_state(s, "idle", now);
        else if (s.state == "working" && silent > 30ull * 60 * 1000)  // a crash mid-turn
            set_state(s, "idle", now);
        else if (s.state == "idle" && in_state > (ULONGLONG)g_settings.asleep_minutes * 60 * 1000)
            set_state(s, "asleep", now);
        ++it;
    }
}

static std::string shown_state(const Session& s, ULONGLONG now)
{
    bool urgent = s.state == "needsyou" || s.state == "stuck" || s.state == "outofmana";
    if (!urgent && s.oops_until > now) return "oops";
    return s.state;
}

static std::string display_state(ULONGLONG now, std::string* why = nullptr)
{
    if (!g_forced.empty() && now < g_forced_until) {
        if (why) *why = "preview";
        return g_forced;
    }
    std::string best = "asleep";
    if (why) *why = "";
    for (const auto& [id, s] : g_sessions) {
        std::string state = shown_state(s, now);
        if (priority(state) < priority(best) || (why && why->empty() && state == best)) {
            best = state;
            if (why) *why = id;
        }
    }
    return best;
}

// ---------------------------------------------------------------- drawing

struct Motion {
    double bob_pixels;    // how far she bobs, in sprite pixels
    double bob_seconds;   // one full bob
    double pose_seconds;  // how long before the next pose in the folder
};

static Motion motion_for(const std::string& state)
{
    if (state == "needsyou" || state == "stuck") return {3, 0.7, 2.0};
    if (state == "working") return {2, 0.9, 3.0};
    if (state == "done") return {2, 1.0, 3.0};
    if (state == "oops") return {1, 2.0, 4.0};
    if (state == "asleep" || state == "outofmana") return {1, 4.0, 8.0};
    return {1, 3.0, 6.0};  // idle
}

static const int BOB_ROOM = 4;  // spare sprite pixels above her, so a bob never clips her head

static HWND g_window;
static std::string g_shown;       // display state currently drawn
static std::string g_art_name;    // pose folder in use
static size_t g_pose = 0;
static ULONGLONG g_pose_since = 0, g_state_since = 0;
static int g_drawn_pose = -1, g_drawn_bob = -1, g_drawn_scale = -1;
static std::string g_drawn_art;

static const std::vector<Frame>* poses_for(const std::string& art)
{
    auto it = g_art.find(art);
    if (it != g_art.end() && !it->second.empty()) return &it->second;
    // No sleeping poses yet: she reads instead
    if (art == "asleep") {
        it = g_art.find("idle");
        if (it != g_art.end() && !it->second.empty()) return &it->second;
    }
    for (auto& [name, frames] : g_art)
        if (!frames.empty()) return &frames;
    return nullptr;
}

static void draw(int bob)
{
    const std::vector<Frame>* poses = poses_for(g_art_name);
    if (!poses) return;
    const Frame& f = (*poses)[g_pose % poses->size()];
    const int k = g_settings.scale;
    const int W = g_frame_w * k, H = (g_frame_h + BOB_ROOM) * k;

    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = W;
    bi.bmiHeader.biHeight = -H;  // top-down
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    void* bits = nullptr;
    HDC screen = GetDC(nullptr);
    HDC dc = CreateCompatibleDC(screen);
    HBITMAP bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ old = SelectObject(dc, bmp);
    uint32_t* out = (uint32_t*)bits;
    std::fill(out, out + (size_t)W * H, 0u);

    // Stand her on the bottom edge, centred, lifted by the bob; whole sprite pixels keep the grid crisp
    int ox = (g_frame_w - f.w) / 2, oy = BOB_ROOM + (g_frame_h - f.h) - bob;
    for (int y = 0; y < f.h; y++) {
        for (int x = 0; x < f.w; x++) {
            uint32_t p = f.pixels[(size_t)y * f.w + x];
            if (!(p >> 24)) continue;
            int sy = (oy + y) * k, sx = (ox + x) * k;
            for (int dy = 0; dy < k; dy++) {
                uint32_t* row = out + (size_t)(sy + dy) * W + sx;
                for (int dx = 0; dx < k; dx++) row[dx] = p;
            }
        }
    }

    RECT r;
    GetWindowRect(g_window, &r);
    POINT at = {r.left, r.top}, zero = {0, 0};
    SIZE size = {W, H};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    UpdateLayeredWindow(g_window, screen, &at, &size, dc, &zero, 0, &blend, ULW_ALPHA);

    SelectObject(dc, old);
    DeleteObject(bmp);
    DeleteDC(dc);
    ReleaseDC(nullptr, screen);
}

static void place_window()
{
    const int W = g_frame_w * g_settings.scale, H = (g_frame_h + BOB_ROOM) * g_settings.scale;
    int x = g_settings.x, y = g_settings.y;
    RECT work;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    if (x == -1 && y == -1) {
        x = work.right - W - 24;
        y = work.bottom - H;
    }
    // Back onto a screen if a monitor she was on has gone
    RECT want = {x, y, x + W, y + H};
    if (!MonitorFromRect(&want, MONITOR_DEFAULTTONULL)) {
        x = work.right - W - 24;
        y = work.bottom - H;
    }
    SetWindowPos(g_window, HWND_TOPMOST, x, y, W, H, SWP_NOACTIVATE);
    g_drawn_scale = -1;
}

static void apply_click_through()
{
    LONG_PTR ex = GetWindowLongPtrW(g_window, GWL_EXSTYLE);
    ex = g_settings.click_through ? (ex | WS_EX_TRANSPARENT) : (ex & ~WS_EX_TRANSPARENT);
    SetWindowLongPtrW(g_window, GWL_EXSTYLE, ex);
}

static void chime()
{
    if (!g_settings.sound) return;
    std::wstring wav = g_home + L"\\data\\chime.wav";
    if (GetFileAttributesW(wav.c_str()) != INVALID_FILE_ATTRIBUTES)
        PlaySoundW(wav.c_str(), nullptr, SND_FILENAME | SND_ASYNC | SND_NODEFAULT);
    else
        PlaySoundW(L"SystemNotification", nullptr, SND_ALIAS | SND_ASYNC);
}

// ---------------------------------------------------------------- Bit
//
// Bit keeps an eye on the AI Workers. Undecided, his calm many-faceted shape, while nothing is loaded on the card; No,
// the red spiky star, while a model sits loaded but nobody is working; Yes, the yellow octahedron, while a worker's turn
// holds the card at the hub's GPU desk. He's drawn fresh every frame as flat-shaded polyhedra with glowing edges, so he
// stays sharp at any size and needs no sprites.

struct Vec3 { double x, y, z; };
static Vec3 operator+(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
static Vec3 operator-(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
static Vec3 operator*(Vec3 a, double k) { return {a.x * k, a.y * k, a.z * k}; }
static double dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static Vec3 cross(Vec3 a, Vec3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
static Vec3 unit(Vec3 a) { double n = std::sqrt(dot(a, a)); return n > 0 ? a * (1 / n) : a; }

struct Tri { Vec3 a, b, c; };
using Shape = std::vector<Tri>;

static void add_outward(Shape& shape, Vec3 a, Vec3 b, Vec3 c)
{
    // Every face wound to face away from his middle, so the back faces can be skipped
    if (dot(cross(b - a, c - a), a + b + c) < 0) std::swap(b, c);
    shape.push_back({a, b, c});
}

static std::vector<Vec3> icosahedron_points()
{
    const double p = (1 + std::sqrt(5.0)) / 2;
    std::vector<Vec3> v = {{-1, p, 0}, {1, p, 0}, {-1, -p, 0}, {1, -p, 0}, {0, -1, p}, {0, 1, p},
                           {0, -1, -p}, {0, 1, -p}, {p, 0, -1}, {p, 0, 1}, {-p, 0, -1}, {-p, 0, 1}};
    for (Vec3& point : v) point = unit(point);
    return v;
}

static const int ICOSAHEDRON_FACES[20][3] = {{0, 11, 5}, {0, 5, 1}, {0, 1, 7}, {0, 7, 10}, {0, 10, 11}, {1, 5, 9},
    {5, 11, 4}, {11, 10, 2}, {10, 7, 6}, {7, 1, 8}, {3, 9, 4}, {3, 4, 2}, {3, 2, 6}, {3, 6, 8}, {3, 8, 9}, {4, 9, 5},
    {2, 4, 11}, {6, 2, 10}, {8, 6, 7}, {9, 8, 1}};

static Shape g_bit_calm, g_bit_no, g_bit_yes;

static void build_bit_shapes()
{
    std::vector<Vec3> v = icosahedron_points();
    for (const auto& f : ICOSAHEDRON_FACES) {
        add_outward(g_bit_calm, v[f[0]], v[f[1]], v[f[2]]);
        // No: every face raised into a spike
        Vec3 a = v[f[0]] * 0.6, b = v[f[1]] * 0.6, c = v[f[2]] * 0.6, tip = unit(a + b + c) * 1.12;
        add_outward(g_bit_no, a, b, tip);
        add_outward(g_bit_no, b, c, tip);
        add_outward(g_bit_no, c, a, tip);
    }
    Vec3 o[6] = {{1.05, 0, 0}, {-1.05, 0, 0}, {0, 1.05, 0}, {0, -1.05, 0}, {0, 0, 1.05}, {0, 0, -1.05}};
    for (int x : {0, 1})
        for (int y : {2, 3})
            for (int z : {4, 5}) add_outward(g_bit_yes, o[x], o[y], o[z]);
}

struct BitLook {
    const Shape* shape;
    double r, g, b;  // his colour, 0..1
    double spin;     // turns, in radians a second
    double bob;      // how far he floats up and down, as a share of his size
    double bob_rate; // radians a second
};

static BitLook look_for(const std::string& state)
{
    if (state == "yes") return {&g_bit_yes, 1.00, 0.80, 0.16, 1.6, 0.06, 5.0};
    if (state == "no") return {&g_bit_no, 1.00, 0.17, 0.10, 2.4, 0.02, 2.0};
    return {&g_bit_calm, 0.52, 0.84, 1.00, 0.6, 0.03, 1.4};
}

static HWND g_bit_window;
static std::mutex g_bit_lock;
static std::string g_bit_heard = "undecided", g_bit_heard_why = "Not asked yet";  // from the watching thread
static std::string g_bit_state, g_bit_from, g_bit_why;  // what he shows, the shape he's leaving, and why
static std::string g_bit_forced;
static ULONGLONG g_bit_forced_until = 0, g_bit_changed = 0;

static int bit_canvas() { return g_settings.bit_size * 3 / 2; }  // room around him for the glow and the float

static void draw_bit(ULONGLONG now)
{
    const int S = g_settings.bit_size, W = bit_canvas(), K = 2, RW = W * K;  // drawn at twice the size, then averaged
    std::string state = g_bit_state;
    double grow = 1;
    ULONGLONG since = now - g_bit_changed;
    // Changing his mind: the old shape shrinks away, and the new one pops out with a little overshoot
    if (since < 150 && !g_bit_from.empty()) {
        state = g_bit_from;
        grow = 1 - since / 150.0;
    } else if (since < 450) {
        double u = (since - 150) / 300.0;
        grow = 1 - std::pow(1 - u, 3) + 0.22 * std::sin(3.14159265 * u);
    }
    BitLook look = look_for(state);
    double t = now / 1000.0;
    double yaw = t * look.spin, pitch = 0.45 + 0.12 * std::sin(t * 0.7);
    double radius = S * 0.5 * K * std::max(grow, 0.0);
    double cx = RW / 2.0, cy = RW / 2.0 - look.bob * S * K * std::sin(t * look.bob_rate);
    if (state == "no" && std::sin(t * 1.3) > 0.7) cx += 0.035 * S * K * std::sin(t * 38);  // shakes his head now and then

    auto turn = [&](Vec3 p) {
        Vec3 q = {p.x * std::cos(yaw) + p.z * std::sin(yaw), p.y, -p.x * std::sin(yaw) + p.z * std::cos(yaw)};
        return Vec3{q.x, q.y * std::cos(pitch) - q.z * std::sin(pitch), q.y * std::sin(pitch) + q.z * std::cos(pitch)};
    };
    struct Face { Vec3 a, b, c; double depth, light; };
    std::vector<Face> faces;
    const Vec3 sun = unit({-0.35, 0.55, 0.75});
    for (const Tri& tri : *look.shape) {
        Vec3 a = turn(tri.a), b = turn(tri.b), c = turn(tri.c), n = unit(cross(b - a, c - a));
        if (n.z <= 0) continue;  // facing away
        double rim = 1 - n.z;
        faces.push_back({a, b, c, (a.z + b.z + c.z) / 3, 0.22 + 0.62 * std::max(0.0, dot(n, sun)) + 0.4 * rim * rim});
    }
    std::sort(faces.begin(), faces.end(), [](const Face& x, const Face& y) { return x.depth < y.depth; });

    std::vector<float> rgb((size_t)RW * RW * 3, 0.f), cover((size_t)RW * RW, 0.f);
    for (const Face& f : faces) {
        double ax = cx + f.a.x * radius, ay = cy - f.a.y * radius, bx = cx + f.b.x * radius, by = cy - f.b.y * radius,
               qx = cx + f.c.x * radius, qy = cy - f.c.y * radius;
        double area = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax);
        if (std::fabs(area) < 1e-6) continue;
        double sign = area > 0 ? 1 : -1;
        double la = std::hypot(qx - bx, qy - by), lb = std::hypot(ax - qx, ay - qy), lc = std::hypot(bx - ax, by - ay);
        int x0 = std::max(0, (int)std::floor(std::min({ax, bx, qx}))), x1 = std::min(RW - 1, (int)std::ceil(std::max({ax, bx, qx})));
        int y0 = std::max(0, (int)std::floor(std::min({ay, by, qy}))), y1 = std::min(RW - 1, (int)std::ceil(std::max({ay, by, qy})));
        for (int y = y0; y <= y1; y++) {
            for (int x = x0; x <= x1; x++) {
                double px = x + 0.5, py = y + 0.5;
                double w0 = sign * ((qx - bx) * (py - by) - (qy - by) * (px - bx));
                double w1 = sign * ((ax - qx) * (py - qy) - (ay - qy) * (px - qx));
                double w2 = sign * ((bx - ax) * (py - ay) - (by - ay) * (px - ax));
                if (w0 < 0 || w1 < 0 || w2 < 0) continue;
                // Near an edge the face lights up toward white: the neon outline
                double edge = std::min({w0 / la, w1 / lb, w2 / lc});
                double e = std::clamp(1 - edge / (1.7 * K), 0.0, 1.0);
                double l = f.light;
                size_t i = (size_t)y * RW + x;
                rgb[i * 3 + 0] = (float)(look.r * l * (1 - e) + (0.45 * look.r + 0.55) * e);
                rgb[i * 3 + 1] = (float)(look.g * l * (1 - e) + (0.45 * look.g + 0.55) * e);
                rgb[i * 3 + 2] = (float)(look.b * l * (1 - e) + (0.45 * look.b + 0.55) * e);
                cover[i] = 1.f;
            }
        }
    }

    // Down to screen size, then a soft glow of his colour around him: his outline, blurred
    std::vector<float> col((size_t)W * W * 3), alpha((size_t)W * W), glow((size_t)W * W);
    for (int y = 0; y < W; y++)
        for (int x = 0; x < W; x++) {
            float c[3] = {0, 0, 0}, a = 0;
            for (int dy = 0; dy < K; dy++)
                for (int dx = 0; dx < K; dx++) {
                    size_t i = (size_t)(y * K + dy) * RW + (x * K + dx);
                    for (int k = 0; k < 3; k++) c[k] += rgb[i * 3 + k];
                    a += cover[i];
                }
            size_t o = (size_t)y * W + x;
            for (int k = 0; k < 3; k++) col[o * 3 + k] = c[k] / (K * K);  // already premultiplied by coverage
            alpha[o] = glow[o] = a / (K * K);
        }
    const int reach = std::max(2, S / 9);
    std::vector<float> pass((size_t)W * W);
    for (int round = 0; round < 3; round++) {
        for (int y = 0; y < W; y++)
            for (int x = 0; x < W; x++) {
                float sum = 0;
                for (int d = -reach; d <= reach; d++) sum += glow[(size_t)y * W + std::clamp(x + d, 0, W - 1)];
                pass[(size_t)y * W + x] = sum / (2 * reach + 1);
            }
        for (int y = 0; y < W; y++)
            for (int x = 0; x < W; x++) {
                float sum = 0;
                for (int d = -reach; d <= reach; d++) sum += pass[(size_t)std::clamp(y + d, 0, W - 1) * W + x];
                glow[(size_t)y * W + x] = sum / (2 * reach + 1);
            }
    }
    double pulse = state == "yes" ? 0.85 + 0.15 * std::sin(t * 4) : 1.0;

    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = W;
    bi.bmiHeader.biHeight = -W;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    void* bits = nullptr;
    HDC screen = GetDC(nullptr);
    HDC dc = CreateCompatibleDC(screen);
    HBITMAP bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ old = SelectObject(dc, bmp);
    uint32_t* out = (uint32_t*)bits;
    for (size_t i = 0; i < (size_t)W * W; i++) {
        double sa = alpha[i], ga = std::min(1.0, glow[i] * 1.4) * 0.7 * pulse * (1 - sa);
        double r = col[i * 3 + 0] + look.r * ga, g = col[i * 3 + 1] + look.g * ga, b = col[i * 3 + 2] + look.b * ga, a = sa + ga;
        auto byte = [](double v) { return (uint32_t)std::lround(std::clamp(v, 0.0, 1.0) * 255); };
        uint32_t A = byte(a);
        out[i] = (A << 24) | (std::min(byte(r), A) << 16) | (std::min(byte(g), A) << 8) | std::min(byte(b), A);
    }
    RECT rect;
    GetWindowRect(g_bit_window, &rect);
    POINT at = {rect.left, rect.top}, zero = {0, 0};
    SIZE size = {W, W};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    UpdateLayeredWindow(g_bit_window, screen, &at, &size, dc, &zero, 0, &blend, ULW_ALPHA);
    SelectObject(dc, old);
    DeleteObject(bmp);
    DeleteDC(dc);
    ReleaseDC(nullptr, screen);
}

static void place_bit()
{
    const int W = bit_canvas();
    int x = g_settings.bit_x, y = g_settings.bit_y;
    RECT work;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    const int beside = work.right - g_frame_w * g_settings.scale - 24 - W;  // just left of where Claudia starts
    RECT want = {x, y, x + W, y + W};
    if ((x == -1 && y == -1) || !MonitorFromRect(&want, MONITOR_DEFAULTTONULL)) {
        x = beside;
        y = work.bottom - W;
    }
    SetWindowPos(g_bit_window, HWND_TOPMOST, x, y, W, W, SWP_NOACTIVATE);
}

static std::string http_get(INTERNET_PORT port, const wchar_t* path)
{
    // A quick local GET; anything that doesn't answer in a couple of seconds counts as nothing said
    std::string body;
    HINTERNET session = WinHttpOpen(L"Minis", WINHTTP_ACCESS_TYPE_NO_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) return body;
    WinHttpSetTimeouts(session, 1500, 1500, 2000, 2000);
    HINTERNET connection = WinHttpConnect(session, L"127.0.0.1", port, 0);
    HINTERNET request = connection ? WinHttpOpenRequest(connection, L"GET", path, nullptr, WINHTTP_NO_REFERER,
                                                        WINHTTP_DEFAULT_ACCEPT_TYPES, 0) : nullptr;
    if (request && WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
        WinHttpReceiveResponse(request, nullptr)) {
        char buffer[4096];
        DWORD got = 0;
        while (WinHttpReadData(request, buffer, sizeof buffer, &got) && got) body.append(buffer, got);
    }
    if (request) WinHttpCloseHandle(request);
    if (connection) WinHttpCloseHandle(connection);
    WinHttpCloseHandle(session);
    return body;
}

static void watch_the_card()
{
    // The Foreman says whether a worker is running, hand-started or the night shift's; the hub's desk says whether a
    // worker's turn holds the card, for a Foreman too old to answer; Ollama says which models are sitting on the card
    for (;;) {
        std::string desk = http_get(8700, L"/api/gpu"), loaded = http_get(11434, L"/api/ps");
        bool running = http_get(8720, L"/api/busy").find("\"running\":true") != std::string::npos;
        std::string models;
        for (size_t at = loaded.find("\"name\""); at != std::string::npos; at = loaded.find("\"name\"", at + 6)) {
            size_t open = loaded.find('"', loaded.find(':', at) + 1), close = loaded.find('"', open + 1);
            if (open == std::string::npos || close == std::string::npos) break;
            models += (models.empty() ? "" : ", ") + loaded.substr(open + 1, close - open - 1);
        }
        std::string state, why;
        if (running || desk.find("\"workers\"") != std::string::npos) {
            state = "yes";
            why = "A worker is working" + (models.empty() ? std::string() : ": " + models);
        } else if (!models.empty()) {
            state = "no";
            why = "Loaded, nobody working: " + models;
        } else {
            state = "undecided";
            why = loaded.empty() ? "Nothing loaded (Ollama isn't answering)" : "Nothing loaded on the card";
        }
        {
            std::lock_guard<std::mutex> hold(g_bit_lock);
            g_bit_heard = state;
            g_bit_heard_why = why;
        }
        Sleep(2000);
    }
}

static void tick_bit(ULONGLONG now)
{
    std::string state, why;
    if (!g_bit_forced.empty() && now < g_bit_forced_until) {
        state = g_bit_forced;
        why = "Previewing";
    } else {
        std::lock_guard<std::mutex> hold(g_bit_lock);
        state = g_bit_heard;
        why = g_bit_heard_why;
    }
    g_bit_why = why;
    if (state != g_bit_state) {
        g_bit_from = g_bit_state;
        g_bit_state = state;
        g_bit_changed = now;
    }
    if (g_settings.bit_shown) draw_bit(now);
}

// ---------------------------------------------------------------- the control page's view of her

static std::mutex g_snapshot_lock;
static std::string g_snapshot = "{}";

static std::string json_escape(const std::string& text)
{
    std::string out;
    for (char c : text) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if ((unsigned char)c < 0x20) out += ' ';
        else out += c;
    }
    return out;
}

static void update_snapshot(ULONGLONG now, const std::string& why)
{
    std::ostringstream j;
    j << "{\"state\":\"" << g_shown << "\",\"art\":\"" << g_art_name << "\",\"pose\":" << (g_pose + 1)
      << ",\"because\":\"" << json_escape(why) << "\",\"scale\":" << g_settings.scale
      << ",\"sound\":" << (g_settings.sound ? "true" : "false")
      << ",\"click_through\":" << (g_settings.click_through ? "true" : "false") << ",\"sessions\":[";
    bool first = true;
    for (const auto& [id, s] : g_sessions) {
        j << (first ? "" : ",") << "{\"id\":\"" << json_escape(id) << "\",\"state\":\"" << shown_state(s, now)
          << "\",\"seconds\":" << (now - s.since) / 1000 << ",\"silent\":" << (now - s.last_event) / 1000 << "}";
        first = false;
    }
    j << "],\"bit\":{\"state\":\"" << g_bit_state << "\",\"why\":\"" << json_escape(g_bit_why) << "\",\"size\":"
      << g_settings.bit_size << ",\"shown\":" << (g_settings.bit_shown ? "true" : "false") << "}";
    j << ",\"art_counts\":{";
    first = true;
    for (const auto& [name, frames] : g_art) {
        j << (first ? "" : ",") << "\"" << name << "\":" << frames.size();
        first = false;
    }
    j << "}}";
    std::lock_guard<std::mutex> hold(g_snapshot_lock);
    g_snapshot = j.str();
}

// ---------------------------------------------------------------- the tick

static void tick()
{
    ULONGLONG now = GetTickCount64();
    age_sessions(now);
    std::string why;
    std::string state = display_state(now, &why);
    if (state != g_shown) {
        bool urgent = state == "needsyou" || state == "stuck" || state == "outofmana";
        if (urgent && why != "preview") chime();
        g_shown = state;
        g_state_since = now;
        std::string art = art_for(state);
        if (art != g_art_name) {
            g_art_name = art;
            const std::vector<Frame>* poses = poses_for(art);
            g_pose = poses ? (size_t)(now / 7) % poses->size() : 0;  // start somewhere different each time
            g_pose_since = now;
        }
    }
    Motion m = motion_for(state);
    const std::vector<Frame>* poses = poses_for(g_art_name);
    if (poses && poses->size() > 1 && now - g_pose_since > (ULONGLONG)(m.pose_seconds * 1000)) {
        g_pose = (g_pose + 1) % poses->size();
        g_pose_since = now;
    }
    // A soft bounce: |sin| reads as a hop for the lively states and a breath for the quiet ones
    double t = (now - g_state_since) / 1000.0;
    int bob = (int)std::lround(m.bob_pixels * std::fabs(std::sin(3.14159265 * t / m.bob_seconds)));
    bob = std::min(bob, BOB_ROOM);
    if ((int)g_pose != g_drawn_pose || bob != g_drawn_bob || g_art_name != g_drawn_art ||
        g_settings.scale != g_drawn_scale) {
        draw(bob);
        g_drawn_pose = (int)g_pose;
        g_drawn_bob = bob;
        g_drawn_art = g_art_name;
        g_drawn_scale = g_settings.scale;
    }
    tick_bit(now);
    static ULONGLONG last_snapshot = 0, last_topmost = 0;
    if (now - last_snapshot > 250) {
        update_snapshot(now, why);
        last_snapshot = now;
    }
    // Some fullscreen apps push themselves above other topmost windows; quietly climb back up
    if (now - last_topmost > 5000) {
        SetWindowPos(g_window, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        SetWindowPos(g_bit_window, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        last_topmost = now;
    }
}

// ---------------------------------------------------------------- commands (menu and control page)

static void run_command(const std::string& command)
{
    // "scale=3", "sound=0", "click_through=1", "preview=working", "preview=", "bit_size=96", "bit_shown=0",
    // "bit_preview=yes", "quit"
    size_t eq = command.find('=');
    std::string key = command.substr(0, eq), value = eq == std::string::npos ? "" : command.substr(eq + 1);
    if (key == "scale") {
        int v = std::atoi(value.c_str());
        if (v >= 1 && v <= 8) {
            g_settings.scale = v;
            RECT r;
            GetWindowRect(g_window, &r);
            // Keep her feet where they were when she changes size
            int H = (g_frame_h + BOB_ROOM) * v, W = g_frame_w * v;
            g_settings.x = r.left + ((r.right - r.left) - W) / 2;
            g_settings.y = r.bottom - H;
            place_window();
            save_settings();
        }
    } else if (key == "sound") {
        g_settings.sound = value == "1";
        save_settings();
    } else if (key == "click_through") {
        g_settings.click_through = value == "1";
        apply_click_through();
        save_settings();
    } else if (key == "preview") {
        g_forced = value;
        g_forced_until = GetTickCount64() + 10000;
    } else if (key == "bit_size") {
        int v = std::atoi(value.c_str());
        if (v >= 48 && v <= 256) {
            RECT r;
            GetWindowRect(g_bit_window, &r);
            g_settings.bit_size = v;
            // Keep him centred over the same spot on the ground
            const int W = bit_canvas();
            g_settings.bit_x = r.left + ((r.right - r.left) - W) / 2;
            g_settings.bit_y = r.bottom - W;
            place_bit();
            save_settings();
        }
    } else if (key == "bit_shown") {
        g_settings.bit_shown = value == "1";
        ShowWindow(g_bit_window, g_settings.bit_shown ? SW_SHOWNOACTIVATE : SW_HIDE);
        save_settings();
    } else if (key == "bit_preview") {
        g_bit_forced = value;
        g_bit_forced_until = GetTickCount64() + 10000;
    } else if (key == "quit") {
        DestroyWindow(g_window);
    } else if (key == "restart") {
        // A fresh copy of her, which waits for this one to let go of the ports before it starts
        wchar_t exe[MAX_PATH];
        GetModuleFileNameW(nullptr, exe, MAX_PATH);
        ShellExecuteW(nullptr, L"open", exe, L"--restart", g_home.c_str(), SW_SHOWNORMAL);
        DestroyWindow(g_window);
    }
}

enum { MENU_SCALE = 100, MENU_SOUND = 200, MENU_CLICK, MENU_PAGE, MENU_BIT, MENU_RESTART, MENU_QUIT };

static void show_menu()
{
    HMENU sizes = CreatePopupMenu();
    for (int k = 2; k <= 5; k++) {
        wchar_t label[16];
        swprintf(label, 16, L"%dx", k);
        AppendMenuW(sizes, MF_STRING | (g_settings.scale == k ? MF_CHECKED : 0), MENU_SCALE + k, label);
    }
    HMENU menu = CreatePopupMenu();
    AppendMenuW(menu, MF_POPUP, (UINT_PTR)sizes, L"Size");
    AppendMenuW(menu, MF_STRING | (g_settings.sound ? MF_CHECKED : 0), MENU_SOUND, L"Chime when she needs you");
    AppendMenuW(menu, MF_STRING, MENU_CLICK, L"Let clicks pass through her");
    AppendMenuW(menu, MF_STRING, MENU_PAGE, L"Open the Minis page");
    AppendMenuW(menu, MF_STRING | (g_settings.bit_shown ? MF_CHECKED : 0), MENU_BIT, L"Show Bit");
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, MENU_RESTART, L"Restart her");
    AppendMenuW(menu, MF_STRING, MENU_QUIT, L"Send her home (quit)");
    POINT p;
    GetCursorPos(&p);
    SetForegroundWindow(g_window);
    int pick = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, p.x, p.y, 0, g_window, nullptr);
    DestroyMenu(menu);
    if (pick > MENU_SCALE && pick < MENU_SCALE + 10) run_command("scale=" + std::to_string(pick - MENU_SCALE));
    else if (pick == MENU_SOUND) run_command(std::string("sound=") + (g_settings.sound ? "0" : "1"));
    else if (pick == MENU_CLICK) run_command("click_through=1");
    else if (pick == MENU_PAGE) ShellExecuteW(nullptr, L"open", L"http://127.0.0.1:8780/", nullptr, nullptr, SW_SHOWNORMAL);
    else if (pick == MENU_BIT) run_command(std::string("bit_shown=") + (g_settings.bit_shown ? "0" : "1"));
    else if (pick == MENU_RESTART) run_command("restart");
    else if (pick == MENU_QUIT) run_command("quit");
}

enum { BIT_MENU_SIZE = 300, BIT_MENU_FOREMAN = 400, BIT_MENU_PAGE, BIT_MENU_HIDE, BIT_MENU_RESTART, BIT_MENU_QUIT };
static const int BIT_SIZES[] = {64, 96, 128, 176};
static const wchar_t* BIT_HOME = L"http://127.0.0.1:8700/#workers";  // the App Hub, opened on the AI Workers' pane
static const wchar_t* BIT_SIZE_NAMES[] = {L"Small", L"Medium", L"Large", L"Huge"};

static void show_bit_menu()
{
    HMENU sizes = CreatePopupMenu();
    for (int i = 0; i < 4; i++)
        AppendMenuW(sizes, MF_STRING | (g_settings.bit_size == BIT_SIZES[i] ? MF_CHECKED : 0), BIT_MENU_SIZE + i, BIT_SIZE_NAMES[i]);
    HMENU menu = CreatePopupMenu();
    AppendMenuW(menu, MF_POPUP, (UINT_PTR)sizes, L"Size");
    AppendMenuW(menu, MF_STRING, BIT_MENU_FOREMAN, L"Open the App Hub");
    AppendMenuW(menu, MF_STRING, BIT_MENU_PAGE, L"Open the Minis page");
    AppendMenuW(menu, MF_STRING, BIT_MENU_HIDE, L"Hide Bit");
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, BIT_MENU_RESTART, L"Restart the Minis");
    AppendMenuW(menu, MF_STRING, BIT_MENU_QUIT, L"Send the Minis home (quit)");
    POINT p;
    GetCursorPos(&p);
    SetForegroundWindow(g_bit_window);
    int pick = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, p.x, p.y, 0, g_bit_window, nullptr);
    DestroyMenu(menu);
    if (pick >= BIT_MENU_SIZE && pick < BIT_MENU_SIZE + 4) run_command("bit_size=" + std::to_string(BIT_SIZES[pick - BIT_MENU_SIZE]));
    else if (pick == BIT_MENU_FOREMAN) ShellExecuteW(nullptr, L"open", BIT_HOME, nullptr, nullptr, SW_SHOWNORMAL);
    else if (pick == BIT_MENU_PAGE) ShellExecuteW(nullptr, L"open", L"http://127.0.0.1:8780/", nullptr, nullptr, SW_SHOWNORMAL);
    else if (pick == BIT_MENU_HIDE) run_command("bit_shown=0");
    else if (pick == BIT_MENU_RESTART) run_command("restart");
    else if (pick == BIT_MENU_QUIT) run_command("quit");
}

// ---------------------------------------------------------------- the ear (UDP from claudia-signal)

static void listen_for_signals()
{
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    sockaddr_in at = {};
    at.sin_family = AF_INET;
    at.sin_port = htons(SIGNAL_PORT);
    inet_pton(AF_INET, "127.0.0.1", &at.sin_addr);
    if (bind(s, (sockaddr*)&at, sizeof at) != 0) return;
    char buffer[1024];
    for (;;) {
        int got = recv(s, buffer, sizeof buffer - 1, 0);
        if (got <= 0) continue;
        PostMessageW(g_window, WM_APP_EVENT, 0, (LPARAM) new std::string(buffer, got));
    }
}

// ---------------------------------------------------------------- the control page (HTTP)

static void send_all(SOCKET c, const std::string& data)
{
    size_t sent = 0;
    while (sent < data.size()) {
        int n = send(c, data.data() + sent, (int)(data.size() - sent), 0);
        if (n <= 0) return;
        sent += n;
    }
}

static void respond(SOCKET c, const char* status, const char* type, const std::string& body)
{
    std::ostringstream head;
    head << "HTTP/1.1 " << status << "\r\nContent-Type: " << type << "\r\nContent-Length: " << body.size()
         << "\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n";
    send_all(c, head.str() + body);
}

static bool safe_path(const std::string& path)
{
    return path.find("..") == std::string::npos && path.find(':') == std::string::npos;
}

static void serve_one(SOCKET c)
{
    std::string request;
    char buffer[4096];
    while (request.find("\r\n\r\n") == std::string::npos && request.size() < 65536) {
        int n = recv(c, buffer, sizeof buffer, 0);
        if (n <= 0) break;
        request.append(buffer, n);
    }
    std::istringstream line(request);
    std::string method, target;
    line >> method >> target;
    std::string path = target.substr(0, target.find('?'));
    std::string query = target.find('?') == std::string::npos ? "" : target.substr(target.find('?') + 1);

    if (method == "GET" && (path == "/" || path == "/index.html")) {
        respond(c, "200 OK", "text/html; charset=utf-8", read_file(g_home + L"\\web\\index.html"));
    } else if (method == "GET" && path == "/api/state") {
        std::string body;
        {
            std::lock_guard<std::mutex> hold(g_snapshot_lock);
            body = g_snapshot;
        }
        respond(c, "200 OK", "application/json", body);
    } else if (method == "POST" && path == "/api/command" && !query.empty() && query.size() < 64) {
        PostMessageW(g_window, WM_APP_COMMAND, 0, (LPARAM) new std::string(query));
        respond(c, "200 OK", "application/json", "{\"ok\":true}");
    } else if (method == "GET" && path.rfind("/sprites/", 0) == 0 && safe_path(path)) {
        std::string rel = path.substr(9);
        std::replace(rel.begin(), rel.end(), '/', '\\');
        std::string png = read_file(g_home + L"\\art\\sprites\\" + std::wstring(rel.begin(), rel.end()));
        if (png.empty()) respond(c, "404 Not Found", "text/plain", "not found");
        else respond(c, "200 OK", "image/png", png);
    } else {
        respond(c, "404 Not Found", "text/plain", "not found");
    }
    closesocket(c);
}

static void serve_page()
{
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    sockaddr_in at = {};
    at.sin_family = AF_INET;
    at.sin_port = htons(HTTP_PORT);
    inet_pton(AF_INET, "127.0.0.1", &at.sin_addr);
    if (bind(s, (sockaddr*)&at, sizeof at) != 0 || listen(s, 8) != 0) return;
    for (;;) {
        SOCKET c = accept(s, nullptr, nullptr);
        if (c == INVALID_SOCKET) continue;
        DWORD wait = 3000;
        setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, (const char*)&wait, sizeof wait);
        serve_one(c);
    }
}

// ---------------------------------------------------------------- the window

static BOOL CALLBACK find_claude_window(HWND hwnd, LPARAM found)
{
    // The desktop app's own window: visible, top-level, belonging to Claude.exe. The Claude Code CLI is claude.exe too,
    // but its console windows belong to the terminal, so it never matches. The first match is the one most recently on top
    if (!IsWindowVisible(hwnd) || GetWindow(hwnd, GW_OWNER) || GetWindowTextLengthW(hwnd) == 0) return TRUE;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!process) return TRUE;
    wchar_t path[MAX_PATH];
    DWORD size = MAX_PATH;
    bool claude = false;
    if (QueryFullProcessImageNameW(process, 0, path, &size)) {
        const wchar_t* name = wcsrchr(path, L'\\');
        claude = name && _wcsicmp(name + 1, L"Claude.exe") == 0;
    }
    CloseHandle(process);
    if (!claude) return TRUE;
    *(HWND*)found = hwnd;
    return FALSE;
}

static void bring_claude_forward()
{
    // Double-clicking her: the Claude app comes up and takes focus. Windows lets the process that got the last input
    // hand over the foreground, and the double-click was ours. Closed to the tray, it has no visible window, so launch
    // the Store app's alias instead; the app is single-instance, and a second launch shows its window
    HWND claude = nullptr;
    EnumWindows(find_claude_window, (LPARAM)&claude);
    if (!claude) {
        ShellExecuteW(nullptr, L"open", L"claude-desktop.exe", nullptr, nullptr, SW_SHOWNORMAL);
        return;
    }
    ShowWindow(claude, IsIconic(claude) ? SW_RESTORE : SW_SHOW);
    SetForegroundWindow(claude);
}

static LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_TIMER:
        tick();
        return 0;
    case WM_APP_EVENT: {
        std::string* text = (std::string*)lp;
        size_t tab = text->find('\t');
        std::string event = text->substr(0, tab), id = tab == std::string::npos ? "" : text->substr(tab + 1);
        while (!id.empty() && (id.back() == '\r' || id.back() == '\n')) id.pop_back();
        handle_event(event, id, GetTickCount64());
        delete text;
        return 0;
    }
    case WM_APP_COMMAND: {
        std::string* text = (std::string*)lp;
        run_command(*text);
        delete text;
        return 0;
    }
    case WM_NCHITTEST:
        // Transparent pixels already let clicks through; anywhere solid on her is a handle to drag her by
        return HTCAPTION;
    case WM_NCRBUTTONUP:
        show_menu();
        return 0;
    case WM_NCLBUTTONDBLCLK:
        // She's all title bar, so a double-click comes as a caption double-click; nothing to maximise, so it's ours
        bring_claude_forward();
        return 0;
    case WM_EXITSIZEMOVE: {
        RECT r;
        GetWindowRect(hwnd, &r);
        g_settings.x = r.left;
        g_settings.y = r.top;
        save_settings();
        return 0;
    }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static LRESULT CALLBACK bit_window_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    // Bit's window only draws and gets dragged; the ticking and the ears live in Claudia's
    switch (msg) {
    case WM_NCHITTEST:
        return HTCAPTION;
    case WM_NCRBUTTONUP:
        show_bit_menu();
        return 0;
    case WM_NCLBUTTONDBLCLK:
        ShellExecuteW(nullptr, L"open", BIT_HOME, nullptr, nullptr, SW_SHOWNORMAL);
        return 0;
    case WM_EXITSIZEMOVE: {
        RECT r;
        GetWindowRect(hwnd, &r);
        g_settings.bit_x = r.left;
        g_settings.bit_y = r.top;
        save_settings();
        return 0;
    }
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR args, int)
{
    // One Claudia at a time. A restart waits a few seconds for the old one to leave
    HANDLE only_one = CreateMutexW(nullptr, TRUE, L"ClaudiaMini.SingleInstance");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        if (!wcsstr(args, L"--restart")) return 0;
        DWORD waited = WaitForSingleObject(only_one, 10000);
        if (waited != WAIT_OBJECT_0 && waited != WAIT_ABANDONED) return 0;
    }

    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);

    wchar_t exe[MAX_PATH];
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    g_home = exe;
    g_home = g_home.substr(0, g_home.find_last_of(L'\\'));
    load_settings();
    load_art();
    if (g_art.empty()) {
        MessageBoxW(nullptr, L"No sprites found in art\\sprites. Run tools\\make_sprites.py first.",
                    L"Minis", MB_ICONWARNING);
        return 1;
    }
    build_bit_shapes();

    WNDCLASSW wc = {};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorW(nullptr, IDC_HAND);
    wc.lpszClassName = L"ClaudiaMini";
    RegisterClassW(&wc);
    // Tool window: no taskbar button, no Alt-Tab entry. No-activate: clicking her never steals focus from a game
    g_window = CreateWindowExW(WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                               wc.lpszClassName, L"Claudia Mini", WS_POPUP, 0, 0, 1, 1,
                               nullptr, nullptr, instance, nullptr);
    WNDCLASSW bit_class = {};
    bit_class.lpfnWndProc = bit_window_proc;
    bit_class.hInstance = instance;
    bit_class.hCursor = LoadCursorW(nullptr, IDC_HAND);
    bit_class.lpszClassName = L"BitMini";
    RegisterClassW(&bit_class);
    g_bit_window = CreateWindowExW(WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                   bit_class.lpszClassName, L"Bit", WS_POPUP, 0, 0, 1, 1,
                                   nullptr, nullptr, instance, nullptr);
    place_window();
    place_bit();
    apply_click_through();
    g_shown = "";
    tick();
    ShowWindow(g_window, SW_SHOWNOACTIVATE);
    if (g_settings.bit_shown) ShowWindow(g_bit_window, SW_SHOWNOACTIVATE);
    SetTimer(g_window, TIMER_TICK, TICK_MS, nullptr);

    std::thread(listen_for_signals).detach();
    std::thread(serve_page).detach();
    std::thread(watch_the_card).detach();

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    WSACleanup();
    CoUninitialize();
    return 0;
}
