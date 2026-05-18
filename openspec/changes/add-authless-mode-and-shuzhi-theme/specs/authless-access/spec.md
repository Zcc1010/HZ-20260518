## ADDED Requirements

### Requirement: Runtime authless mode bypasses interactive login
The system SHALL support a runtime authless mode that bypasses interactive login for WebUI users while keeping the existing authenticated flow available when the mode is disabled.

#### Scenario: REST request in authless mode
- **WHEN** authless mode is enabled and a frontend REST request is sent without a bearer token
- **THEN** the backend SHALL treat the request as authenticated with a synthesized local admin identity

#### Scenario: REST request in normal mode
- **WHEN** authless mode is disabled and a frontend REST request is sent without a bearer token
- **THEN** the backend SHALL continue to reject the request with an authentication error

### Requirement: WebSocket chat works without JWT in authless mode
The system SHALL allow `/ws/chat` connections to succeed without a JWT token when authless mode is enabled.

#### Scenario: Chat connection in authless mode
- **WHEN** authless mode is enabled and the frontend opens `/ws/chat` without a token
- **THEN** the backend SHALL accept the connection and bind it to the synthesized local admin identity

#### Scenario: Chat connection in normal mode
- **WHEN** authless mode is disabled and the frontend opens `/ws/chat` without a token
- **THEN** the backend SHALL continue to reject the connection as unauthenticated

### Requirement: Frontend shell skips the login page in authless mode
The frontend SHALL route directly into the application shell when authless mode is enabled and SHALL NOT require the user to visit the login page first.

#### Scenario: Initial app load in authless mode
- **WHEN** authless mode is enabled and the user opens the app root
- **THEN** the frontend SHALL render the protected application shell without redirecting to `/login`

#### Scenario: Login route in authless mode
- **WHEN** authless mode is enabled and the user navigates to `/login`
- **THEN** the frontend SHALL redirect to the default authenticated landing page

### Requirement: Authless mode preserves admin-only surfaces
The frontend and backend SHALL expose admin-only pages and operations in authless mode using the synthesized local admin identity.

#### Scenario: Admin route in authless mode
- **WHEN** authless mode is enabled and the user navigates to an admin-only route
- **THEN** the frontend SHALL allow access without a login redirect

#### Scenario: Admin-protected API in authless mode
- **WHEN** authless mode is enabled and an admin-protected API is requested
- **THEN** the backend SHALL authorize the request as the synthesized local admin identity
