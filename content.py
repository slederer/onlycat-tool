"""Site content for slederer.com.

This is the ONLY file you need to edit to update the personal site. Nothing here
touches HTML. The templates read these objects and lay them out.

Quick guide:
  * Add a portfolio company      -> append a Company(...) to PORTFOLIO
  * Move one into the SPV block  -> set spv=True on it
  * Edit the incubator           -> INCUBATOR
  * Edit bio / links / thesis    -> PROFILE and THESIS

`accent` is always a TOKEN NAME from ACCENTS (e.g. "purple"), never a hex code.
The template turns it into var(--purple). tests/test_content.py enforces this,
so a typo fails CI instead of rendering an invisible chip.
"""

from dataclasses import dataclass

# Accent tokens defined in templates/site_base.html. Using anything else renders
# as transparent, so tests/test_content.py rejects it.
ACCENTS = {
    "blue", "purple", "green", "orange", "cyan", "red", "yellow", "pink", "indigo",
}

COMPANY_STATUSES = {"active", "exited", "acquired", "dead"}
COHORT_STATUSES = {"completed", "running", "open"}

# Keep blurbs to one line so cards stay uniform. Enforced by tests.
MAX_BLURB = 90


@dataclass(frozen=True)
class Link:
    label: str
    url: str
    handle: str = ""
    show_in_hero: bool = True   # False -> footer and JSON-LD only


@dataclass(frozen=True)
class Company:
    name: str
    blurb: str = ""             # one line, <= MAX_BLURB chars; "" renders name-only
    url: str = ""               # "" renders a non-clickable tile
    sector: str = ""
    stage: str = ""             # stage at entry, e.g. "Seed"
    year: int | None = None
    location: str = ""
    status: str = "active"      # see COMPANY_STATUSES
    spv: bool = False           # True -> rendered in the "Rounds I lead" block
    role: str = ""              # SPV only, e.g. "Lead investor, syndicate via SPV"
    accent: str = "blue"


@dataclass(frozen=True)
class CohortProject:
    """One product built during a cohort. Blurb optional, name-only is fine."""
    name: str
    blurb: str = ""


@dataclass(frozen=True)
class Cohort:
    name: str
    period: str                 # "Ten weeks"
    theme: str                  # one sentence
    status: str = "completed"   # see COHORT_STATUSES
    people: int | None = None
    teams: int | None = None
    focus_areas: tuple[str, ...] = ()
    highlights: tuple[str, ...] = ()
    projects: tuple[CohortProject, ...] = ()
    # How many projects the cohort actually ran. If it exceeds len(projects),
    # the page says "N of M shown" rather than implying the list is complete.
    projects_total: int | None = None
    accent: str = "cyan"
    url: str = ""


@dataclass(frozen=True)
class Photo:
    src: str                    # path under /static/site/
    alt: str                    # required: this is the accessible description


@dataclass(frozen=True)
class Incubator:
    name: str
    tagline: str
    description: str
    url: str = ""
    cohorts: tuple[Cohort, ...] = ()
    photos: tuple[Photo, ...] = ()
    photo_caption: str = ""


@dataclass(frozen=True)
class Project:
    name: str
    description: str
    host: str                   # bare hostname, no scheme
    emoji: str
    accent: str = "blue"

    @property
    def href(self) -> str:
        return f"https://{self.host}"


@dataclass(frozen=True)
class Thesis:
    headline: str
    sectors: tuple[tuple[str, str], ...] = ()   # (label, accent token)
    bullets: tuple[str, ...] = ()
    anti_bullets: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    geos: tuple[str, ...] = ()
    how_to_reach: str = ""


@dataclass(frozen=True)
class Profile:
    name: str
    role: str
    tagline: str
    location: str = ""
    bio: tuple[str, ...] = ()
    facts: tuple[tuple[str, str], ...] = ()
    links: tuple[Link, ...] = ()
    # Research projects Bitmovin funds. Deliberately separate from `links`,
    # which feeds schema.org sameAs and must only hold Stefan's own profiles.
    research: tuple[Link, ...] = ()
    research_note: str = ""
    portrait: str = ""          # "" hides the hero portrait
    contact_email: str = ""

    def json_ld(self) -> dict:
        """schema.org Person, single-sourced with the visible links."""
        return {
            "@context": "https://schema.org",
            "@type": "Person",
            "name": self.name,
            "jobTitle": self.role,
            "url": "https://slederer.com",
            "worksFor": {"@type": "Organization", "name": "Bitmovin",
                         "url": "https://bitmovin.com"},
            "sameAs": [link.url for link in self.links if link.url],
        }


# ---------------------------------------------------------------------------
# PROFILE
#
# The facts below are sourced from Stefan's own IBC/NAB speaker bio ("more than
# 25 research papers and 10 patents in the field of multimedia delivery and
# networks") and his Google Scholar profile (2,187 citations, h-index 20).
#
# NOTE: Scholar still lists an associate professorship at Klagenfurt. Stefan
# says that is out of date. He guest lectured there, and Bitmovin funds
# research with the university. Do not reinstate the professorship claim.
#
# TODO(stefan): confirm the bio wording reads how you want it, and set
# contact_email. The patent count is YOURS personally. I could not find a
# reliable public figure for Bitmovin's company-wide portfolio.
# ---------------------------------------------------------------------------

PROFILE = Profile(
    name="Stefan Lederer",
    role="CEO & Co-founder, Bitmovin",
    tagline="I build video infrastructure at Bitmovin. I also put my own money "
            "into early-stage technical founders.",
    location="",
    bio=(
        "I co-founded Bitmovin in 2013 and run it as CEO. It grew out of our "
        "research on adaptive streaming and the work we did on MPEG-DASH, which "
        "is now how a large share of internet video gets delivered. Today we "
        "build the encoding, playback and analytics that streaming services "
        "run on.",
        "I never fully left the research side. 25 papers and 10 patents in "
        "multimedia delivery and networking. I have guest lectured at the "
        "University of Klagenfurt over the years, and Bitmovin funds several "
        "research projects with them. The biggest is ATHENA, a Christian "
        "Doppler laboratory working on adaptive streaming and networked "
        "multimedia.",
        "I also invest my own money in early-stage companies. Mostly pre-seed "
        "and seed, mostly technical founders, in B2B SaaS, security and "
        "defence, and energy. Three times so far I have led the round and "
        "brought other investors in through an SPV.",
    ),
    facts=(
        ("2013", "Co-founded Bitmovin"),
        ("MPEG-DASH", "Co-created the standard"),
        ("10", "Patents"),
        ("25+", "Research papers"),
        ("2,100+", "Scholar citations"),
    ),
    links=(
        Link("LinkedIn", "https://www.linkedin.com/in/stefanlederer/"),
        Link("X", "https://x.com/slederer", handle="@slederer"),
        Link("Google Scholar",
             "https://scholar.google.com/citations?user=wRckgn0AAAAJ&hl=de",
             show_in_hero=False),
        Link("Bitmovin", "https://bitmovin.com", show_in_hero=False),
    ),
    research=(
        Link("ATHENA", "https://athena.itec.aau.at/"),
    ),
    research_note="and several other projects with the University of Klagenfurt",
    portrait="/static/site/stefan.jpg",
    contact_email="stefan.lederer@bitmovin.com",
)


# ---------------------------------------------------------------------------
# BITMOVIN
# ---------------------------------------------------------------------------

BITMOVIN = Company(
    name="Bitmovin",
    blurb="Encoding, player and analytics infrastructure for online video.",
    url="https://bitmovin.com",
    sector="Video infrastructure",
    year=2013,
    accent="blue",
)


# ---------------------------------------------------------------------------
# PORTFOLIO
#
# ONE list. Set spv=True to move a company into the "Rounds I lead" block.
#
# Cheque sizes are deliberately NOT modelled here. The page shows companies,
# not amounts. If you want them public, add an `amount` field and render it.
#
# Bitmovin is not in this list: it has its own section above.
#
# Order matters: the angel list is rendered in this order, roughly largest and
# best known first. Move a line to move a company on the page.
#
# TODO(stefan): the blurbs are DRAFTED from each company's own site or press
# coverage and need your eye. Still no blurb: Rewbi (stealth, deliberate) and
# Statewide (could not identify it; the name is too generic to search).
# ---------------------------------------------------------------------------

PORTFOLIO: tuple[Company, ...] = (
    # --- rounds I lead via an SPV ---
    Company("HockeyStack", "B2B marketing attribution and revenue analytics.",
            sector="Analytics", spv=True, role="Lead investor, syndicate via SPV",
            accent="pink"),
    Company("GuardAero", "Counter-drone protection systems for military vehicles.",
            sector="Defence", spv=True, role="Lead investor, syndicate via SPV",
            accent="blue"),
    Company("Salvy", "Business mobile connectivity and eSIM in Brazil.",
            sector="Telecom", spv=True, role="Lead investor, syndicate via SPV",
            accent="green"),

    # --- direct angel investments, roughly largest first ---
    Company("SpaceX", "Orbital launch and satellite internet.",
            url="https://www.spacex.com", sector="Space", accent="blue"),
    Company("Mistral", "Open-weight frontier AI models, built in Europe.",
            url="https://mistral.ai", sector="AI", accent="orange"),
    Company("crate", "Distributed SQL database for real-time machine data.",
            url="https://cratedb.com", sector="Data", accent="blue"),
    Company("Upflow", "Accounts-receivable automation for B2B finance teams.",
            url="https://upflow.io", sector="Fintech", accent="green"),
    Company("Oden.io", "Real-time analytics for manufacturing lines.",
            url="https://oden.io", sector="Industrial", accent="red"),
    Company("Waydev", "Engineering analytics for software teams.",
            url="https://waydev.co", sector="Dev tools", accent="purple"),
    Company("Resquared", "Lead generation for teams selling to local businesses.",
            sector="Sales", accent="yellow"),
    Company("AiSDR", "AI sales development rep for outbound pipeline.",
            sector="Sales", accent="purple"),
    Company("Invofox", "AI document and invoice processing for finance teams.",
            sector="Fintech", accent="blue"),
    Company("Kilobaser", "Benchtop DNA synthesiser for research labs.",
            sector="Biotech", accent="pink"),
    Company("Onedoclabs", "Document infrastructure for healthcare software.",
            sector="Health", accent="cyan"),
    Company("Linemetrics", "IoT sensor monitoring for buildings and industry.",
            sector="IoT", accent="cyan"),
    Company("Cosmic JS", "Headless CMS for content-driven applications.",
            sector="Dev tools", accent="cyan"),
    Company("Reflect", "No-code automated browser testing.",
            sector="Dev tools", accent="purple"),
    Company("Onboard.io", "Customer onboarding for B2B software teams.",
            sector="SaaS", accent="blue"),
    Company("Kickscale", "AI meeting intelligence for sales teams.",
            sector="Sales", accent="orange"),
    Company("Hilos", "WhatsApp automation for customer conversations.",
            sector="SaaS", accent="green"),
    Company("Rownd", "Drop-in authentication and user onboarding.",
            sector="Dev tools", accent="blue"),
    Company("Golpo", "Turns documents and prompts into whiteboard animation videos.",
            url="https://video.golpoai.com", sector="AI video", accent="pink"),
    Company("Red Barn Robotics", "Robotic weeding for vegetable farms.",
            sector="Robotics", accent="green"),
    Company("Splash Inc.", "Autonomous surface vessels for maritime security.",
            url="https://splash9.com", sector="Defence", accent="red"),
    Company("Ozeki", "AI that negotiates and reviews contracts.",
            url="https://www.ozeki.ai", sector="Legal tech", accent="green"),
    Company("Pally", "AI assistant over text that remembers your life and follows up.",
            url="https://pally.com", sector="AI", accent="pink"),
    Company("HumanLayer", "Human-in-the-loop approvals for AI agents.",
            sector="AI infra", accent="orange"),
    Company("GlassKube", "Open-source package manager for Kubernetes.",
            sector="Dev tools", accent="green"),
    Company("Promptless", "Keeps product documentation up to date automatically.",
            sector="Dev tools", accent="indigo"),
    Company("0.email", "Open-source, AI-native email client.",
            sector="AI", accent="indigo"),
    Company("Hyprnote", "Open-source AI notetaker that keeps meeting data on-device.",
            url="https://www.ycombinator.com/launches/OEu-hyprnote-open-source-ai-notetaker-for-enterprises",
            sector="AI", accent="purple"),
    Company("Linq", "Private photo sharing where you can revoke access after sending.",
            url="https://sendlinqs.com", sector="Consumer", accent="blue"),
    Company("Earendil", "Building AI tools in the open.",
            url="https://earendil.com", sector="AI", accent="indigo"),
    Company("Rewbi", "", url="https://www.rewbi.com", sector="Stealth", accent="cyan"),
    Company("Dartboard Energy", "AI analyst that finds missed revenue for grid batteries.",
            url="https://dartboard.energy", sector="Energy", accent="yellow"),
    Company("Statewide", "", accent="yellow"),
    Company("Trace", "Maps a company so AI agents know where they fit.",
            sector="AI infra", accent="indigo"),
)


# ---------------------------------------------------------------------------
# BITMOVIN AI INCUBATOR
#
# Cohort 2 is sourced from the Demo Day overview and the Klagenfurt press
# release (Sept 2026); cohort 1 from Stefan directly.
#
# Cohort 1 lists 6 of its 9 projects (projects_total=9), so the page says
# "6 of 9 shown" instead of implying the list is complete. Add the missing
# three and the note disappears on its own.
# ---------------------------------------------------------------------------

INCUBATOR = Incubator(
    name="Bitmovin AI Incubator",
    tagline="Two rounds, Vienna and Klagenfurt",
    description=(
        "We give small teams ten weeks, a budget and access to real customers, "
        "then see what they can ship. We have run it twice. After the second "
        "round we made it permanent."
    ),
    photos=(
        Photo("/static/site/incubator-1.jpg",
              "Two Talecut team members presenting to the room on Demo Day."),
        Photo("/static/site/incubator-2.jpg",
              "The Quicly team presenting to a seated audience at the Demo Day."),
    ),
    photo_caption="Demo Day, Summer 2026",
    cohorts=(
        Cohort(
            name="Summer 2025",
            period="First run",
            theme="Nine people, nine projects. Eight of them ended up inside "
                  "Bitmovin products.",
            status="completed",
            people=9,
            teams=9,
            accent="blue",
            focus_areas=("Observability", "AI assistants", "Analytics",
                         "Test automation"),
            highlights=(
                "We interviewed 350 people across Europe to fill nine places.",
                "Eight of the nine projects became features in Bitmovin products.",
                "Shown at IBC and other industry shows.",
            ),
            projects_total=9,
            projects=(
                CohortProject("Model training for observability data"),
                CohortProject("AISA Highlight Clips"),
                CohortProject("Personal AI assistants"),
                CohortProject("Industry Insights Report"),
                CohortProject("TestAutomation MCP & Support Copilot"),
                CohortProject("Analytics Anomaly Detection"),
            ),
        ),
        Cohort(
            name="Summer 2026",
            period="Ten weeks",
            theme="Fifteen interns picked from 500 applicants across Europe. "
                  "Seven products in ten weeks.",
            status="completed",
            people=15,
            teams=7,
            accent="pink",
            projects_total=7,
            focus_areas=("Streaming", "Observability", "Advertising",
                         "Video workflows", "AI tooling"),
            highlights=(
                "Teams were demoing to customers inside four weeks.",
                "Several signed their first test users before the ten weeks were up.",
            ),
            projects=(
                CohortProject("Quicly", "Multiview live streaming on Media over QUIC."),
                CohortProject("Kairos", "Automatic highlight clipping for live sport."),
                CohortProject("End-to-End Observability",
                              "Per-segment quality scoring and self-healing encodings."),
                CohortProject("Davy", "Advertising observability, live in the dashboard."),
                CohortProject("govideo", "Browser-native live streaming you control by typing."),
                CohortProject("Talecut", "GPU-accelerated vertical reframing with subject detection."),
                CohortProject("Context Goblin", "AI code review with specialised agents."),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# INVESTING THESIS
#
# Sectors are Stefan's. The bullets and how_to_reach are still drafted.
# TODO(stefan): reword in your own voice.
# ---------------------------------------------------------------------------

THESIS = Thesis(
    headline="What I look for",
    sectors=(
        ("B2B SaaS", "blue"),
        ("Security & Defence", "pink"),
        ("Energy", "green"),
    ),
    bullets=(
        "Founders who have hit the problem themselves.",
        "Something already built that someone is using.",
        "Problems that look boring on the surface and are hard underneath.",
    ),
    anti_bullets=(
        "Decks with nothing built yet.",
        "Consumer social and marketplaces. I would be no help to you.",
        "Rounds where my cheque would not move the needle.",
    ),
    stages=("Pre-seed", "Seed"),
    geos=("Europe", "US"),
    how_to_reach=(
        "Email me. Tell me what you are building, who is using it and what you "
        "need. A link to something working beats a deck."
    ),
)


# ---------------------------------------------------------------------------
# SIDE PROJECTS, shown at /projects rather than the homepage
# ---------------------------------------------------------------------------

PROJECTS: tuple[Project, ...] = (
    Project("OnlyCat Dashboard", "Real-time cat activity monitoring, analytics and "
            "smart door controls for Oni.", "oni.slederer.com", "\U0001F431", "orange"),
    Project("Streaming Finder", "Find where any film or series is streaming, across "
            "services and regions.", "streaming.slederer.com", "\U0001F3AC", "purple"),
    Project("Stream Monitor", "Live monitoring and QoE metrics for streaming "
            "endpoints.", "stream.slederer.com", "\U0001F39E", "indigo"),
    Project("Bitmovin CRM", "Pipeline and account dashboard built on the Bitmovin "
            "data warehouse.", "crm.slederer.com", "\U0001F4BC", "blue"),
    Project("YC Startup Tracker", "Track Y Combinator batches, funding and founder "
            "moves over time.", "tracker.slederer.com", "\U0001F680", "yellow"),
    Project("Trading Dashboard", "Portfolio tracking and strategy backtesting.",
            "trading.slederer.com", "\U0001F4C8", "green"),
    Project("Ads Manager", "AI-generated localized ad creative across markets.",
            "ads.slederer.com", "\U0001F4E2", "red"),
    Project("CTV Analytics", "Connected-TV audience and inventory analytics.",
            "ctv.slederer.com", "\U0001F4FA", "pink"),
    Project("Encoding Intel", "Competitive intelligence on video encoding vendors.",
            "intel.slederer.com", "\U0001F50D", "cyan"),
    Project("Security Monitor", "Continuous security scanning for my deployed "
            "services.", "security.slederer.com", "\U0001F512", "red"),
)


# ---------------------------------------------------------------------------
# Derived views. Templates use these, never PORTFOLIO directly.
# ---------------------------------------------------------------------------

def spv_companies() -> tuple[Company, ...]:
    """Companies where Stefan leads the round via an SPV."""
    return tuple(c for c in PORTFOLIO if c.spv)


def angel_companies() -> tuple[Company, ...]:
    """Ordinary direct angel investments."""
    return tuple(c for c in PORTFOLIO if not c.spv)


def page_context() -> dict:
    """Everything templates/homepage.html needs."""
    return {
        "profile": PROFILE,
        "thesis": THESIS,
        "bitmovin": BITMOVIN,
        "spv_companies": spv_companies(),
        "angel_companies": angel_companies(),
        "incubator": INCUBATOR,
        "projects": PROJECTS,
    }
