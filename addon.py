from datetime import datetime, timedelta, timezone
import json, os, requests, sys, time, tzlocal, urllib.parse, uuid
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


# SET UNIQUE DEVICE ID
if __addon__.getSetting("uuid") == "":
    __addon__.setSetting("uuid", str(uuid.uuid4()))


def build_url(query):
    """Get the addon url based on Kodi request"""

    return f"{base_url}?{urllib.parse.urlencode(query)}"


def load_epg(type, identifier):
    """Load the EPG data"""

    url = f"https://services.sg102.prd.sctv.ch/catalog/tv/broadcast/list/(ids={identifier};level=enorm)"
    genre_url = f"https://services.sg102.prd.sctv.ch/catalog/tv/{lang.capitalize()}Genres/genres/list/(ids=all;level=minimal)"

    try:
        epg_page = requests.get(url, timeout=5, headers=headers).json()["Nodes"]["Items"][0]
    except:
        xbmcgui.Dialog().textviewer("Handlung", "Keine Sendungdaten verfügbar")

    try:
        genre_page = {i["Identifier"].replace("de_", ""): i["Content"]["Description"]["Title"] for i in requests.get(genre_url, timeout=5, headers=headers).json()["Nodes"]["Items"]}
    except:
        genre_page = {}

    header = f'{"Jetzt/Now" if type == "now" else "Danach/Next" if type == "next" else "Handlung"}{": " + epg_page["Content"]["Description"]["Title"]}'

    desc = ""

    if epg_page["Content"].get("Series") and epg_page["Content"]["Description"].get("Subtitle"):
        if epg_page["Content"]["Series"].get("Season") and epg_page["Content"]["Series"].get("Episode"):
            desc = desc + (f'[B]{"Staffel" if lang == "de" else "Season"} {str(epg_page["Content"]["Series"]["Season"])}, {"Folge" if lang == "de" else "Episode"} {str(epg_page["Content"]["Series"]["Episode"])}[/B]: {epg_page["Content"]["Description"]["Subtitle"]}\n\n')
        else:
            desc = desc + (f'{epg_page["Content"]["Description"]["Subtitle"]}\n\n')

    desc = desc + epg_page["Content"]["Description"]["Summary"] + "\n\n"

    desc = desc + (f'[B]{"Bewertung" if lang == "de" else "Rating"}[/B]: {str((int(epg_page["Content"]["Description"]["Rating"]) / 10)) + "/10"}\n' if epg_page["Content"]["Description"].get("Rating") else "")
    desc = desc + (f'[B]{"Land" if lang == "de" else "Country"}[/B]: {epg_page["Content"]["Description"]["Country"]}\n' if epg_page["Content"]["Description"].get("Country") else "")
    desc = desc + (f'[B]{"Veröffentlichungsjahr" if lang == "de" else "Year"}[/B]: {str(datetime(*(time.strptime(epg_page["Content"]["Description"]["ReleaseDate"], "%Y-%m-%dT%H:%M:%SZ")[0:6])).year)}\n' if epg_page["Content"]["Description"].get("ReleaseDate") else "")
    desc = desc + (f'[B]{epg_page["Content"]["Description"]["AgeRestrictionSystem"]}[/B]: {epg_page["Content"]["Description"]["AgeRestrictionRating"]}\n' if epg_page["Content"]["Description"].get("AgeRestrictionSystem") else "")

    if len(epg_page.get("Relations", [])) > 0:
        if desc != "":
            desc = desc + "\n"
        
        directors = []
        actors = []
        genres = []
        
        for i in epg_page["Relations"]:
            if i["Kind"] == "Participant" and i["Role"] == "Director":
                directors.append(i["TargetNode"]["Content"]["Description"]["Fullname"])
            elif i["Kind"] == "Participant" and i["Role"] == "Actor":
                actors.append(i["TargetNode"]["Content"]["Description"]["Fullname"])
            elif i["Kind"] == "Genre" and i["Role"] == "Genre":
                genres.append(genre_page.get(i["TargetIdentifier"], "Unbekannt"))
        
        directors = " / ".join(directors)
        actors = ", ".join(actors)
        genres = " / ".join(genres)

        desc = desc + (f'[B]Genre[/B]: {genres}\n\n' if genres != "" else "")
        
        desc = desc + (f'[B]{"Regisseur" if lang == "de" else "Director"}[/B]: {directors}\n' if directors != "" else "")
        desc = desc + (f'[B]{"Schauspieler" if lang == "de" else "Actors"}[/B]: {actors}\n' if actors != "" else "")

    xbmcgui.Dialog().textviewer(header, desc)


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

    channels = {item["Identifier"]: {"name": f'{item["Title"]}{" UHD" if "UHD Sender" in item["Bouquets"] and "UHD" not in item["Title"] else ""}', "genre": item["Bouquets"][0],
                                     "desc": item["Description"], 
                                     "logo_url": f"https://services.sg101.prd.sctv.ch/content/images/tv/"
                                                 f"channel/{item['Identifier']}_w300.webp"}
                for item in live_page.json()
                if item["Services"].get("OTT.LiveTV", {"State": ""})["State"] == "Subscribed"
                and item["Visibility"] == "Visible"}

    if __addon__.getSetting("favorites") == "true":
        url = "https://services.sg101.prd.sctv.ch/portfolio/tv/lineups"
        favorites_page = requests.get(url, timeout=5, headers=ch_headers)
        for item in favorites_page.json():
            if item["Name"] == "Favoriten" if lang == "de" else "Favorites":
                channels = {i: channels[i] for i in item["Items"] if i in channels.keys()}

    # LOAD EPG
    timestamp_start = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    timestamp_end = (datetime.now(timezone.utc) + timedelta(hours=4)).strftime("%Y%m%d%H%M")
    epg_url = f"https://services.sg102.prd.sctv.ch/catalog/tv/channels/list/(end={timestamp_end};ids={','.join(channels.keys())};level=minimal;start={timestamp_start})"
    epg_data = {i["Identifier"]: i["Content"] for i in requests.get(epg_url, headers=headers).json()["Nodes"]["Items"]}

    for item in channels.keys():
        context_list = []
        
        try:
            epg_now = epg_data[item]["Nodes"]["Items"][0]
        except:
            url = build_url({'id': item})
            li = xbmcgui.ListItem(f'[COLOR yellow]--:--[/COLOR] [COLOR blue][B]{channels[item]["name"]}[/B][/COLOR] Keine Informationen verfügbar')
            li.setInfo('video', {'title': f'[B]{channels[item]["name"]}[/B]', 'genre': channels[item]["genre"],
                                 'plot': channels[item]["desc"]})
            li.setArt({"icon": channels[item]['logo_url'], "thumb": channels[item]['logo_url']})
            xbmcplugin.addDirectoryItem(handle=__addon_handle__, url=url, listitem=li, isFolder=False)
            continue

        epg_now_desc = epg_now["Content"]["Description"]["Title"]
        epg_now_sub = epg_now["Content"]["Description"].get("Subtitle")
        
        if len(epg_now.get("Availabilities", [])) > 0:
            epg_now_start = datetime(*(time.strptime(epg_now["Availabilities"][0]["AvailabilityStart"], "%Y-%m-%dT%H:%M:%SZ")[0:6])).replace(tzinfo=timezone.utc).astimezone(tzlocal.get_localzone())
        else:
            epg_now_start = datetime.now()

        epg_now_img = None
        epg_img_url = "https://services.sg102.prd.sctv.ch/content/images/"
        if epg_now["Content"].get("Nodes"):
            for i in epg_now["Content"]["Nodes"]["Items"]:
                if i.get("Kind", "") == "Image" and i.get("Role", "") in ["Landscape", "Lane"]:
                    epg_now_img = f'{epg_img_url}{i["ContentPath"]}_w1920.webp'
        fanart = "" if not epg_now_img else epg_now_img
        epg_now_img = channels[item]['logo_url'] if not epg_now_img else epg_now_img

        desc_now_url = build_url({'mode': 'desc', 'type': 'now', 'desc': epg_now["Identifier"]})
        context_list.append(("EPG (Jetzt/Now)", f"RunPlugin({desc_now_url})"))

        try:
            epg_next = epg_data[item]["Nodes"]["Items"][1]
            epg_next_desc = epg_next["Content"]["Description"]["Title"]
            epg_next_sub = epg_next["Content"]["Description"].get("Subtitle")
            epg_next_start = datetime(*(time.strptime(epg_next["Availabilities"][0]["AvailabilityStart"], "%Y-%m-%dT%H:%M:%SZ")[0:6])).replace(tzinfo=timezone.utc).astimezone(tzlocal.get_localzone())
            epg_next_end = datetime(*(time.strptime(epg_next["Availabilities"][0]["AvailabilityEnd"], "%Y-%m-%dT%H:%M:%SZ")[0:6])).replace(tzinfo=timezone.utc).astimezone(tzlocal.get_localzone())
            plot = f'[COLOR blue][B]Danach: {datetime.strftime(epg_next_start, "%H:%M")} - {datetime.strftime(epg_next_end, "%H:%M")} ({str(int((epg_next_end - epg_next_start).seconds / 60))} Min.)[/B][/COLOR]\n{epg_next_desc}{": " + epg_next_sub if epg_next_sub else ""}' + '\n\n' + channels[item]["desc"]

            desc_next_url = build_url({'mode': 'desc', 'type': 'next', 'desc': epg_next["Identifier"]})
            context_list.append(("EPG (Danach/Next)", f"RunPlugin({desc_next_url})"))
        except:
            plot = channels[item]["desc"]

        url = build_url({'id': item})
        li = xbmcgui.ListItem(f'[COLOR red]{datetime.strftime(epg_now_start, "%H:%M")}[/COLOR] [COLOR blue][B]{channels[item]["name"]}[/B][/COLOR] {epg_now_desc}{": " + epg_now_sub if epg_now_sub else ""}')
        li.setInfo('video', {'title': f'[B]{channels[item]["name"]}[/B] {epg_now_desc}{": " + epg_now_sub if epg_now_sub else ""}', 'genre': channels[item]["genre"],
                             'plot': plot})
        li.setArt({'fanart': fanart, "icon": channels[item]['logo_url'], "thumb": channels[item]['logo_url']})
        li.addContextMenuItems(context_list)
        xbmcplugin.addDirectoryItem(handle=__addon_handle__, url=url, listitem=li, isFolder=False)
        
    xbmcplugin.endOfDirectory(__addon_handle__)


def get_stream(channel_id):
    """Retrieve the live tv playlist"""

    session = login()
    if session == "":
        return

    title = "blue TV Air (Live)"

    ch_headers = headers
    ch_headers.update({"Authorization": f"Bearer {session}"})

    if __addon__.getSetting("loq") == "true":
        manifest_type = "dash_loq_cas"
    else:
        manifest_type = "dash_cas"

    url = f'https://services.sg1.etvp01.sctv.ch/streaming/liveTv/{channel_id}/{manifest_type}/0/signature'
    
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
        if params.get("mode", "") == "desc":
            load_epg(params.get("type"), params.get("desc"))

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
        if (int(time.time() - int(os.path.getmtime(f"{data_dir}/cookie.txt")))) > 172800:
            os.remove(f"{data_dir}/cookie.txt")
        else:
            with open(f"{data_dir}/cookie.txt", "r") as file:
                cookie = file.read()
                file.close()
                return cookie

    # Get username and password
    __login = __addon__.getSetting("username")
    __password = __addon__.getSetting("password")
    __device_id = __addon__.getSetting("uuid")
    if __login == "" or __password == "":
        xbmcgui.Dialog().notification(__addonname__,
                                      "Failed to retrieve the credentials. Please check the addon settings.",
                                      xbmcgui.NOTIFICATION_ERROR)
        return ""

    # APP TOKEN - ANDROID TV LOGIN
    s = requests.Session()
    s.headers.update(headers)

    login_url = 'https://bwsso.login.scl.swisscom.ch/login?SNA=tv2&uxtype=tv&L=de&' \
                'RURL=https%3A%2F%2Fapps.sctv.ch%2Fottbigscreen-universal%2F%3Fop%3Ddefault%26deviceFriendlyName%3DNVIDIA%2520SHIELD%2520Android%2520TV'
    login_data = {"username": "", "postusername": __login, "anmelden": "Weiter"}
    submit_data = {"password": __password, "p": "", "anmelden": "1"}

    login_page = s.get(login_url, timeout=5, allow_redirects=True)
    submit_page = s.post(login_page.url, timeout=5, data=login_data, allow_redirects=True)
    session_page = s.post(submit_page.url, timeout=5, data=submit_data, allow_redirects=True)
    
    session_dict = {item.split("=")[0]: item.split("=")[1] for item in session_page.url.split("?")[1].split("&")}

    session_data = {"Application": {"Identifier": "92d5b06c-7c7f-4dc4-889d-59e88df9d5da"},
                                                "Device": {"Name": "NVIDIA SHIELD Android TV",
                                                            "RecognitionId": __device_id,
                                                            "Type": "BigScreenGeneric"}, "Language": lang,
                                                "Sso": {"Instance": "Production", "LogoutPropagation": True,
                                                        "Provider": "SwisscomSso", "ServiceName": "tv2",
                                                        "Token": session_dict["T"],
                                                        "TokenSignature": session_dict["TS"]}}
    
    s.headers.update({"content-type": "application/json", "Accept": "application/json"})
    session_result = s.post("https://services.sg101.prd.sctv.ch/account/login", data=json.dumps(session_data))
    session = session_result.json()
    
    if session.get("SsoAuthenticated"):
        session_cookie = session["Identifier"]
    elif session.get("MultiStepLogin") and len(session["MultiStepLogin"].get("SelectableAccounts", [])) != 0:
        if len(session["MultiStepLogin"]["SelectableAccounts"][0]["ChangeableDevices"]) < 5:
            if session["MultiStepLogin"]["SelectableAccounts"][0].get("DeviceManagementState", "") == "NotUsable":
                xbmcgui.Dialog().notification(__addonname__, "Login failed: Device registration is blocked",
                                              xbmcgui.NOTIFICATION_ERROR)
                return ""
            device_id = __device_id
        else:
            device_id = None
            for i in session["MultiStepLogin"]["SelectableAccounts"][0]["ChangeableDevices"]:
                if i["Type"] == "BigScreenGeneric":
                    device_id = i["Identifier"]
            if not device_id:
                xbmcgui.Dialog().notification(__addonname__, "Login failed: Device list is full, no big screen device detected",
                                              xbmcgui.NOTIFICATION_ERROR)
                return ""
        
        select_data = {"Application": {"Identifier": "92d5b06c-7c7f-4dc4-889d-59e88df9d5da"},
                    "MultiStep": {
                            "OneTimeToken": session["MultiStepLogin"]["OneTimeToken"],
                            "SelectedAccount": session["MultiStepLogin"]["SelectableAccounts"][0]["Identifier"],
                            "SelectedDevice": device_id
                        }, "Language": lang}
        
        select_result = s.post("https://services.sg101.prd.sctv.ch/account/login", data=json.dumps(select_data))
        
        try:
            session_cookie = select_result.json()["Identifier"]
            with open(f"{data_dir}/cookie.txt", "w") as file:
                file.write(session_cookie)
                file.close()
            return session_cookie
        except:
            xbmcgui.Dialog().notification(__addonname__, "Unable to generate valid session token",
                                          xbmcgui.NOTIFICATION_ERROR)
            return ""
    else:
        xbmcgui.Dialog().notification(__addonname__, "Login failed: No subscription to be selected",
                                      xbmcgui.NOTIFICATION_ERROR)
        return ""


if __name__ == "__main__":
    router(sys.argv[2])
