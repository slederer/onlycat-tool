"""Validation for content.py.

content.py is hand-edited whenever the portfolio or incubator changes, and it
auto-deploys on green CI. These tests are the guard rail: a bad paste fails here
rather than rendering a broken card in production.
"""

import pytest

import content


ALL_COMPANIES = content.PORTFOLIO + (content.BITMOVIN,)


class TestCompanies:
    @pytest.mark.parametrize("company", ALL_COMPANIES, ids=lambda c: c.name)
    def test_has_name(self, company):
        assert company.name.strip(), "company needs a name"

    @pytest.mark.parametrize("company", ALL_COMPANIES, ids=lambda c: c.name)
    def test_blurb_fits_a_card(self, company):
        assert len(company.blurb) <= content.MAX_BLURB, (
            f"{company.name}: blurb is {len(company.blurb)} chars, "
            f"max is {content.MAX_BLURB} — cards stop lining up past that"
        )

    @pytest.mark.parametrize("company", ALL_COMPANIES, ids=lambda c: c.name)
    def test_accent_is_a_real_token(self, company):
        assert company.accent in content.ACCENTS, (
            f"{company.name}: accent {company.accent!r} is not in ACCENTS — "
            f"it would render as a transparent chip"
        )

    @pytest.mark.parametrize("company", ALL_COMPANIES, ids=lambda c: c.name)
    def test_url_is_absolute_https_or_empty(self, company):
        assert company.url == "" or company.url.startswith("https://"), (
            f"{company.name}: url must be empty or start with https://"
        )

    @pytest.mark.parametrize("company", ALL_COMPANIES, ids=lambda c: c.name)
    def test_status_is_known(self, company):
        assert company.status in content.COMPANY_STATUSES

    def test_no_duplicate_names(self):
        names = [c.name.lower() for c in content.PORTFOLIO]
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"duplicate companies in PORTFOLIO: {dupes}"

    def test_spv_companies_carry_a_role(self):
        for company in content.spv_companies():
            assert company.role.strip(), (
                f"{company.name} is spv=True so it needs a role line "
                f"explaining the involvement"
            )

    def test_the_three_known_spvs_are_present(self):
        names = {c.name for c in content.spv_companies()}
        assert {"HockeyStack", "GuardAero", "Salvy"} <= names

    def test_spv_and_angel_partition_the_portfolio(self):
        spv = content.spv_companies()
        angel = content.angel_companies()
        assert len(spv) + len(angel) == len(content.PORTFOLIO)
        assert not set(spv) & set(angel)


class TestIncubator:
    def test_has_exactly_two_iterations(self):
        assert len(content.INCUBATOR.cohorts) == 2, (
            "the site lays the incubator out as two side-by-side cohorts"
        )

    @pytest.mark.parametrize("cohort", content.INCUBATOR.cohorts, ids=lambda c: c.name)
    def test_cohort_fields(self, cohort):
        assert cohort.name.strip()
        assert cohort.period.strip()
        assert cohort.theme.strip()
        assert cohort.status in content.COHORT_STATUSES
        assert cohort.accent in content.ACCENTS

    def test_cohorts_are_visually_distinct(self):
        accents = [c.accent for c in content.INCUBATOR.cohorts]
        assert len(set(accents)) == len(accents), (
            "give the two cohorts different accents so they read as a pair"
        )


class TestProjects:
    @pytest.mark.parametrize("project", content.PROJECTS, ids=lambda p: p.name)
    def test_host_is_a_bare_hostname(self, project):
        assert "://" not in project.host, f"{project.name}: host must not include a scheme"
        assert not project.host.endswith("/"), f"{project.name}: host must not end with /"
        assert "." in project.host

    @pytest.mark.parametrize("project", content.PROJECTS, ids=lambda p: p.name)
    def test_fields(self, project):
        assert project.name.strip()
        assert project.description.strip()
        assert project.emoji.strip()
        assert project.accent in content.ACCENTS

    @pytest.mark.parametrize("project", content.PROJECTS, ids=lambda p: p.name)
    def test_href_is_https(self, project):
        assert project.href == f"https://{project.host}"

    def test_no_duplicate_hosts(self):
        hosts = [p.host for p in content.PROJECTS]
        assert len(set(hosts)) == len(hosts)


class TestProfile:
    def test_core_fields(self):
        assert content.PROFILE.name == "Stefan Lederer"
        assert content.PROFILE.role.strip()
        assert content.PROFILE.tagline.strip()
        assert content.PROFILE.bio, "bio needs at least one paragraph"

    def test_links_are_absolute(self):
        assert content.PROFILE.links, "profile needs at least one link"
        for link in content.PROFILE.links:
            assert link.label.strip()
            assert link.url.startswith("https://"), f"{link.label}: url must be https://"

    def test_json_ld_shape(self):
        data = content.PROFILE.json_ld()
        assert data["@type"] == "Person"
        assert data["name"] == content.PROFILE.name
        # structured data must not drift from the visible links
        assert data["sameAs"] == [link.url for link in content.PROFILE.links if link.url]


class TestThesis:
    def test_has_both_sides(self):
        assert content.THESIS.bullets, "thesis needs 'what I look for' bullets"
        assert content.THESIS.anti_bullets, (
            "the anti-thesis is what saves founders time — keep at least one"
        )

    def test_headline_and_reach(self):
        assert content.THESIS.headline.strip()
        assert content.THESIS.how_to_reach.strip()


class TestPageContext:
    def test_supplies_every_key_the_homepage_uses(self):
        ctx = content.page_context()
        expected = {
            "profile", "thesis", "bitmovin", "spv_companies",
            "angel_companies", "incubator", "projects",
        }
        assert expected <= set(ctx)

    def test_no_key_is_none(self):
        for key, value in content.page_context().items():
            assert value is not None, f"page_context()[{key!r}] is None"


class TestCohortProjects:
    def test_second_cohort_shipped_seven_products(self):
        second = content.INCUBATOR.cohorts[1]
        assert len(second.projects) == 7

    @pytest.mark.parametrize(
        "project",
        [p for k in content.INCUBATOR.cohorts for p in k.projects],
        ids=lambda p: p.name,
    )
    def test_project_fields(self, project):
        assert project.name.strip()
        assert len(project.blurb) <= content.MAX_BLURB

    def test_no_duplicate_product_names(self):
        names = [p.name for k in content.INCUBATOR.cohorts for p in k.projects]
        assert len(set(names)) == len(names)

    def test_cohort_headcount_is_at_least_team_count(self):
        for k in content.INCUBATOR.cohorts:
            if k.people and k.teams:
                assert k.people >= k.teams, f"{k.name}: fewer people than teams?"


    def test_projects_total_is_not_less_than_what_is_listed(self):
        """Guards the "N of M shown" note against claiming a nonsense total."""
        for k in content.INCUBATOR.cohorts:
            if k.projects_total is not None:
                assert k.projects_total >= len(k.projects), (
                    f"{k.name}: projects_total={k.projects_total} but "
                    f"{len(k.projects)} are listed"
                )


class TestThesisSectors:
    def test_sectors_are_declared(self):
        assert content.THESIS.sectors, "founders filter on sector first"

    @pytest.mark.parametrize("sector", content.THESIS.sectors, ids=lambda s: s[0])
    def test_sector_shape(self, sector):
        label, accent = sector
        assert label.strip()
        assert accent in content.ACCENTS


class TestNoPlaceholdersEscape:
    """content.py auto-deploys on green CI, so unfinished text must fail here.

    A "Cheque: PLACEHOLDER ..." line reached production once; this is the guard.
    """

    BANNED = ("placeholder", "todo", "tbd", "lorem ipsum", "xxx")

    def _strings(self):
        """Every user-visible string in the content module, with a label."""
        import dataclasses

        def walk(obj, path):
            if isinstance(obj, str):
                yield path, obj
            elif dataclasses.is_dataclass(obj):
                for f in dataclasses.fields(obj):
                    yield from walk(getattr(obj, f.name), f"{path}.{f.name}")
            elif isinstance(obj, (tuple, list)):
                for i, item in enumerate(obj):
                    yield from walk(item, f"{path}[{i}]")

        for name in ("PROFILE", "THESIS", "BITMOVIN", "INCUBATOR",
                     "PORTFOLIO", "PROJECTS"):
            yield from walk(getattr(content, name), name)

    def test_no_placeholder_text_in_content(self):
        offenders = [
            (path, text) for path, text in self._strings()
            if any(word in text.lower() for word in self.BANNED)
        ]
        assert not offenders, "unfinished text would render on the live site:\n" + "\n".join(
            f"  {path}: {text[:70]!r}" for path, text in offenders
        )


class TestVoice:
    """Stefan asked for copy that does not read as machine-written.

    Em dashes are the giveaway he called out, so they fail the build.
    """

    def test_no_em_dashes_in_visible_copy(self):
        offenders = [
            (path, text)
            for path, text in TestNoPlaceholdersEscape()._strings()
            if "—" in text
        ]
        assert not offenders, "em dash in visible copy:\n" + "\n".join(
            f"  {path}: {text[:70]!r}" for path, text in offenders
        )
