"""Site content for slederer.com.

This is the ONLY file you need to edit to update the personal site. Nothing here
touches HTML — the templates read these objects and lay them out.

Quick guide:
  * Add a portfolio company      -> append a Company(...) to PORTFOLIO
  * Move one into the SPV block  -> set spv=True on it
  * Edit the incubator           -> INCUBATOR
  * Edit bio / links / thesis    -> PROFILE and THESIS

`accent` is always a TOKEN NAME from ACCENTS (e.g. "purple"), never a hex code —
the template turns it into var(--purple). tests/test_content.py enforces this,
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
    """One product built during a cohort. Blurb optional — name-only is fine."""
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
class Incubator:
    name: str
    tagline: str
    description: str
    url: str = ""
    cohorts: tuple[Cohort, ...] = ()


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
    bullets: tuple[str, ...] = ()
    anti_bullets: tuple[str, ...] = ()
    check_size: str = ""
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
    contact_email: str = ""

    def json_ld(self) -> dict:
        """schema.org Person — single-sourced with the visible links."""
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
# TODO(stefan): confirm the bio wording reads how you want it, and set
# contact_email. The patent count is YOURS personally — I could not find a
# reliable public figure for Bitmovin's company-wide portfolio.
# ---------------------------------------------------------------------------

PROFILE = Profile(
    name="Stefan Lederer",
    role="CEO & Co-founder, Bitmovin",
    tagline="Building the video infrastructure behind a large share of internet "
            "streaming. Angel investor in early-stage technical founders.",
    location="Paris, France",
    bio=(
        "I'm the co-founder and CEO of Bitmovin. We started the company in 2013 "
        "out of research and standardisation work on adaptive streaming, "
        "co-creating MPEG-DASH — the format behind a large share of the video "
        "delivered over the internet today. Bitmovin now builds the encoding, "
        "playback and analytics infrastructure that streaming services run on.",
        "I still keep a foot in research: more than 25 papers and 10 patents in "
        "multimedia delivery and networking, and an associate professorship at "
        "the University of Klagenfurt.",
        "Alongside Bitmovin I invest as an angel in early-stage companies — "
        "usually technical founders at pre-seed and seed, often in "
        "infrastructure, developer tools and media. In a handful of cases I lead "
        "the round and bring other investors in through an SPV.",
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
# Cheque sizes are deliberately NOT modelled here — the page shows companies,
# not amounts. If you want them public, add an `amount` field and render it.
#
# Bitmovin is not in this list: it has its own section above.
#
# TODO(stefan): the blurbs below are DRAFTED from public knowledge of each
# company and need your eye before this goes live. These have NO blurb because
# I did not want to guess: GuardAero, Dartboard Energy, Earendil, Golpo,
# Hypernote, Linq, Ozeki, Pally, Rewbi, Splash Inc., Statewide, Trace.
# A blank blurb renders as a name-only tile, which is fine.
# ---------------------------------------------------------------------------

PORTFOLIO: tuple[Company, ...] = (
    # --- rounds I lead via an SPV ---
    Company("HockeyStack", "B2B marketing attribution and revenue analytics.",
            sector="Analytics", spv=True, role="Lead investor, syndicate via SPV",
            accent="purple"),
    Company("GuardAero", "",
            sector="Aviation", spv=True, role="Lead investor, syndicate via SPV",
            accent="cyan"),
    Company("Salvy", "Business mobile connectivity and eSIM in Brazil.",
            sector="Telecom", spv=True, role="Lead investor, syndicate via SPV",
            accent="green"),

    # --- direct angel investments (alphabetical) ---
    Company("0.email", "Open-source, AI-native email client.", sector="AI", accent="indigo"),
    Company("AiSDR", "AI sales development rep for outbound pipeline.", sector="Sales", accent="purple"),
    Company("Cosmic JS", "Headless CMS for content-driven applications.", sector="Dev tools", accent="cyan"),
    Company("crate", "Distributed SQL database for real-time machine data.", sector="Data", accent="blue"),
    Company("Dartboard Energy", "", sector="Energy", accent="yellow"),
    Company("Earendil", "", accent="indigo"),
    Company("GlassKube", "Open-source package manager for Kubernetes.", sector="Dev tools", accent="green"),
    Company("Golpo", "", accent="pink"),
    Company("Hilos", "WhatsApp automation for customer conversations.", sector="SaaS", accent="green"),
    Company("HumanLayer", "Human-in-the-loop approvals for AI agents.", sector="AI infra", accent="orange"),
    Company("Hypernote", "", accent="purple"),
    Company("Invofox", "AI document and invoice processing for finance teams.", sector="Fintech", accent="blue"),
    Company("Kickscale", "AI meeting intelligence for sales teams.", sector="Sales", accent="orange"),
    Company("Kilobaser", "Benchtop DNA synthesiser for research labs.", sector="Biotech", accent="pink"),
    Company("Linemetrics", "IoT sensor monitoring for buildings and industry.", sector="IoT", accent="cyan"),
    Company("Linq", "", accent="blue"),
    Company("Mistral", "Open-weight frontier AI models, built in Europe.", sector="AI", accent="orange"),
    Company("Oden.io", "Real-time analytics for manufacturing lines.", sector="Industrial", accent="red"),
    Company("Onboard.io", "Customer onboarding for B2B software teams.", sector="SaaS", accent="blue"),
    Company("Onedoclabs", "Document infrastructure for healthcare software.", sector="Health", accent="cyan"),
    Company("Ozeki", "", accent="green"),
    Company("Pally", "", accent="pink"),
    Company("Promptless", "Keeps product documentation up to date automatically.", sector="Dev tools", accent="indigo"),
    Company("Red Barn Robotics", "Robotic weeding for vegetable farms.", sector="Robotics", accent="green"),
    Company("Reflect", "No-code automated browser testing.", sector="Dev tools", accent="purple"),
    Company("Resquared", "Lead generation for teams selling to local businesses.", sector="Sales", accent="yellow"),
    Company("Rewbi", "", accent="cyan"),
    Company("Rownd", "Drop-in authentication and user onboarding.", sector="Dev tools", accent="blue"),
    Company("SpaceX", "Orbital launch and satellite internet.", sector="Space", accent="red"),
    Company("Splash Inc.", "", accent="orange"),
    Company("Statewide", "", accent="yellow"),
    Company("Trace", "", accent="indigo"),
    Company("Upflow", "Accounts-receivable automation for B2B finance teams.", sector="Fintech", accent="green"),
    Company("Waydev", "Engineering analytics for software teams.", sector="Dev tools", accent="purple"),
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
    tagline="Two iterations, Vienna and Klagenfurt",
    description=(
        "A programme that gives small teams ten weeks, real customers and a budget "
        "to take an AI idea from a hypothesis to a working product. We have run it "
        "twice; after the second cohort it became a permanent part of Bitmovin."
    ),
    cohorts=(
        Cohort(
            name="Summer 2025",
            period="First run",
            theme="Nine people, nine projects — eight of which ended up shipping "
                  "inside Bitmovin products.",
            status="completed",
            people=9,
            teams=9,
            accent="cyan",
            focus_areas=("Observability", "AI assistants", "Analytics",
                         "Test automation"),
            highlights=(
                "Nine people chosen after interviewing 350 candidates across Europe.",
                "Eight of the nine projects became features of Bitmovin products.",
                "Shown at IBC and other industry events.",
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
            theme="Fifteen interns, selected from 500 European applicants, shipping "
                  "seven products in ten weeks.",
            status="completed",
            people=15,
            teams=7,
            accent="purple",
            projects_total=7,
            focus_areas=("Streaming", "Observability", "Advertising",
                         "Video workflows", "AI tooling"),
            highlights=(
                "Teams demoed to real customers within four weeks and signed first test users.",
                "The programme is now permanent.",
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
# TODO(stefan): this is a reasonable default written to save founders time.
# Rewrite it in your own words — especially check_size and how_to_reach.
# ---------------------------------------------------------------------------

THESIS = Thesis(
    headline="What I look for",
    bullets=(
        "Technical founders who have felt the problem themselves.",
        "Infrastructure, developer tools, video and media — where I can actually help.",
        "A product a real user is already using, however small.",
        "Unglamorous problems with a clear reason they are hard.",
    ),
    anti_bullets=(
        "Pre-product decks with no working prototype.",
        "Consumer social and marketplaces — I would be a bad investor for you.",
        "Anything needing a large check to reach the next milestone.",
    ),
    check_size="PLACEHOLDER — e.g. €25k–100k, larger when leading via SPV",
    stages=("Pre-seed", "Seed"),
    geos=("Europe", "US"),
    how_to_reach=(
        "Send a short email with what you are building, who is using it, and what "
        "you need. A demo link beats a deck. I try to reply within a week."
    ),
)


# ---------------------------------------------------------------------------
# SIDE PROJECTS — shown at /projects, not on the homepage
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
# Derived views — the templates use these, never PORTFOLIO directly.
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
