# What each GGCMS site is, in a line a small model can use for context; unknown sites fall back to their name
SITES = {
    "revoltlib": ("RevoltLib", "an online library of anarchist, socialist and other radical writing, much of it old or translated"),
    "revoltsource": ("RevoltSource", "an online archive of radical and revolutionary source documents"),
    "revoltlink": ("RevoltLink", "a directory of radical and revolutionary organisations and websites"),
    "earthfluent": ("EarthFluent", "a site for learning vocabulary in other languages"),
    "holdoffhunger": ("HoldOffHunger", "a personal site of writing and projects"),
    "masereelgroup": ("Masereel Group", "a site about the woodcut novels of Frans Masereel and the artists around him"),
    "wordweight": ("WordWeight", "a site about words and their use"),
    "yallhearingthis": ("Y'all Hearing This?!", "a K-pop reaction channel's site: a page per show and per artist reacted to"),
}


def site_name(target: str) -> str:
    return SITES.get(target, (target, ""))[0]


def site_about(target: str) -> str:
    name, about = SITES.get(target, (target, ""))
    return f"{name}, {about}" if about else name
