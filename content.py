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


@dataclass(frozen=True)
class Company:
    name: str
    blurb: str                  # one line, <= MAX_BLURB chars
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
class Cohort:
    name: str
    period: str                 # "Spring 2025"
    theme: str                  # one sentence
    status: str = "completed"   # see COHORT_STATUSES
    teams: int | None = None
    focus_areas: tuple[str, ...] = ()
    highlights: tuple[str, ...] = ()
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
# TODO(stefan): this bio is DRAFTED from widely-published facts about Bitmovin.
# Please read it and correct anything wrong before it goes out — especially the
# founding year, the MPEG-DASH framing, and the `facts` strip.
# ---------------------------------------------------------------------------

PROFILE = Profile(
    name="Stefan Lederer",
    role="CEO & Co-founder, Bitmovin",
    tagline="Building video infrastructure for the internet. Angel investor in "
            "early-stage founders solving unglamorous, technical problems.",
    location="Paris, France",
    bio=(
        "I'm the co-founder and CEO of Bitmovin, where we build the encoding, "
        "playback and analytics infrastructure behind a large share of the world's "
        "online video. We started the company out of research on adaptive streaming "
        "and have been shipping video infrastructure ever since.",
        "Alongside Bitmovin I invest as an angel in early-stage companies — usually "
        "technical founders at pre-seed and seed, often in infrastructure, developer "
        "tools and media. In a handful of cases I lead the round and bring other "
        "investors in through an SPV.",
    ),
    facts=(
        ("2013", "Co-founded Bitmovin"),
        ("MPEG-DASH", "Co-authored the streaming standard"),
        ("Global", "Customers on every continent"),
    ),
    links=(
        Link("LinkedIn", "https://www.linkedin.com/in/stefanlederer/"),
        Link("X", "https://x.com/slederer", handle="@slederer"),
        Link("Bitmovin", "https://bitmovin.com"),
    ),
    # TODO(stefan): set the address you actually want public here.
    contact_email="",
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
# TODO(stefan): the three SPV entries below are real but need blurbs/sectors.
# Everything under "direct angel investments" is a PLACEHOLDER — replace the
# whole block with your actual portfolio. Delete any you don't want shown.
# ---------------------------------------------------------------------------

PORTFOLIO: tuple[Company, ...] = (
    # --- rounds I lead via an SPV ---
    Company(
        name="HockeyStack",
        blurb="PLACEHOLDER — one line on what HockeyStack does.",
        spv=True,
        role="Lead investor, syndicate via SPV",
        accent="purple",
    ),
    Company(
        name="GuardAero",
        blurb="PLACEHOLDER — one line on what GuardAero does.",
        spv=True,
        role="Lead investor, syndicate via SPV",
        accent="cyan",
    ),
    Company(
        name="Salvy",
        blurb="PLACEHOLDER — one line on what Salvy does.",
        spv=True,
        role="Lead investor, syndicate via SPV",
        accent="green",
    ),

    # --- direct angel investments (ALL PLACEHOLDERS — replace) ---
    Company(
        name="Example Co.",
        blurb="PLACEHOLDER — replace this block with your real portfolio.",
        sector="SaaS",
        stage="Seed",
        accent="orange",
    ),
)


# ---------------------------------------------------------------------------
# BITMOVIN AI INCUBATOR
#
# TODO(stefan): both cohorts below are PLACEHOLDERS. Replace with the real
# iterations — name, period, theme, how many teams, and 2-4 highlights each.
# ---------------------------------------------------------------------------

INCUBATOR = Incubator(
    name="Bitmovin AI Incubator",
    tagline="Two iterations of building AI products inside Bitmovin.",
    description=(
        "An internal incubator that gives small teams a fixed window, a budget and "
        "real customer access to take an AI idea from a hypothesis to something "
        "shippable. We have run it twice so far."
    ),
    cohorts=(
        Cohort(
            name="PLACEHOLDER — Iteration 1 name",
            period="PLACEHOLDER — e.g. Spring 2025",
            theme="PLACEHOLDER — one sentence on what this iteration focused on.",
            status="completed",
            accent="cyan",
            focus_areas=("PLACEHOLDER", "PLACEHOLDER"),
            highlights=(
                "PLACEHOLDER — what came out of it.",
                "PLACEHOLDER — a second outcome.",
            ),
        ),
        Cohort(
            name="PLACEHOLDER — Iteration 2 name",
            period="PLACEHOLDER — e.g. Autumn 2025",
            theme="PLACEHOLDER — one sentence on what changed the second time.",
            status="completed",
            accent="purple",
            focus_areas=("PLACEHOLDER", "PLACEHOLDER"),
            highlights=(
                "PLACEHOLDER — what came out of it.",
                "PLACEHOLDER — a second outcome.",
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
