# UTC admissions interface

Design workflow: [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), using the installed skill's design-system searches for university admissions and education dashboards.

Applied direction: a restrained, spacious interface with a navy navigation rail, blue actions, white content surfaces and limited yellow accents. The portfolio layout returned by the initial search was unsuitable; the second search's minimal dashboard guidance informed the layout. The requested blue identity overrides generic teal palette suggestions. Be Vietnam Pro is retained for Vietnamese readability.

- Navy navigation: `#102f60`; primary actions: `#1555ad`; text: `#182b49`; secondary text: `#566781`.
- Official UTC emblem: `frontend/public/utc-logo.png`, extracted from the school's published asset at `https://www.utc.edu.vn/assets/flatsome/images/logo.svg`. Preserve its colors and proportions.
- Shared visual tokens and responsive treatment: `frontend/app/utc-theme.css`.
- Navigation becomes an icon rail below 760px; every link retains an accessible name and tooltip.
- Use visible focus, minimum 44px controls and reduced-motion support. Table content scrolls within its container.
- Chat suggestions fill and focus the composer; session, retrieval and feedback behavior remain connected to the existing API.
