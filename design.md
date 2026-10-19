# KRIBU Demo Design System

## 1. Experience principles

- Evidence first: findings and source proof are visually connected.
- Calm, professional, and dense enough for business analysis without looking like a chat toy.
- Governance is visible: user scope, skill, source count, limitations, and approval status are never hidden.
- Progressive disclosure: show conclusions first, then details, raw evidence, and audit data.
- Never communicate authorization, confidence, or status using color alone.

## 2. Brand and color tokens

The palette preserves the existing KRIBU platform concept: deep navy, warm orange, and restrained status colors.

### Light theme

| Token | Value | Use |
|---|---|---|
| `background` | `#F6F7FA` | Application background |
| `surface` | `#FFFFFF` | Cards, drawers, panels |
| `heading` | `#0F1F3F` | Headings and strong foreground |
| `text` | `#1A2540` | Primary body text |
| `muted` | `#5A6C7D` | Secondary text |
| `border` | `#E0E6F0` | Dividers and controls |
| `brand` | `#FF6B35` | Primary action and key accent |
| `brand-soft` | `#FFF3E9` | Selected/highlight backgrounds |
| `navy-band` | `#0F1F3F` | Navigation and emphasis bands |
| `success` | `#0E9F6E` | Completed/approved |
| `warning` | `#C2410C` | Needs review/limited evidence |
| `danger` | `#B42318` | Denied/failed/destructive |
| `info` | `#34389F` | Processing/information |

### Dark theme

| Token | Value |
|---|---|
| `background` | `#0D1322` |
| `surface` | `#162036` |
| `heading` | `#F0F4F8` |
| `text` | `#E3E9F1` |
| `muted` | `#A8B5C7` |
| `border` | `#2A3A50` |
| `brand` | `#FF7A4A` |
| `success` | `#34D399` |
| `navy-band` | `#1B2C52` |

Check text/background pairs for WCAG 2.2 AA contrast in implementation. Orange is not used for small body text on white.

## 3. Typography

- **Display/headings:** Poppins, weights 600-700.
- **Body/UI:** Inter, weights 400-600.
- **Code, identifiers, evidence locators:** JetBrains Mono, weight 400-500.
- Bundle open-source font assets locally; keep system fallbacks (`Segoe UI`, Arial, sans-serif).

| Style | Desktop size / line height | Use |
|---|---|---|
| Display | 36 / 44 | Page hero only |
| H1 | 30 / 38 | Main page title |
| H2 | 24 / 32 | Major result section |
| H3 | 20 / 28 | Panel/card section |
| Body | 15 / 24 | Default reading text |
| Small | 13 / 20 | Metadata, helper text |
| Label | 12 / 16, semibold | Field labels and status labels |
| Code | 13 / 20 | IDs and locators |

Use sentence case. Avoid all caps except short status labels with adequate letter spacing.

## 4. Layout and spacing

- Base spacing unit: 4 px; common steps: 4, 8, 12, 16, 24, 32, 48, 64.
- Desktop shell: 240 px navigation, flexible content, optional 400-480 px evidence drawer.
- Maximum reading width: 800 px; analytical tables may use the full workspace.
- Page gutter: 24 px desktop, 16 px tablet/mobile.
- Card radius: 12 px; control radius: 8 px; pill radius: 999 px.
- Prefer borders and subtle background contrast over heavy shadows.

## 5. Core screens

1. **Sign in:** tenant-branded Keycloak entry.
2. **Workspace:** skill selector, query composer, recent runs, example questions.
3. **Run view:** progress steps, answer, findings, limitations, citations, artifacts.
4. **Evidence drawer:** source metadata, exact excerpt/table/cell, surrounding context, open preview.
5. **Source library:** upload, processing state, version, classification, ACL summary.
6. **Approval inbox:** action/artifact, diff/edit, supporting evidence, approve/reject with reason.
7. **Administration:** users/roles/attributes, skills, source metadata, policies, demo reset.
8. **Audit timeline:** actor, event, decision, policy/skill version, correlation ID, timestamp.

## 6. Component behavior

- **Finding card:** statement, evidence chips, confidence/limitation label, calculation/inference badge.
- **Evidence chip:** document title plus page/cell; keyboard-activatable; opens drawer without losing run context.
- **Progress stepper:** named graph stages, not model internals or chain-of-thought.
- **Data table:** sticky header, sorting, accessible caption, clear units, horizontal scroll on small screens.
- **Policy denial:** explains that access is unavailable and gives a correlation ID; does not reveal hidden record details.
- **Approval card:** clearly separates generated draft from the proposed action and from final execution state.
- **Toast:** only for transient confirmation; errors that require action remain inline.
- **Skeleton/loading:** match eventual layout; never show indefinite spinners without a status label.

## 7. Status language

| State | Label example | Visual treatment |
|---|---|---|
| Evidence-backed | `Supported` | Success icon and neutral evidence count |
| Model inference | `Inference` | Info icon and explicit explanation |
| Missing evidence | `Not established` | Warning icon and next-needed source |
| Conflicting evidence | `Conflict` | Warning icon and both sources |
| Policy blocked | `Access denied` | Lock icon and neutral safe message |
| Draft action | `Awaiting approval` | Clock icon; never styled as complete |
| Approved | `Approved` | Check icon, approver, timestamp |

Avoid numeric model confidence unless calibrated on an evaluation set. Prefer meaningful labels tied to evidence coverage.

## 8. Accessibility and responsive rules

- Full keyboard navigation, logical focus order, skip link, and visible focus ring.
- Semantic headings, landmarks, forms, tables, and live regions for streamed status.
- Minimum 44 by 44 px touch target where practical.
- Respect reduced-motion preferences; streamed content must not constantly steal focus.
- Use icons plus text for status. Provide accessible names for icon-only controls.
- On narrow screens, collapse navigation and make evidence a full-screen sheet; preserve citation context.
- Test at 320 px width and 200% zoom.

## 9. Content style

- Lead with the supported conclusion, then evidence and limitations.
- Use precise business language, dates, currencies, periods, and units.
- Say "The available records show..." rather than implying omniscience.
- Say "Not established by the available evidence" when a cause is unsupported.
- Never expose prompt text, hidden reasoning, internal policy expressions, or inaccessible resource names.
