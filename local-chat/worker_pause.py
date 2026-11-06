# Chat goes first: before each reply, ask the AI Workers' Foreman to step its worker aside until the chat goes quiet.
# The Foreman makes a fresh login link each start (E:\AIWorkers\data\foreman_login.txt); its token is the session cookie.

import json
import urllib.error
import urllib.parse
import urllib.request

from hub import login_link


def hold_request(link, minutes):
    parts = urllib.parse.urlsplit(link)
    token = urllib.parse.parse_qs(parts.query).get("token", [""])[0]
    if not token:
        return None
    return urllib.request.Request("%s://%s/api/chat-hold" % (parts.scheme, parts.netloc), method="POST",
                                  data=json.dumps({"minutes": minutes}).encode("utf-8"),
                                  headers={"Content-Type": "application/json", "Cookie": "foreman_session=" + token})


def pause_workers(workers_app, minutes):
    # Best effort: a Foreman that isn't running, or isn't signed in, never holds up the chat
    if not workers_app or minutes <= 0:
        return
    request = hold_request(login_link(workers_app), minutes)
    if request is None:
        return
    try:
        urllib.request.urlopen(request, timeout=25).close()
    except (urllib.error.URLError, OSError, ValueError):
        pass
