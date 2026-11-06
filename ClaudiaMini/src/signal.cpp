// claudia-signal.exe: the plugin's hooks run this once per Claude Code event.
// It fires one UDP packet at the overlay and exits. If the overlay isn't running the packet is
// simply lost, so Claude Code never waits on Claudia and never notices she's missing.
//
//   claudia-signal.exe <event>        from a hook: the hook's JSON arrives on stdin
//   claudia-signal.exe oops --manual  from Claude herself, when she spots her own mistake

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <cstdio>
#include <string>

static const unsigned short OVERLAY_PORT = 8781;

static std::string read_stdin()
{
    std::string text;
    HANDLE in = GetStdHandle(STD_INPUT_HANDLE);
    if (in == nullptr || in == INVALID_HANDLE_VALUE)
        return text;
    char buffer[4096];
    DWORD got = 0;
    // Hook input is a few KB at most; past 256 KB (a huge tool_input) the session id was long since read
    while (text.size() < 262144 && ReadFile(in, buffer, sizeof buffer, &got, nullptr) && got > 0)
        text.append(buffer, got);
    return text;
}

// Just enough JSON to pull out one top-level string value; ids never hold escapes
static std::string string_field(const std::string& json, const char* key)
{
    std::string pattern = std::string("\"") + key + "\"";
    size_t at = json.find(pattern);
    if (at == std::string::npos)
        return "";
    at = json.find(':', at + pattern.size());
    if (at == std::string::npos)
        return "";
    at = json.find('"', at);
    if (at == std::string::npos)
        return "";
    size_t end = json.find('"', at + 1);
    return end == std::string::npos ? "" : json.substr(at + 1, end - at - 1);
}

static void send_packet(const std::string& message)
{
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
        return;
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s != INVALID_SOCKET) {
        sockaddr_in to = {};
        to.sin_family = AF_INET;
        to.sin_port = htons(OVERLAY_PORT);
        inet_pton(AF_INET, "127.0.0.1", &to.sin_addr);
        sendto(s, message.data(), (int)message.size(), 0, (sockaddr*)&to, sizeof to);
        closesocket(s);
    }
    WSACleanup();
}

int main(int argc, char** argv)
{
    if (argc < 2)
        return 0;
    std::string event = argv[1];
    bool manual = argc > 2 && std::string(argv[2]) == "--manual";

    std::string session;
    if (!manual) {
        std::string json = read_stdin();
        session = string_field(json, "session_id");
        // A subagent's tool calls are its parent session's work; they share the session_id anyway
    }
    send_packet(event + "\t" + session);

    if (event == "sessionstart") {
        // Plain stdout from a SessionStart hook becomes context for Claude
        char self[MAX_PATH] = {};
        GetModuleFileNameA(nullptr, self, MAX_PATH);
        std::printf("Claudia Mini, a small desktop sprite showing Ben what this session is doing, is running. "
                    "When you notice a mistake of your own (a wrong edit, a bad assumption you then correct), "
                    "running \"%s\" oops --manual once makes her show her sheepish pose. "
                    "It is optional and silent; it never needs mentioning.\n", self);
    }
    return 0;
}
