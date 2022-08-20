from time import time
import json, os, requests, sys, urllib.parse, uuid
import xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs


headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 11_4) AppleWebKit/605.1.15 '
                         '(KHTML, like Gecko) Version/14.1 Safari/605.1.15'}

__addon__ = xbmcaddon.Addon()
__addonname__ = __addon__.getAddonInfo('name')
data_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))

base_url = sys.argv[0]
__addon_handle__ = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])
lang = "de" if xbmc.getLanguage(xbmc.ISO_639_1) == "de" else "en"

xbmcplugin.setContent(__addon_handle__, 'videos')


def build_url(query):
    """Get the addon url based on Kodi request"""

    return f"{base_url}?{urllib.parse.urlencode(query)}"


def load_channels():
    """Load the channel list"""

    session = login()
    if session == "":
        return

    channels = dict()
    
    ch_headers = headers
    ch_headers.update({"Authorization": f"Bearer {session}"})

    url = "https://services.sg101.prd.sctv.ch/portfolio/tv/channels"

    live_page = requests.get(url, timeout=5, headers=ch_headers)

    channels = {item["Identifier"]: {"name": item["Title"], "genre": item["Bouquets"][0],
                                     "desc": item["Description"], 
                                     "logo_url": f"https://services.sg101.prd.sctv.ch/content/images/tv/"
                                                 f"channel/{item['Identifier']}_w300.webp"}
                for item in live_page.json()
                if item["Services"].get("OTT.LiveTV", {"State": ""})["State"] == "Subscribed"
                and item["Visibility"] == "Visible"}

    if __addon__.getSetting("favorites"):
        url = "https://services.sg101.prd.sctv.ch/portfolio/tv/lineups"
        favorites_page = requests.get(url, timeout=5, headers=ch_headers)
        for item in favorites_page.json():
            if item["Name"] == "Favoriten" if lang == "de" else "Favorites":
                channels = {i: channels[i] for i in item["Items"] if i in channels.keys()}

    channel_listing = []
    for item in channels.keys():
        url = build_url({'id': item})
        li = xbmcgui.ListItem(channels[item]["name"])
        li.setArt({"thumb": channels[item]['logo_url']})
        li.setInfo('video', {'title': channels[item]["name"], 'genre': channels[item]["genre"],
                             'plot': channels[item]["desc"]})
        channel_listing.append((url, li, False))

    xbmcplugin.addDirectoryItems(__addon_handle__, channel_listing, len(channel_listing))
    xbmcplugin.endOfDirectory(__addon_handle__)


def get_stream(channel_id):
    """Retrieve the live tv playlist"""

    session = login()
    if session == "":
        return

    title = "blue TV (Live)"

    ch_headers = headers
    ch_headers.update({"Authorization": f"Bearer {session}"})

    url = f'https://services.sg1.etvp01.sctv.ch/streaming/liveTv/{channel_id}/dash_cas/0/42'
    
    page = requests.get(url, timeout=5, headers=ch_headers)
    channel_data = page.json()
    watch_url = channel_data["Address"]

    if channel_data.get("IsEncrypted"):
        license_url = "https://services.sg102.prd.sctv.ch/drm.cas/widevine/license"
    else:
        license_url = None
    
    license_headers = f"Authorization=Bearer {session}|R{'{SSM}'}|"

    return watch_url, license_url, license_headers, title


def playback(stream_url, license_url, license_headers, title):
    """Pass the urls and infolabels to the player"""

    try:
        thumb = xbmc.getInfoLabel("ListItem.Thumb")
        plot = xbmc.getInfoLabel("ListItem.Plot")
        genre = xbmc.getInfoLabel("ListItem.Genre")
        title = xbmc.getInfoLabel("ListItem.Title")
    except:
        pass

    li = xbmcgui.ListItem(path=stream_url)

    if license_url is not None:
        li.setProperty('inputstream.adaptive.license_key', license_url + "|" + license_headers)
        li.setProperty('inputstream.adaptive.license_type', "com.widevine.alpha")
        li.setProperty('inputstream.adaptive.stream_selection_type', 'fixed-res')
        li.setProperty('inputstream.adaptive.manifest_update_parameter', 'full')

    li.setProperty('inputstream', 'inputstream.adaptive')
    li.setProperty('inputstream.adaptive.manifest_type', 'mpd')
    li.setProperty("IsPlayable", "true")

    li.setProperty("IsPlayable", "true")
    try:
        li.setInfo("video", {"title": title, "plot": plot, "genre": genre})
        li.setArt({'thumb': thumb})
    except:
        li.setInfo("video", {"title": title})

    xbmcplugin.setResolvedUrl(__addon_handle__, True, li)

    xbmc.Player().play(item=stream_url, listitem=li)


def router(item):
    """Router function calling other functions of this script"""

    params = dict(urllib.parse.parse_qsl(item[1:]))

    if params:       
        # LIVE TV / VOD STREAM
        if params.get("id"):
            stream_params = get_stream(params["id"])
            if stream_params:
                playback(stream_params[0], stream_params[1], stream_params[2], stream_params[3])

    else:
        # LIVE TV CHANNEL LIST
        load_channels()
        

def login():
    """Retrieve the session cookie to access the video content"""

    # Check geolocation
    url = requests.get('https://services.sg101.prd.sctv.ch/account/geotargeting', timeout=5, headers=headers)
    if not url.json()["InContentArea"]:
        xbmcgui.Dialog().notification(__addonname__, "Out of country, please check your IP address.",
                                      xbmcgui.NOTIFICATION_ERROR)
        return ""

    # Retrieve existing cookie from file
    if os.path.exists(f"{data_dir}/cookie.txt"):
        if (int(os.path.getmtime(f"{data_dir}/cookie.txt")) - int(time())) > 2592000:
            os.remove(f"{data_dir}/cookie.txt")
        else:
            with open(f"{data_dir}/cookie.txt", "r") as file:
                cookie = file.read()
                file.close()
                return cookie

    # Get username and password
    __login = __addon__.getSetting("username")
    __password = __addon__.getSetting("password")
    if __login == "" or __password == "":
        xbmcgui.Dialog().notification(__addonname__,
                                      "Failed to retrieve the credentials. Please check the addon settings.",
                                      xbmcgui.NOTIFICATION_ERROR)
        return ""

    # Login to webservice
    s = requests.Session()
    login_url = 'https://bwsso.login.scl.swisscom.ch/login?SNA=tv2&L=de' \
                '&RURL=https%3A%2F%2Ftv.blue.ch%2FoauthRedirect%3Fprovider%3DSwisscomSso&keepLogin=true' \
                '&presentation=dark'

    login_headers = headers

    s.get(login_url, timeout=5, headers=login_headers)
    s.post('https://login.scl.swisscom.ch/submit-username', timeout=5, headers=login_headers,
            data={"identifier": __login, "dummyPasswordField": "", "stayLoggedIn": "on"})
    login_result = s.post('https://login.scl.swisscom.ch/submit-password', timeout=5, headers=login_headers,
                            data={"username": __login, "password": __password})

    if "error" in login_result.url or "submit-username" in login_result.url:
        xbmcgui.Dialog().notification(__addonname__, "Wrong username or password",
                                      xbmcgui.NOTIFICATION_ERROR)
        return ""

    session_dict = {item.split("=")[0]: item.split("=")[1] for item in login_result.url.split("?")[1].split("&")}
    rec_id = str(uuid.uuid4())

    login_headers.update(
        {"content-type": "application/json", "Authorization": "Bearer null", "Accept": "application/json"})
    bootstrap_result = s.post('https://services.sg101.prd.sctv.ch/account/bootstrap', timeout=5,
                                headers=login_headers,
                                data=json.dumps({"Anonymous": True,
                                                "Application": {
                                                    "Identifier": "ec731aea-b3b0-4338-ab8c-969eb6f8d551"},
                                                "Device": {"Name": "Safari_605.1.15",
                                                            "RecognitionId": rec_id,
                                                            "Type": "Computer"},
                                                "Domain": "TV2014",
                                                "Language": "de"}))

    login_headers.update({"Authorization": f"Bearer {bootstrap_result.json()['Session']['Identifier']}"})

    session_result = s.post('https://services.sg101.prd.sctv.ch/account/login', timeout=5, headers=login_headers,
                            data=json.dumps({"Application": {"Identifier": "e354da44-f167-4220-9bf1-97baff1afb54"},
                                                "Device": {"Name": "Safari_605.1.15",
                                                        "RecognitionId": rec_id,
                                                        "Type": "Computer"}, "Language": "de",
                                                "Sso": {"Instance": "Production", "LogoutPropagation": True,
                                                        "Provider": session_dict["provider"], "ServiceName": "tv2",
                                                        "Token": session_dict["T"],
                                                        "TokenSignature": session_dict["TS"]}}))

    session_cookie = session_result.cookies.get("Session")

    if not session_cookie:
        xbmcgui.Dialog().notification(__addonname__, "Unable to generate valid session token",
                                      xbmcgui.NOTIFICATION_ERROR)
        return ""
    else:
        with open(f"{data_dir}/cookie.txt", "w") as file:
            file.write(session_cookie)
            file.close()
        return session_cookie


if __name__ == "__main__":
    router(sys.argv[2])