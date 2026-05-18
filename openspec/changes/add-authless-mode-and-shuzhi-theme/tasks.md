## 1. Authless backend path

- [x] 1.1 Add a shared authless-mode runtime helper and synthesized local admin identity for backend use
- [x] 1.2 Update REST auth dependencies and auth routes to respect authless mode without breaking normal JWT mode
- [x] 1.3 Update WebSocket auth and session ownership to allow tokenless chat when authless mode is enabled

## 2. Authless frontend shell

- [x] 2.1 Add frontend authless bootstrap/config wiring so the app can treat authless mode as already authenticated
- [x] 2.2 Update route guards and `/login` behavior so the shell skips login in authless mode
- [x] 2.3 Remove login from the default user journey while keeping the existing login implementation recoverable

## 3. 数智小徽 static assets and shell branding

- [x] 3.1 Copy the approved 数智小徽 static assets and font into the frontend public bundle
- [x] 3.2 Update browser metadata, app title, favicon/app icons, and shared branding text to 数智小徽
- [x] 3.3 Replace shared theme tokens with the 数智小徽 palette and typography foundations

## 4. High-exposure UI restyling

- [x] 4.1 Restyle the sidebar and shell chrome to use 数智小徽 branding assets and light-blue navigation treatment
- [x] 4.2 Restyle the chat empty state, session list, and high-visibility chat shell to match the 数智小徽 reference
- [x] 4.3 Ensure lower-priority pages inherit the new token system without page-by-page redesign

## 5. Verification

- [x] 5.1 Build the frontend and fix any asset or type errors introduced by the change
- [x] 5.2 Sanity-check the authless flow assumptions in code paths and update documentation/spec task checkboxes accordingly
