## ADDED Requirements

### Requirement: The shipped shell SHALL use 数智小徽 branding
The frontend shell SHALL present the product as "数智小徽" in browser metadata, high-visibility branding text, and bundled public icon assets.

#### Scenario: Browser shell branding
- **WHEN** the application is loaded in a browser
- **THEN** the document title, mobile app title, and primary favicon/icon assets SHALL use 数智小徽 branding instead of Nanobot branding

#### Scenario: Sidebar branding
- **WHEN** the application shell is rendered
- **THEN** the sidebar branding area SHALL show 数智小徽 brand assets instead of the existing Nanobot logo treatment

### Requirement: The theme SHALL adopt the 数智小徽 palette
The frontend SHALL replace the current orange-led base theme with a 数智小徽 palette built around light government blue surfaces, blue-purple gradient emphasis, white translucent cards, and warm yellow-orange hover accents.

#### Scenario: Shared UI tokens
- **WHEN** common UI components render cards, borders, inputs, and accent states
- **THEN** they SHALL inherit the 数智小徽 token set from the shared theme definitions

#### Scenario: Sidebar interaction styling
- **WHEN** navigation items or shell controls are hovered or activated
- **THEN** they SHALL use the updated light-blue shell styling and warm highlight accents defined by the 数智小徽 theme

### Requirement: Chat empty state SHALL reflect the 数智小徽 brand
The chat empty state and high-visibility chat chrome SHALL use 数智小徽 brand assets, typography, and styling rather than the generic Nanobot placeholder.

#### Scenario: Empty chat page
- **WHEN** the current session has no messages
- **THEN** the chat view SHALL show 数智小徽 branded visuals and copy rather than the default Nanobot placeholder

#### Scenario: Session shell restyle
- **WHEN** the chat page renders the session list and conversation container
- **THEN** the page SHALL reflect the 数智小徽 light-blue shell style and branded high-exposure assets

### Requirement: Static brand assets SHALL ship with the frontend build
The Vite public asset bundle SHALL include the PNG icons, backgrounds, and font files required for the 数智小徽 shell.

#### Scenario: Production build references branded assets
- **WHEN** the frontend is built for production
- **THEN** the build SHALL resolve branded assets from the shipped frontend static bundle without requiring backend-only custom asset routes
